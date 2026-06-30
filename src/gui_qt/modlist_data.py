"""Real modlist metadata (versions / installed dates / flags from meta.ini, and
conflicts from filemap overrides). Pure backend calls — no Qt, no gui.* — so
they can run on a worker thread.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from Utils.modlist import ModEntry


# Flag bits for the Flags column — only the ones the Tk app shows there.
# (FOMOD/BAIN are install methods, NOT flag icons; note.png = a real saved
#  user note, not FOMOD. brush = xedit-modified — both wired in a later pass.)
FLAG_UPDATE = 1 << 0       # has_update & not ignored
FLAG_ENDORSED = 1 << 1
FLAG_ROOT = 1 << 2
FLAG_MODIFIED_MF = 1 << 3  # modified in the Mod Files tab (excluded files/strip)


def read_meta_for_entries(entries: list[ModEntry], staging_dir: Path):
    """Return a MetaInfo-ish tuple keyed by mod name.

    versions[name]   -> version string ("" if none)
    installed[name]  -> short date string ("" if none)
    flags[name]      -> int bitmask of FLAG_* above
    categories[name] -> Nexus category display name ("" if none)
    updates          -> set of mod names with a pending update
    fomod            -> set of mod names installed via FOMOD (meta.is_fomod)
    bain             -> set of mod names installed via BAIN (meta.is_bain)
    """
    versions: dict[str, str] = {}
    installed: dict[str, str] = {}
    flags: dict[str, int] = {}
    categories: dict[str, str] = {}
    updates: set[str] = set()
    fomod: set[str] = set()
    bain: set[str] = set()

    try:
        from Nexus.nexus_meta import read_meta
    except Exception:
        return versions, installed, flags, categories, updates, fomod, bain

    for e in entries:
        if e.is_separator:
            continue
        meta_path = staging_dir / e.name / "meta.ini"
        if not meta_path.is_file():
            continue
        try:
            meta = read_meta(meta_path)
        except Exception:
            continue

        if meta.version:
            versions[e.name] = meta.version

        if meta.installed:
            try:
                installed[e.name] = datetime.fromisoformat(
                    meta.installed).strftime("%Y-%m-%d")
            except Exception:
                installed[e.name] = meta.installed[:10]

        if meta.category_name:
            categories[e.name] = meta.category_name

        if getattr(meta, "is_fomod", False):
            fomod.add(e.name)
        if getattr(meta, "is_bain", False):
            bain.add(e.name)

        bits = 0
        if meta.has_update and meta.latest_version != meta.ignored_version:
            bits |= FLAG_UPDATE
            updates.add(e.name)
        if meta.endorsed:
            bits |= FLAG_ENDORSED
        if meta.root_folder:
            bits |= FLAG_ROOT
        if bits:
            flags[e.name] = bits

    return versions, installed, flags, categories, updates, fomod, bain


# Qt display conflict codes (drawn by the delegate). Mirrors the Tk app's
# icon mapping: WINS→winner, LOSES→loser, PARTIAL→mixed, FULL→redundant.
DISP_NONE = 0
DISP_WINS = 1
DISP_LOSES = -1
DISP_PARTIAL = 2
DISP_FULL = 3


def display_codes_from_conflict_map(conflict_map: dict):
    """Map the backend's full conflict_map (CONFLICT_* from Utils.filemap:
    NONE=0 WINS=1 LOSES=2 PARTIAL=3 FULL=4) to the Qt delegate's display codes.
    This preserves FULL (fully-overridden / redundant) which the old
    override-set re-derivation lost."""
    from Utils.filemap import (
        CONFLICT_WINS, CONFLICT_LOSES, CONFLICT_PARTIAL, CONFLICT_FULL,
    )
    out: dict[str, int] = {}
    for name, code in (conflict_map or {}).items():
        if code == CONFLICT_WINS:
            out[name] = DISP_WINS
        elif code == CONFLICT_LOSES:
            out[name] = DISP_LOSES
        elif code == CONFLICT_PARTIAL:
            out[name] = DISP_PARTIAL
        elif code == CONFLICT_FULL:
            out[name] = DISP_FULL
    return out


def conflicts_from_filemap(overrides: dict, overridden_by: dict):
    """[legacy] Re-derive per-mod codes from override sets (no FULL). Kept for
    BSA conflicts which only expose override maps; prefer
    display_codes_from_conflict_map for loose conflicts."""
    codes: dict[str, int] = {}
    wins = {m for m, v in (overrides or {}).items() if v}
    loses = {m for m, v in (overridden_by or {}).items() if v}
    for m in wins | loses:
        if m in wins and m in loses:
            codes[m] = 2
        elif m in wins:
            codes[m] = 1
        else:
            codes[m] = -1
    return codes
