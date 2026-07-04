"""Cyber Engine Tweaks symlink-mode detection (GUI-agnostic).

CET's ASI loader refuses to load a symlinked ``cyber_engine_tweaks.asi``, so the
mod silently fails when Cyberpunk 2077 is deployed in SYMLINK mode. This module
holds the pure detection — scan the effective filemap for the asi and report
whether a warning is warranted. The GUI layer owns the actual prompt.

Ported from the Tk ``gui.dialogs.confirm_cet_symlink`` (its detection half).
"""

from __future__ import annotations

from pathlib import Path


CET_ASI = "cyber_engine_tweaks.asi"


def cet_symlink_conflict(game) -> bool:
    """Return True when *game* is Cyberpunk 2077, its deploy mode is SYMLINK,
    and the effective filemap stages ``cyber_engine_tweaks.asi`` — i.e. the
    situation where CET would silently fail to load. Any missing attribute,
    non-Cyberpunk game, non-symlink mode, or unreadable filemap returns False
    (nothing to warn about)."""
    if getattr(game, "name", "") != "Cyberpunk 2077":
        return False
    try:
        from Utils.deploy import LinkMode
        if not hasattr(game, "get_deploy_mode"):
            return False
        if game.get_deploy_mode() != LinkMode.SYMLINK:
            return False
    except Exception:
        return False
    try:
        filemap_path = game.get_effective_filemap_path()
    except Exception:
        return False
    if not filemap_path or not Path(filemap_path).is_file():
        return False
    try:
        with Path(filemap_path).open(encoding="utf-8") as f:
            for line in f:
                if "\t" not in line:
                    continue
                rel_str, _ = line.rstrip("\n").split("\t", 1)
                if rel_str.lower().endswith(CET_ASI):
                    return True
    except Exception:
        return False
    return False
