"""Shared helpers for wizards that can install their payload as a managed mod
(staging folder + modlist entry + rootFolder=true flag).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from Games.base_game import BaseGame


def derive_mod_name(archive: Path, fallback: str) -> str:
    """Derive a mod folder name from the archive filename, stripping the
    extension (including double extensions like ``.tar.gz``).  Falls back to
    *fallback* when the resulting stem is empty.
    """
    stem = archive.name
    for ext in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if stem.lower().endswith(ext):
            stem = stem[: -len(ext)]
            break
    else:
        stem = Path(stem).stem
    return stem.strip() or fallback


def register_as_mod(
    game: "BaseGame",
    mod_name: str,
    archive: "Path | None" = None,
    *,
    parent_widget,
    log_fn: Callable[[str], None],
    root_folder: bool = True,
) -> Path:
    """Write meta.ini with rootFolder=*root_folder*, prepend the mod to
    modlist.txt, and trigger a refresh of the modlist panel if reachable from
    *parent_widget*.

    *archive* is optional — pass ``None`` for payloads built directly in the
    staging folder (no source archive), in which case ``installation_file`` is
    left blank.

    Returns the staging mod directory so callers can drop files into it.
    Must be called from the worker thread; UI refresh is scheduled via .after().
    """
    from Nexus.nexus_meta import NexusModMeta, write_meta
    from Utils.modlist import prepend_mod

    staging = game.get_effective_mod_staging_path()
    if staging is None:
        raise RuntimeError("Mod staging path is not configured.")

    mod_dir = staging / mod_name
    mod_dir.mkdir(parents=True, exist_ok=True)

    meta = NexusModMeta(
        mod_name=mod_name,
        installation_file=archive.name if archive is not None else "",
        root_folder=root_folder,
    )
    write_meta(mod_dir / "meta.ini", meta)

    mod_panel = None
    try:
        toplevel = parent_widget.winfo_toplevel()
        mod_panel = getattr(toplevel, "_mod_panel", None)
    except Exception:
        mod_panel = None

    modlist_path: Path | None = None
    if mod_panel is not None:
        modlist_path = getattr(mod_panel, "_modlist_path", None)
    if modlist_path is None:
        modlist_path = game.get_profile_root() / "profiles" / "default" / "modlist.txt"

    prepend_mod(modlist_path, mod_name, enabled=True)
    log_fn(f"Wizard: added '{mod_name}' to modlist with rootFolder={str(root_folder).lower()}.")

    if mod_panel is not None:
        try:
            mod_panel.after(0, mod_panel.reload_after_install)
        except Exception as exc:
            log_fn(f"Wizard: could not trigger mod panel refresh: {exc}")

    return mod_dir
