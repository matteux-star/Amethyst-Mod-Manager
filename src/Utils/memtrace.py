"""Lightweight memory-leak diagnostic — env-gated, prints to stderr.

Purpose
-------
A from-source session that climbs to ~2 GB RSS but resets to ~150 MB on
restart is a leak. This module lets you capture before/after snapshots of
*what* is growing (RSS, Python object counts by type, live Tk items/images)
so the leak can be pinned to a specific class instead of guessed at.

Usage
-----
- Auto-enabled when run from source (no AppImage env present), or force with
  ``MM_MEMTRACE=1`` / disable with ``MM_MEMTRACE=0``.
- Press **F12** in the app to dump a snapshot to the terminal (stderr).
  Each dump diffs against the *previous* dump, so the workflow is:
      1. Launch, press F12 once  -> baseline
      2. Do a task (e.g. create a modlist)
      3. Press F12 again         -> shows the delta
  Whatever type count climbs every cycle is your leak.
- Snapshots also print automatically every 60s (heartbeat) so a slow climb
  is visible even if you forget to press F12. Set ``MM_MEMTRACE_HEARTBEAT=0``
  to silence the heartbeat (keypress dumps still work).

Output goes to **stderr**, which ``run.sh`` tees live to the terminal and to
run-stderr.log, so no extra wiring is needed for a from-source run.
"""

from __future__ import annotations

import gc
import os
import sys
import time
from collections import Counter

_PREV: Counter | None = None        # previous object-type histogram
_PREV_RSS: int | None = None        # previous RSS in bytes
_DUMP_COUNT = 0
_HEARTBEAT_ID = None                 # tk after() id for the heartbeat loop


def _running_from_source() -> bool:
    """True when not launched via the AppImage (run.sh unsets these)."""
    return not any(os.environ.get(k) for k in ("APPDIR", "APPIMAGE", "SHARUN_DIR"))


def is_enabled() -> bool:
    val = os.environ.get("MM_MEMTRACE")
    if val is not None:
        return val not in ("0", "", "false", "False")
    return _running_from_source()


def _rss_bytes() -> int:
    """Resident set size in bytes (Linux), 0 if unavailable."""
    try:
        with open("/proc/self/statm", "rb") as f:
            pages = int(f.read().split()[1])  # field 2 = resident pages
        return pages * os.sysconf("SC_PAGE_SIZE")
    except Exception:
        try:
            import resource
            # ru_maxrss is in KiB on Linux (peak, not current — fallback only)
            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        except Exception:
            return 0


def _fmt_mb(n: int) -> str:
    return f"{n / (1024 * 1024):8.1f} MB"


def _fmt_signed(n: int) -> str:
    return f"+{n}" if n > 0 else str(n)


def _tk_object_counts(root) -> tuple[int, int]:
    """(live canvas items across all Canvas widgets, live Tk image count)."""
    items = 0
    images = 0
    try:
        # Number of registered Tk images (PhotoImage/BitmapImage) in the interp.
        names = root.tk.call("image", "names")
        if isinstance(names, str):
            names = root.tk.splitlist(names)
        images = len(names)
    except Exception:
        pass
    try:
        from tkinter import Canvas

        def _walk(w):
            nonlocal items
            if isinstance(w, Canvas):
                try:
                    items += len(w.find_all())
                except Exception:
                    pass
            for child in w.winfo_children():
                _walk(child)

        _walk(root)
    except Exception:
        pass
    return items, images


def _histogram() -> Counter:
    """Count live Python objects by type name."""
    counts: Counter = Counter()
    for obj in gc.get_objects():
        counts[type(obj).__name__] += 1
    return counts


def dump(root=None, reason: str = "") -> None:
    """Print a memory snapshot to stderr, diffed against the previous dump."""
    global _PREV, _PREV_RSS, _DUMP_COUNT
    if not is_enabled():
        return
    _DUMP_COUNT += 1

    gc.collect()  # collect cycles first so we measure genuinely-retained objects

    rss = _rss_bytes()
    hist = _histogram()
    total_objs = sum(hist.values())

    tk_items = tk_images = -1
    if root is not None:
        try:
            tk_items, tk_images = _tk_object_counts(root)
        except Exception:
            pass

    out = sys.stderr
    tag = f"[MEM #{_DUMP_COUNT}]"
    when = time.strftime("%H:%M:%S")
    head = f"{tag} {when}"
    if reason:
        head += f" ({reason})"
    print(f"\n{head}", file=out)
    print(f"{tag} RSS: {_fmt_mb(rss)}", end="", file=out)
    if _PREV_RSS is not None:
        delta = rss - _PREV_RSS
        sign = "+" if delta >= 0 else "-"
        print(f"   (Δ {sign}{abs(delta) / (1024*1024):.1f} MB since last dump)", file=out)
    else:
        print(file=out)
    print(f"{tag} Python objects: {total_objs:,}"
          + (f"   (Δ {_fmt_signed(total_objs - sum(_PREV.values()))})" if _PREV else ""),
          file=out)
    if tk_items >= 0:
        print(f"{tag} Tk canvas items: {tk_items:,}   Tk images: {tk_images:,}", file=out)
    print(f"{tag} GC tracked uncollectable (gc.garbage): {len(gc.garbage)}", file=out)

    # Top growers since the last dump — this is where the leak shows up.
    if _PREV is not None:
        growth = Counter()
        for name, cnt in hist.items():
            d = cnt - _PREV.get(name, 0)
            if d > 0:
                growth[name] = d
        if growth:
            print(f"{tag} Top object-count GROWTH since last dump:", file=out)
            for name, d in growth.most_common(15):
                print(f"{tag}     +{d:>7,}  {name}  (now {hist[name]:,})", file=out)
        else:
            print(f"{tag} No object-type grew since last dump.", file=out)
    else:
        print(f"{tag} (baseline — press F12 again after a task to see growth)", file=out)
        print(f"{tag} Largest object types:", file=out)
        for name, cnt in hist.most_common(10):
            print(f"{tag}     {cnt:>8,}  {name}", file=out)

    out.flush()
    _PREV = hist
    _PREV_RSS = rss


def _describe(obj, depth: int = 0) -> str:
    """One-line description of an object for referrer traces."""
    t = type(obj).__name__
    try:
        if isinstance(obj, dict):
            keys = list(obj.keys())[:4]
            return f"dict(len={len(obj)}, keys≈{keys})"
        if isinstance(obj, (list, tuple, set)):
            return f"{t}(len={len(obj)})"
        if t in ("function", "method"):
            mod = getattr(obj, "__module__", "?")
            qn = getattr(obj, "__qualname__", getattr(obj, "__name__", "?"))
            return f"{t} {mod}.{qn}"
        if t == "cell":
            return "cell (closure variable)"
        if t == "frame":
            return f"frame {obj.f_code.co_filename}:{obj.f_lineno}"
        return f"{t} (id={id(obj):#x})"
    except Exception:
        return t


def trace_leak(root=None, type_name: str | None = None) -> None:
    """Find live instances of a leaked widget type and report what retains them.

    Bound to Shift+F12. By default targets the CTk type most associated with
    overlay leaks. Prints, for a few sample instances, the chain of referrers
    (skipping memtrace's own frames) so the owning closure / dict / panel that
    keeps the widget alive after close is named.
    """
    if not is_enabled():
        return
    out = sys.stderr
    gc.collect()

    # Candidate leak types, in priority order — first one with live instances wins.
    candidates = [type_name] if type_name else [
        "DrawEngine", "CTkCanvas", "CTkButton", "CTkLabel", "NexusBrowserOverlay",
    ]
    targets: list = []
    chosen = None
    for name in candidates:
        if not name:
            continue
        insts = [o for o in gc.get_objects() if type(o).__name__ == name]
        if insts:
            chosen = name
            targets = insts
            break

    print(f"\n[LEAKTRACE] target type: {chosen!r}  live instances: {len(targets)}",
          file=out)
    if not targets:
        print("[LEAKTRACE] nothing to trace.", file=out)
        out.flush()
        return

    # Ignore memtrace's own containers so we don't report ourselves as a holder.
    sample = targets[:3]
    ignore_ids = {id(targets), id(sample), id(trace_leak), id(candidates),
                  id(gc.get_objects)}

    def _is_noise(r) -> bool:
        tn = type(r).__name__
        if tn == "frame":
            return "memtrace" in getattr(r.f_code, "co_filename", "")
        # list_iterator / enumerate / the local sample lists are trace artifacts.
        if tn in ("list_iterator", "tuple_iterator", "enumerate"):
            return True
        return id(r) in ignore_ids

    def _referrers(obj, hops: int, seen: set) -> None:
        if hops <= 0:
            return
        refs = gc.get_referrers(obj)
        shown = 0
        for r in refs:
            rid = id(r)
            if rid in seen or _is_noise(r) or r is refs:
                continue
            seen.add(rid)
            print(f"[LEAKTRACE]   {'  ' * (3 - hops)}↑ held by {_describe(r)}", file=out)
            shown += 1
            if shown >= 3:
                break
            _referrers(r, hops - 1, seen)

    for i, obj in enumerate(sample):
        print(f"[LEAKTRACE] sample #{i} {_describe(obj)}:", file=out)
        _referrers(obj, hops=3, seen={id(sample), id(targets)})
    out.flush()


def _heartbeat(root) -> None:
    global _HEARTBEAT_ID
    try:
        dump(root, reason="heartbeat")
    finally:
        try:
            _HEARTBEAT_ID = root.after(60_000, lambda: _heartbeat(root))
        except Exception:
            pass


def install(root) -> None:
    """Wire F12 -> dump and start the heartbeat. No-op when disabled."""
    if not is_enabled():
        return
    try:
        root.bind_all("<F12>", lambda _e: dump(root, reason="F12"), add="+")
        # Shift+F12: trace what is retaining leaked widgets (run right AFTER
        # closing a panel you expect to free — it names the holding referrer).
        root.bind_all("<Shift-F12>", lambda _e: trace_leak(root), add="+")
    except Exception:
        pass
    print("[MEM] memtrace enabled — F12 = snapshot, Shift+F12 = trace leaked-"
          "widget referrers (run just after closing a panel). Baseline now:",
          file=sys.stderr)
    dump(root, reason="startup baseline")
    if os.environ.get("MM_MEMTRACE_HEARTBEAT", "1") not in ("0", "", "false", "False"):
        try:
            root.after(60_000, lambda: _heartbeat(root))
        except Exception:
            pass
