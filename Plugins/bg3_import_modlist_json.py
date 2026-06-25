"""
Import a BG3 Mod Manager load-order JSON (modlist.json / saved order) and
apply it to the active Baldur's Gate 3 profile's modlist.txt.

BG3MM identifies mods by UUID (each entry in the JSON's "Order" array has a
UUID + Name).  Our modlist.txt orders mods by their *staging folder name*.
To bridge the two we scan every staged mod's .pak file(s), read the meta.lsx
UUID out of each (reusing the manager's own modsettings/pak_reader code), and
order the installed mods by where their UUID appears in the JSON.  A staging
folder may hold several paks (different UUIDs); it sorts to the earliest JSON
position among them.  A mod whose folder has no pak / no meta.lsx UUID falls
back to a case-insensitive match on the JSON entry's Name.  We then rewrite
modlist.txt so the matched mods follow the JSON's order, with:

  - BG3MM's list (and modsettings.lsx) is lowest-priority-first: entries
    nearer the bottom load later and win.  Our modlist.txt is the opposite
    (line 0 = highest priority), so the JSON order is REVERSED when written:
    JSON[0] lands at the bottom of modlist.txt, JSON[last] at the top.
  - Matched mods are all enabled.
  - Mods installed but absent from the JSON are DISABLED (placed above the
    imported order, but turned off so they don't deploy).
  - Separators are preserved at the top so groupings survive.

After writing, the dialog asks the running app to reload the modlist panel so
the new order is visible immediately.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from pathlib import Path

import customtkinter as ctk

from Utils import portal_filechooser as _pfc
from Utils.modlist import ModEntry, read_modlist, write_modlist
from Utils.modsettings import scan_mod_paks
from gui.theme import (
    ACCENT, ACCENT_HOV, BG_DEEP, BG_HEADER, BG_PANEL,
    TEXT_DIM, TEXT_MAIN,
    FONT_NORMAL, FONT_BOLD, FONT_SMALL,
)

PLUGIN_INFO = {
    "id":           "bg3_import_modlist_json",
    "label":        "Import BG3MM Load Order (.json)",
    "description":  "Convert a BG3 Mod Manager modlist.json into this profile's "
                    "load order and apply it.",
    "game_ids":     ["baldurs_gate_3"],
    "all_games":    False,
    "dialog_class": "BG3ImportModlistJsonWizard",
    "category":     "Load Order & Config",
}

_OK = "#6bc76b"
_ERR = "#e06c6c"
_WARN = "#d8a657"


# ---------------------------------------------------------------------------
# JSON file picker
#
# The manager's portal_filechooser.pick_file() hardcodes the "Mod Archives"
# filter and ignores any caller-supplied filter, so it would only show
# archives — not .json files.  We drive the same portal→zenity→kdialog→tkinter
# waterfall ourselves with a JSON filter, reusing the library's internal
# helpers, and fall back to the stock pick_file (which still lets the user
# switch to "All files") if those internals ever change.
# ---------------------------------------------------------------------------

_JSON_FILTERS = [
    ("Load Order (*.json)", ["*.json"]),
    ("All files", ["*"]),
]


def _zenity_json(title: str):
    result = _pfc._run_zenity([
        "--file-selection",
        f"--title={title}",
        "--file-filter=Load Order (*.json) | *.json",
        "--file-filter=All files | *",
    ])
    if result is None:
        return None
    if result.returncode == 0:
        p = Path(result.stdout.strip())
        if p.is_file():
            return p
    if result.returncode == 1 and not result.stderr.strip():
        return _pfc._CANCELLED
    return None


def _kdialog_json(title: str):
    if shutil.which("kdialog") is None:
        return None
    try:
        result = subprocess.run(
            ["kdialog", "--getopenfilename", str(Path.home()),
             "*.json|Load Order (*.json)", "--title", title],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            p = Path(result.stdout.strip())
            if p.is_file():
                return p
        if result.returncode == 1 and not result.stderr.strip():
            return _pfc._CANCELLED
        return None
    except FileNotFoundError:
        return None


def _tkinter_json(title: str):
    import tkinter.filedialog as fd

    def _fn():
        chosen = fd.askopenfilename(
            title=title,
            filetypes=[("Load Order", "*.json"), ("All files", "*")],
        )
        if chosen:
            p = Path(chosen)
            if p.is_file():
                return p
        return None

    return _pfc._tkinter_dispatch(_fn, "file", None)


def pick_json_file(title: str, callback) -> None:
    """Pick a .json file (portal/zenity/kdialog/tkinter), JSON-filtered.

    Runs on a background thread; *callback* gets the Path or None. Falls back
    to the manager's stock picker if the reused internals are unavailable.
    """
    def _worker() -> None:
        try:
            chosen = _pfc._run_waterfall(
                [
                    ("XDG portal (json)", lambda: _pfc._run_portal_file_impl(title, "", _JSON_FILTERS)),
                    ("zenity (json)", lambda: _zenity_json(title)),
                    ("kdialog (json)", lambda: _kdialog_json(title)),
                    ("tkinter (json)", lambda: _tkinter_json(title)),
                ],
                Path, None, "File",
            )
            callback(chosen)
        except Exception:
            # Reused internals changed — fall back to the stock archive picker
            # (the user can still switch to "All files" there).
            _pfc.pick_file(title, callback)

    threading.Thread(target=_worker, daemon=True).start()


# ---------------------------------------------------------------------------
# Parsing the BG3MM JSON
# ---------------------------------------------------------------------------

def _parse_order_json(path: Path) -> list[tuple[str, str]]:
    """Return an ordered list of (uuid, name) from a BG3MM order .json.

    Supports the two shapes BG3MM writes:
      1. A DivinityLoadOrder object:  {"Name": ..., "Order": [{"UUID","Name"}, ...]}
      2. A bare exported list:        [{"UUID"/"Uuid", "Name"}, ...]
    UUID/Name keys are matched case-insensitively to be tolerant of variants.
    """
    raw = json.loads(path.read_text(encoding="utf-8-sig"))

    if isinstance(raw, dict):
        order = raw.get("Order") or raw.get("order") or []
    elif isinstance(raw, list):
        order = raw
    else:
        order = []

    result: list[tuple[str, str]] = []
    for item in order:
        if not isinstance(item, dict):
            continue
        uuid = ""
        name = ""
        for k, v in item.items():
            kl = k.lower()
            if kl == "uuid" and isinstance(v, str):
                uuid = v.strip()
            elif kl == "name" and isinstance(v, str):
                name = v.strip()
        if uuid:
            result.append((uuid, name))
    return result


# ---------------------------------------------------------------------------
# Resolving the active profile + staging
# ---------------------------------------------------------------------------

def _active_profile_modlist(game) -> Path | None:
    """Path to the active profile's modlist.txt, or None if undeterminable."""
    profile_dir = getattr(game, "_active_profile_dir", None)
    if profile_dir is None:
        # Fall back to the last-active profile recorded on disk.
        try:
            name = game.get_last_active_profile()
            profile_dir = game.get_profile_root() / "profiles" / name
        except Exception:
            return None
    return Path(profile_dir) / "modlist.txt"


# ---------------------------------------------------------------------------
# Reorder logic
# ---------------------------------------------------------------------------

def _scan_staging_uuids(game) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Scan all enabled+disabled staged mods for their pak UUIDs.

    Returns ``(uuid_to_mod, mod_to_uuids)`` where:
      - ``uuid_to_mod``  maps each meta.lsx UUID -> staging folder name.
      - ``mod_to_uuids`` maps each staging folder name -> list of UUIDs it
        contributes (a folder may hold several .pak files, e.g. a load-order
        divider pack).  Folders with no .pak / no meta.lsx are absent here,
        which is how the caller detects mods that need the name fallback.

    We scan disabled mods too so an imported order can re-enable a mod the
    user had turned off.
    """
    staging = game.get_effective_mod_staging_path()
    entries = read_modlist(_active_profile_modlist(game))
    # scan_mod_paks keys on entry.name (the staging folder); feed it all
    # non-separator entries regardless of enabled state.
    mod_entries = [e for e in entries if not e.is_separator]
    by_uuid = scan_mod_paks(staging, mod_entries)

    uuid_to_mod: dict[str, str] = {}
    mod_to_uuids: dict[str, list[str]] = {}
    for uuid, info in by_uuid.items():
        mod = info.source_mod
        if not mod:
            continue
        uuid_to_mod[uuid] = mod
        mod_to_uuids.setdefault(mod, []).append(uuid)
    return uuid_to_mod, mod_to_uuids


def _plan_reorder(
    existing: list[ModEntry],
    order_uuids: list[tuple[str, str]],
    uuid_to_mod: dict[str, str],
    mod_to_uuids: dict[str, list[str]],
) -> tuple[list[ModEntry], list[str], list[tuple[str, str]]]:
    """Compute the new modlist entries plus diagnostics.

    Returns (new_entries, extra_mod_names, missing_json_entries) where:
      - new_entries:           reordered ModEntry list to write.
      - extra_mod_names:       installed mods not referenced by the JSON
                               (DISABLED, placed above the imported order).
      - missing_json_entries:  (uuid, name) in the JSON with no matching
                               installed mod.

    Ordering is driven by the pak UUIDs read from the staging folders, not by
    folder names.  Each installed mod is positioned by where its UUID first
    appears in the JSON's Order array.  A staging folder holding several paks
    (e.g. a load-order divider pack) sorts to the earliest JSON position among
    its UUIDs.  Mods whose folder has no pak / no meta.lsx UUID fall back to a
    case-insensitive match on the JSON entry's Name.

    The JSON is lowest-priority-first (BG3MM/modsettings.lsx convention);
    modlist.txt is highest-priority-first, so the matched run is reversed
    before being written (JSON[0] -> bottom, JSON[last] -> top).
    """
    separators = [e for e in existing if e.is_separator]
    mods = {e.name: e for e in existing if not e.is_separator}

    # JSON position of each UUID and each name (first occurrence wins).
    uuid_pos: dict[str, int] = {}
    name_pos: dict[str, int] = {}
    for i, (uuid, name) in enumerate(order_uuids):
        if uuid and uuid not in uuid_pos:
            uuid_pos[uuid] = i
        if name and name.casefold() not in name_pos:
            name_pos[name.casefold()] = i

    # Position each installed mod by its earliest UUID in the JSON; if the
    # folder has no UUID at all, fall back to matching the folder name against
    # a JSON entry's Name.
    mod_pos: dict[str, int] = {}
    for name in mods:
        positions = [uuid_pos[u] for u in mod_to_uuids.get(name, []) if u in uuid_pos]
        if positions:
            mod_pos[name] = min(positions)
        elif not mod_to_uuids.get(name):
            # No pak UUID for this folder — fall back to a name match.
            fallback = name_pos.get(name.casefold())
            if fallback is not None:
                mod_pos[name] = fallback

    # Matched mods, ordered by JSON position (stable on ties → modlist order).
    ordered_names = sorted(mod_pos, key=lambda n: mod_pos[n])
    matched_set = set(ordered_names)

    # JSON entries whose UUID matched no installed mod and whose name also
    # didn't resolve to an installed folder → "in JSON but not installed".
    placed_uuids = {u for n in ordered_names for u in mod_to_uuids.get(n, [])}
    placed_names = {n.casefold() for n in ordered_names}
    missing: list[tuple[str, str]] = []
    for uuid, name in order_uuids:
        if uuid in placed_uuids:
            continue
        if name and name.casefold() in placed_names:
            continue
        if uuid_to_mod.get(uuid):
            continue  # resolved to an installed mod via some other entry
        missing.append((uuid, name))

    extra = [n for n in mods if n not in matched_set]

    # Build the new entry list (top = highest priority in modlist.txt):
    #   [separators] + [extra mods, DISABLED] + [imported order, reversed]
    # The imported run is reversed so JSON[0] (lowest priority in BG3MM)
    # ends up at the bottom of modlist.txt and JSON[last] at the top.
    new_entries: list[ModEntry] = list(separators)
    for n in extra:
        e = mods[n]
        e.enabled = False
        e.locked = False
        new_entries.append(e)
    for n in reversed(ordered_names):
        e = mods[n]
        e.enabled = True
        e.locked = False
        new_entries.append(e)

    return new_entries, extra, missing


# ============================================================================
# Wizard dialog
# ============================================================================

class BG3ImportModlistJsonWizard(ctk.CTkFrame):

    def __init__(self, parent, game, log_fn=None, *, on_close=None, **_extra):
        super().__init__(parent, fg_color=BG_DEEP, corner_radius=0)
        self._on_close_cb = on_close or (lambda: None)
        self._game = game
        self._log = log_fn or (lambda msg: None)

        self._json_path: Path | None = None
        self._new_entries: list[ModEntry] | None = None

        title_bar = ctk.CTkFrame(self, fg_color=BG_HEADER, corner_radius=0, height=40)
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)
        ctk.CTkLabel(
            title_bar, text="Import BG3MM Load Order — Baldur's Gate 3",
            font=FONT_BOLD, text_color=TEXT_MAIN, anchor="w",
        ).pack(side="left", padx=12, pady=8)
        ctk.CTkButton(
            title_bar, text="✕", width=32, height=32, font=FONT_BOLD,
            fg_color="transparent", hover_color=BG_PANEL, text_color=TEXT_MAIN,
            command=self._on_close_cb,
        ).pack(side="right", padx=4, pady=4)

        self._body = ctk.CTkFrame(self, fg_color=BG_DEEP)
        self._body.pack(fill="both", expand=True, padx=20, pady=20)

        self._show_pick_step()

    def _clear_body(self):
        for w in self._body.winfo_children():
            w.destroy()

    # ------------------------------------------------------------------
    # Step 1 — pick the JSON
    # ------------------------------------------------------------------

    def _show_pick_step(self):
        self._clear_body()

        ctk.CTkLabel(
            self._body, text="Step 1: Select a BG3 Mod Manager order file",
            font=FONT_BOLD, text_color=TEXT_MAIN,
        ).pack(pady=(0, 8))

        ctk.CTkLabel(
            self._body,
            text="Choose a modlist.json (or an exported saved-order .json) from "
                 "BG3 Mod Manager.\nMods are matched to your installed mods by UUID.",
            font=FONT_SMALL, text_color=TEXT_DIM, justify="center", wraplength=480,
        ).pack(pady=(0, 16))

        self._pick_status = ctk.CTkLabel(
            self._body, text="No file selected.",
            font=FONT_NORMAL, text_color=TEXT_DIM, justify="center", wraplength=480,
        )
        self._pick_status.pack(pady=(0, 16))

        btn_frame = ctk.CTkFrame(self._body, fg_color="transparent")
        btn_frame.pack(side="bottom", pady=(8, 0))

        self._next_btn = ctk.CTkButton(
            btn_frame, text="Preview →", width=130, height=36, font=FONT_BOLD,
            fg_color=ACCENT, hover_color=ACCENT_HOV, text_color="white",
            command=self._show_preview_step, state="disabled",
        )
        self._next_btn.pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            btn_frame, text="Browse…", width=110, height=36, font=FONT_BOLD,
            fg_color=BG_HEADER, hover_color="#3d3d3d", text_color=TEXT_MAIN,
            command=self._browse,
        ).pack(side="right")

    def _browse(self):
        def _on_picked(path: Path | None) -> None:
            if path and path.is_file():
                self._json_path = path
                self._set_label(self._pick_status, f"Selected: {path.name}", _OK)
                try:
                    self._next_btn.configure(state="normal")
                except Exception:
                    pass

        pick_json_file(
            "Select a BG3MM order .json",
            lambda p: self.after(0, lambda: _on_picked(p)),
        )

    # ------------------------------------------------------------------
    # Step 2 — preview the plan
    # ------------------------------------------------------------------

    def _show_preview_step(self):
        self._clear_body()
        self._new_entries = None

        ctk.CTkLabel(
            self._body, text="Step 2: Review changes",
            font=FONT_BOLD, text_color=TEXT_MAIN,
        ).pack(pady=(0, 8))

        summary = ctk.CTkLabel(
            self._body, text="Reading order and scanning installed mods…",
            font=FONT_NORMAL, text_color=TEXT_DIM, justify="center", wraplength=520,
        )
        summary.pack(pady=(0, 8))

        textbox = ctk.CTkTextbox(
            self._body, font=FONT_SMALL, fg_color=BG_PANEL, text_color=TEXT_MAIN,
            wrap="none",
        )
        textbox.pack(fill="both", expand=True, pady=(4, 12))

        btn_frame = ctk.CTkFrame(self._body, fg_color="transparent")
        btn_frame.pack(side="bottom", pady=(4, 0))

        self._apply_btn = ctk.CTkButton(
            btn_frame, text="Apply Order", width=140, height=36, font=FONT_BOLD,
            fg_color="#2d7a2d", hover_color="#3a9e3a", text_color="white",
            command=self._apply, state="disabled",
        )
        self._apply_btn.pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            btn_frame, text="← Back", width=100, height=36, font=FONT_BOLD,
            fg_color=BG_HEADER, hover_color="#3d3d3d", text_color=TEXT_MAIN,
            command=self._show_pick_step,
        ).pack(side="right")

        # Compute the plan (synchronous; pak header reads are cheap).
        try:
            order_uuids = _parse_order_json(self._json_path)
            if not order_uuids:
                self._set_label(summary, "No mod entries found in that JSON.", _ERR)
                return

            modlist_path = _active_profile_modlist(self._game)
            if modlist_path is None:
                self._set_label(summary, "Could not determine the active profile.", _ERR)
                return

            existing = read_modlist(modlist_path)
            uuid_to_mod, mod_to_uuids = _scan_staging_uuids(self._game)

            new_entries, extra, missing = _plan_reorder(
                existing, order_uuids, uuid_to_mod, mod_to_uuids,
            )
            self._new_entries = new_entries

            matched = len(order_uuids) - len(missing)
            self._set_label(
                summary,
                f"{matched} of {len(order_uuids)} order entries matched installed "
                f"mods.   {len(extra)} extra installed mod(s) DISABLED (not in "
                f"the order).   {len(missing)} not installed.",
                TEXT_MAIN,
            )

            lines: list[str] = []
            lines.append("=== NEW LOAD ORDER (top = highest priority) ===")
            extra_set = set(extra)
            idx = 0
            for e in new_entries:
                if e.is_separator:
                    lines.append(f"   --- {e.display_name} ---")
                elif e.name in extra_set:
                    lines.append(f"   ✗ {e.name}   [not in JSON – DISABLED]")
                else:
                    idx += 1
                    lines.append(f"{idx:>3}. {e.name}")
            if missing:
                lines.append("")
                lines.append("=== IN JSON BUT NOT INSTALLED (skipped) ===")
                for uuid, name in missing:
                    label = name or "(unnamed)"
                    lines.append(f"   {label}   [{uuid}]")

            textbox.insert("1.0", "\n".join(lines))
            textbox.configure(state="disabled")
            self._apply_btn.configure(state="normal")

        except Exception as exc:
            self._log(f"BG3 Import: preview error: {exc}")
            self._set_label(summary, f"Error: {exc}", _ERR)

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def _apply(self):
        if not self._new_entries:
            return
        try:
            modlist_path = _active_profile_modlist(self._game)
            write_modlist(modlist_path, self._new_entries)
            self._log(f"BG3 Import: wrote new load order to {modlist_path}")
            self._reload_app_modlist()
            self._show_done_step()
        except Exception as exc:
            self._log(f"BG3 Import: apply error: {exc}")
            self._set_label(self._apply_btn, "Failed", _ERR)

    def _reload_app_modlist(self):
        """Ask the running app to reload the modlist panel from disk."""
        try:
            app = self.winfo_toplevel()
            panel = getattr(app, "_mod_panel", None)
            topbar = getattr(app, "_topbar", None)
            if panel is None or topbar is None:
                return
            profile = topbar._profile_var.get()
            app.after(0, lambda: panel.load_game(self._game, profile))
        except Exception as exc:
            self._log(f"BG3 Import: could not refresh modlist panel: {exc}")

    def _show_done_step(self):
        self._clear_body()
        ctk.CTkLabel(
            self._body, text="Load order applied",
            font=FONT_BOLD, text_color=_OK,
        ).pack(pady=(20, 8))
        ctk.CTkLabel(
            self._body,
            text="The modlist has been reordered to match the BG3MM order.\n"
                 "Deploy to push the new load order to the game.",
            font=FONT_NORMAL, text_color=TEXT_DIM, justify="center", wraplength=480,
        ).pack(pady=(0, 20))
        ctk.CTkButton(
            self._body, text="Done", width=120, height=36, font=FONT_BOLD,
            fg_color="#2d7a2d", hover_color="#3a9e3a", text_color="white",
            command=self._on_close_cb,
        ).pack(side="bottom")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_label(self, widget, text: str, color: str = TEXT_DIM):
        try:
            self.after(0, lambda: widget.configure(text=text, text_color=color))
        except Exception:
            pass
