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


def index_installed_mod(
    game: "BaseGame",
    mod_name: str,
    *,
    log_fn: Callable[[str], None],
) -> None:
    """Scan *mod_name*'s staging folder and add it to ``modindex.bin``.

    ``build_filemap`` reads the index (fast path) instead of rescanning disk, so
    a mod whose files were just dropped into staging won't deploy until the
    index knows about them.  The normal Install Mod flow does this with
    ``_scan_dir`` + ``update_mod_index``; wizards that build their payload via
    ``register_as_mod`` must call this *after* the files are in place (e.g. after
    extraction) or the next deploy emits nothing for the mod.

    Mirrors ``gui/install_mod.py``'s indexing block.  No-op-safe: failures are
    logged, and a later Refresh (full ``rebuild_mod_index``) still recovers.
    """
    from Utils.filemap import _scan_dir, update_mod_index

    try:
        staging = game.get_effective_mod_staging_path()
        if staging is None:
            return
        mod_dir = staging / mod_name
        if not mod_dir.is_dir():
            return
        strip_fs = frozenset(
            s.lower() for s in (getattr(game, "mod_folder_strip_prefixes", set()) or [])
        )
        exts_fs = frozenset(
            e.lower() for e in (getattr(game, "install_extensions", None) or [])
        )
        root_fs = frozenset(
            s.lower() for s in (getattr(game, "root_deploy_folders", None) or [])
        )
        _, normal_files, root_files, _ = _scan_dir(
            mod_name, str(mod_dir), strip_fs, exts_fs, root_fs
        )
        index_path = staging.parent / "modindex.bin"
        norm_case = getattr(game, "normalize_folder_case", True)
        update_mod_index(
            index_path, mod_name, normal_files, root_files,
            normalize_folder_case=norm_case,
        )
        log_fn(f"Wizard: indexed '{mod_name}' ({len(normal_files)} file(s)) for deploy.")
    except Exception as exc:
        log_fn(f"Wizard: could not index '{mod_name}': {exc}")
