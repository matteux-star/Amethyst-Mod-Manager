#!/usr/bin/env python3
"""Source-preserving helper to wrap user-facing strings in self.tr(...).

This does NOT do a full AST round-trip (that would reflow the whole file and
destroy comments/formatting). Instead it locates specific, provably-safe string
argument nodes and rewrites ONLY those byte spans, leaving everything else
untouched.

Scope (conservative on purpose):
  * The first positional arg of a configured set of calls/constructors, when
    that arg is:
      - a plain string literal            "Foo"           -> self.tr("Foo")
      - an implicit-concat of literals     "a" "b"         -> self.tr("a" "b")
      - a simple f-string with only {name}/{obj.attr} field exprs
                                           f"Total: {x}"   -> self.tr("Total: {0}").format(x)
  * Anything else (method calls in the f-string, ternaries, format specs,
    already-wrapped tr() calls, non-self classes) is SKIPPED and reported so a
    human can handle it.

Usage:
    python3 tools/i18n_wrap.py <file.py> [--apply]     # dry-run unless --apply
    python3 tools/i18n_wrap.py <file.py> --list        # just report sites

It prints, per file, how many sites it wrapped and how many it skipped (with
line numbers + reason) so the residue can be finished by hand.
"""
from __future__ import annotations

import ast
import sys
from dataclasses import dataclass

# Call names whose FIRST positional arg is user-facing text. Constructors are
# matched by the callee's attribute/name; methods by attribute name.
WRAP_CALLS = {
    # widgets built with visible text
    "QLabel", "QPushButton", "QCheckBox", "QRadioButton", "QToolButton",
    "QGroupBox", "QAction",
    # NB: NOT QLineEdit — its ctor arg is initial *content*, not a label.
    # setters
    "setText", "setToolTip", "setPlaceholderText", "setWindowTitle",
    "setStatusTip", "setTitle", "addAction", "setWhatsThis",
    # app notifications: self._notify("msg", state)
    "_notify",
    # project-specific helpers whose FIRST positional arg is display text
    # (verified signatures): wizard page headers, buttons, section labels,
    # status/hint lines. NB: only helpers where text is the FIRST arg — e.g.
    # _make_note(self, lay, text) has text SECOND, so it's handled by hand.
    "_step_page", "_small_btn", "_text_button", "_color_button",
    "_section_header", "_section_title", "_section_label", "_hint",
    "_accent_btn", "_field_label", "_primary", "_page", "_help_label",
    "_green_btn", "_set_prefix_status", "_panel", "_status", "_set_tip",
    "_make_section_header", "_mono_edit", "_append_box",
}

# Helpers whose display text is the SECOND positional arg (arg index 1), e.g.
# self._make_note(layout, "text"). Same wrapping, different arg position.
WRAP_CALLS_ARG2 = {
    "_make_note",
    # _set_status(self, status_label, "text", color) in the wizard views. NB a
    # few files define _set_status(self, "text", kind) with text FIRST — those
    # are handled by hand (the tool skips arg-1 there since it's not a string).
    "_set_status",
    # open_tab(widget, "Tab Title", key) / open_scoped_tab(widget, "Title", ...)
    # — the tab-bar label is the 2nd arg.
    "open_tab", "open_scoped_tab",
}

# Receiver expression to use for tr(). Everything here is inside a QObject
# subclass method, so "self" is right; a plain-class fallback would use
# QCoreApplication.translate but we SKIP those (reported) instead of guessing.
TR_RECEIVER = "self"


@dataclass
class Site:
    lineno: int
    col: int
    end_lineno: int
    end_col: int
    kind: str          # "plain" | "fstring"
    replacement: str
    reason: str = ""


def _callee_name(call: ast.Call) -> str | None:
    f = call.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return None


def _is_plain_str(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _worth_translating(s: str) -> bool:
    """True only if the string has actual letters to translate.

    Skips empty strings and decorative glyph/symbol/punctuation-only labels
    (e.g. "●", "▶", "⊟", "…", "1/2") — wrapping those in tr() just pollutes the
    catalogue with untranslatable noise.
    """
    return bool(s) and any(ch.isalpha() for ch in s)


def _fstring_to_template(node: ast.JoinedStr) -> str | None:
    """Return `self.tr("template").format(args)` or None if not safely convertible.

    Only handles field exprs that are a bare Name or a dotted attribute chain of
    Names (e.g. x, obj.attr, a.b.c) and literal text parts. Rejects format specs,
    conversions (!r), calls, subscripts, ternaries, etc.
    """
    template_parts: list[str] = []
    args: list[str] = []
    for part in node.values:
        if isinstance(part, ast.Constant) and isinstance(part.value, str):
            # Escape braces so .format() treats them as literal.
            template_parts.append(part.value.replace("{", "{{").replace("}", "}}"))
        elif isinstance(part, ast.FormattedValue):
            if part.conversion != -1 or part.format_spec is not None:
                return None
            expr = _dotted_name(part.value)
            if expr is None:
                return None
            template_parts.append("{%d}" % len(args))
            args.append(expr)
        else:
            return None
    if not args:
        # No interpolation — it's effectively a plain string; caller handles.
        return None
    template = "".join(template_parts)
    # Build a double-quoted Python literal safely via repr, but prefer keeping
    # it readable: use ast to render the string constant.
    literal = _py_str_literal(template)
    return f'{TR_RECEIVER}.tr({literal}).format({", ".join(args)})'


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _py_str_literal(s: str) -> str:
    # Render as a double-quoted literal; repr may pick single quotes, so
    # normalise when safe.
    r = repr(s)
    if r.startswith("'") and '"' not in s and "\\" not in r:
        r = '"' + r[1:-1] + '"'
    return r


def _self_method_ranges(tree: ast.AST) -> list[tuple[int, int]]:
    """Line ranges of every function whose first arg is `self`.

    Only inside such a method is `self.tr(...)` valid. A wrap site outside all
    of these (module-level function, staticmethod, plain-class method) would
    raise NameError at runtime, so we report those instead of wrapping.
    """
    ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = node.args
            first = (a.posonlyargs + a.args)[:1]
            if first and first[0].arg == "self":
                ranges.append((node.lineno, node.end_lineno or node.lineno))
    return ranges


def find_sites(tree: ast.AST, src: str) -> tuple[list[Site], list[Site]]:
    wrapped: list[Site] = []
    skipped: list[Site] = []
    self_ranges = _self_method_ranges(tree)

    def _has_self(lineno: int) -> bool:
        return any(lo <= lineno <= hi for lo, hi in self_ranges)

    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        name = _callee_name(call)
        # Which positional arg carries the display text (0 for most, 1 for the
        # _make_note-style helpers).
        if name in WRAP_CALLS:
            arg_idx = 0
        elif name in WRAP_CALLS_ARG2:
            arg_idx = 1
        else:
            continue
        if len(call.args) <= arg_idx:
            continue
        arg = call.args[arg_idx]

        # Already wrapped? self.tr(...) / translate(...) as the arg.
        if isinstance(arg, ast.Call) and _callee_name(arg) in ("tr", "translate"):
            continue

        # tr() needs a QObject `self` in scope; if this call isn't inside a
        # self-method, report it (unless it's a non-translatable literal).
        translatable = (
            (_is_plain_str(arg) and _worth_translating(arg.value))
            or isinstance(arg, (ast.JoinedStr, ast.IfExp)))
        if translatable and not _has_self(arg.lineno):
            skipped.append(Site(arg.lineno, arg.col_offset, arg.end_lineno,
                                arg.end_col_offset, "noself", "",
                                "no self in scope (manual)"))
            continue

        if _is_plain_str(arg):
            if not _worth_translating(arg.value):
                continue  # empty / glyph-only / non-letter — not translatable
            lit = _slice(src, arg)
            wrapped.append(Site(arg.lineno, arg.col_offset,
                                arg.end_lineno, arg.end_col_offset,
                                "plain", f"{TR_RECEIVER}.tr({lit})"))
        elif isinstance(arg, ast.JoinedStr):
            repl = _fstring_to_template(arg)
            if repl is None:
                skipped.append(Site(arg.lineno, arg.col_offset, arg.end_lineno,
                                    arg.end_col_offset, "fstring", "",
                                    "complex f-string (manual)"))
            else:
                wrapped.append(Site(arg.lineno, arg.col_offset, arg.end_lineno,
                                    arg.end_col_offset, "fstring", repl))
        elif isinstance(arg, ast.IfExp):
            skipped.append(Site(arg.lineno, arg.col_offset, arg.end_lineno,
                                arg.end_col_offset, "ternary", "",
                                "ternary text (manual)"))
        # else: not a string arg (variable, etc.) — ignore silently.

    return wrapped, skipped


def _slice(src: str, node: ast.AST) -> str:
    """Exact source text of `node`, sliced by BYTE offsets (ast cols are bytes)."""
    data = src.encode("utf-8")
    line_start = [0]
    for b in data.splitlines(keepends=True):
        line_start.append(line_start[-1] + len(b))
    start = line_start[node.lineno - 1] + node.col_offset
    end = line_start[node.end_lineno - 1] + node.end_col_offset
    return data[start:end].decode("utf-8")


def apply_sites(src: str, sites: list[Site]) -> str:
    # ast col offsets are UTF-8 BYTE offsets, so do all slicing in bytes (a
    # non-ASCII char like "…" is 3 bytes but 1 str codepoint — mixing the two
    # corrupts spans). Decode back to str only at the end.
    data = src.encode("utf-8")
    # Byte offset of the start of each line (1-based line -> byte index).
    line_start = [0]
    for b in data.splitlines(keepends=True):
        line_start.append(line_start[-1] + len(b))

    def off(lineno, col):
        return line_start[lineno - 1] + col

    spans = sorted(
        ((off(s.lineno, s.col), off(s.end_lineno, s.end_col),
          s.replacement.encode("utf-8"))
         for s in sites),
        reverse=True)
    out = data
    for start, end, repl in spans:
        out = out[:start] + repl + out[end:]
    return out.decode("utf-8")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if not args:
        print(__doc__)
        return 2
    path = args[0]
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    src_lines = src.splitlines()
    wrapped, skipped = find_sites(tree, src)

    print(f"{path}: {len(wrapped)} wrappable, {len(skipped)} need manual review")
    if "--list" in flags or "--apply" not in flags:
        for s in skipped:
            print(f"  SKIP L{s.lineno}: {s.reason}: "
                  f"{src_lines[s.lineno-1].strip()[:80]}")
    if "--apply" in flags and wrapped:
        new = apply_sites(src, wrapped)
        # sanity: must still parse
        ast.parse(new)
        open(path, "w", encoding="utf-8").write(new)
        print(f"  applied {len(wrapped)} wraps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
