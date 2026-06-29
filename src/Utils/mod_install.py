"""Toolkit-neutral mod installation core (no Tk / no Qt).

A self-contained install pipeline the Qt UI calls: extract an archive, auto-strip
to a sensible mod root, copy into the game's staging folder, then update the mod
index (+ BSA index), modlist.txt and plugins.txt. FOMOD archives are installed
with their DEFAULT (recommended) selections — the interactive wizard is NOT run
here (deferred to a later Qt port); a plain non-FOMOD layout installs verbatim.

The heavy Tk-coupled `gui/install_mod.py` is the full-featured path (FOMOD/BAIN
wizards, replace dialogs, Nexus lookup). This module reuses the same neutral
`Utils.*` backend so behaviour matches for the common case.

Public API:
    install_archive(archive_path, game, profile_dir, *, log_fn, progress_fn,
                    preferred_name="") -> str | None   # installed mod name
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Callable, Optional

LogFn = Callable[[str], None]
ProgressFn = Callable[[int, int, Optional[str]], None]


# ---- case-insensitive copy core (moved from gui/install_mod.py, shared) ------
# These resolve FOMOD/archive paths case-insensitively against the real (case-
# sensitive Linux) filesystem and dedup by destination — the accumulated fixes
# for "wrong files installed" / duplicate-cased folders. gui/install_mod.py
# imports them back so there is ONE implementation.
def _resolve_src_case(src_root: Path, src_rel: str,
                      _cache: "dict[Path, dict[str, str]] | None" = None) -> Path:
    """src_root / src_rel with each component resolved case-insensitively against
    what exists on disk (FOMOD XML is Windows-cased)."""
    if _cache is None:
        _cache = {}
    current = src_root
    for part in src_rel.replace("\\", "/").strip("/").split("/"):
        if not part:
            continue
        if current not in _cache:
            try:
                _cache[current] = {p.name.lower(): p.name
                                   for p in current.iterdir() if current.is_dir()}
            except OSError:
                _cache[current] = {}
        current = current / _cache[current].get(part.lower(), part)
    return current


def _resolve_dst_case(dest_root: Path, dst_rel: str,
                      _cache: "dict[Path, dict[str, str]] | None" = None) -> Path:
    """dest_root / dst_rel with each component resolved case-insensitively so a
    FOMOD install doesn't create duplicate folders differing only in case."""
    if _cache is None:
        _cache = {}
    current = dest_root
    for part in dst_rel.replace("\\", "/").split("/"):
        if not part:
            continue
        if current not in _cache:
            try:
                _cache[current] = {p.name.lower(): p.name
                                   for p in current.iterdir() if current.is_dir()}
            except OSError:
                _cache[current] = {}
        current = current / _cache[current].get(part.lower(), part)
    return current


def _link_or_copy(src, dst) -> None:
    """Hardlink src→dst when same-fs (near-instant, zero extra disk), else copy."""
    try:
        os.link(src, dst)
        return
    except OSError:
        try:
            shutil.copy2(src, dst)
        except FileNotFoundError:
            shutil.copy2(src, dst)


def _copytree_case_insensitive(src: Path, dst: Path) -> int:
    """Recursive copy resolving each dst component case-insensitively against
    disk (a case-aware shutil.copytree(dirs_exist_ok=True)). Returns file count."""
    copied = 0
    dst.mkdir(parents=True, exist_ok=True)
    for entry in os.scandir(src):
        try:
            existing = {p.name.lower(): p.name for p in dst.iterdir()}
        except OSError:
            existing = {}
        child_dst = dst / existing.get(entry.name.lower(), entry.name)
        if entry.is_dir(follow_symlinks=False):
            copied += _copytree_case_insensitive(Path(entry.path), child_dst)
        elif entry.is_file(follow_symlinks=False):
            child_dst.parent.mkdir(parents=True, exist_ok=True)
            if child_dst.is_dir():
                shutil.rmtree(child_dst)
            elif child_dst.exists():
                child_dst.chmod(0o644)
                child_dst.unlink()
            _link_or_copy(entry.path, child_dst)
            copied += 1
    return copied


def _copy_file_list(file_list, src_root: str, dest_root: Path, log_fn) -> None:
    """Copy each (src_rel, dst_rel, is_folder) from src_root → dest_root with
    case-insensitive resolution + destination dedup (later wins = FOMOD priority).
    Folders via the recursive copytree; files in parallel."""
    from concurrent.futures import ThreadPoolExecutor

    folder_copied = 0
    file_entries: list = []
    _src_cache: dict = {}
    _dst_cache: dict = {}
    src_root_path = Path(src_root)

    for src_rel, dst_rel, is_folder in file_list:
        if src_rel and src_rel == dst_rel:
            src = src_root_path / src_rel.replace("\\", "/")
        elif src_rel:
            src = _resolve_src_case(src_root_path, src_rel, _src_cache)
        else:
            src = src_root_path
        dst = (_resolve_dst_case(dest_root, dst_rel, _dst_cache)
               if dst_rel else dest_root / dst_rel)
        if is_folder:
            if not dst_rel:
                dst = dest_root
            if src.is_dir():
                folder_copied += _copytree_case_insensitive(src, dst)
                _dst_cache.pop(dst.parent, None)
        else:
            if not dst_rel:
                dst = dest_root / src.name
            elif dst_rel.endswith("/") or dst_rel.endswith("\\"):
                dst = _resolve_dst_case(dest_root, dst_rel.rstrip("/\\"), _dst_cache) / src.name
            if src.is_file():
                file_entries.append((src, dst))

    if file_entries:
        by_dst: dict = {}
        for src, dst in file_entries:
            by_dst[str(dst).lower()] = (src, dst)
        file_entries = list(by_dst.values())

    dirs_seen: set = set()
    for _, dst in file_entries:
        d = dst.parent
        if d not in dirs_seen:
            d.mkdir(parents=True, exist_ok=True)
            dirs_seen.add(d)

    def _copy_one(src_dst):
        src, dst = src_dst
        if dst.is_dir():
            shutil.rmtree(dst)
        elif dst.exists() or dst.is_symlink():
            try:
                dst.unlink()
            except PermissionError:
                dst.chmod(0o644)
                dst.unlink()
        _link_or_copy(src, dst)

    with ThreadPoolExecutor(max_workers=8) as pool:
        for _ in pool.map(_copy_one, file_entries, chunksize=256):
            pass
    copied = folder_copied + len(file_entries)
    log_fn(f"Copied {copied} item(s) to staging area.")


# ---------------------------------------------------------------- temp location
def _uncompressed_size(path: str) -> int:
    """Best-effort uncompressed size in bytes. ZIP reads central-directory sizes;
    otherwise a 15× compressed-size estimate (handles texture packs)."""
    try:
        compressed = os.path.getsize(path)
    except OSError:
        compressed = 0
    if path.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(path, "r") as zf:
                total = sum(m.file_size for m in zf.infolist())
            if total > 0:
                return total
        except Exception:
            pass
    return compressed * 15


def _is_small_fs(path: str, limit_gib: int = 8) -> bool:
    """True if *path*'s mount is small enough to be a tmpfs ramdisk (e.g. /tmp)."""
    try:
        st = os.statvfs(path)
        return st.f_blocks * st.f_frsize < limit_gib * 1024 ** 3
    except OSError:
        return False


def _free_bytes(path: str) -> int:
    try:
        st = os.statvfs(path)
        return st.f_frsize * st.f_bavail
    except OSError:
        return 0


def _choose_extract_parent(archive_path: str, staging_root: Path,
                           log_fn: LogFn) -> Path | None:
    """Pick a temp-dir PARENT that can hold the extraction. Default /tmp is often
    a small tmpfs ramdisk (Steam Deck: ~1GB) — if the archive won't fit there
    with headroom, extract NEXT TO the staging folder (real disk) instead. This
    mirrors the Tk app's reroute logic — without it large mods fail with
    'No space left on device'. Returns the parent dir, or None to use /tmp."""
    need = _uncompressed_size(archive_path)
    headroom = 512 * 1024 * 1024
    tmp = tempfile.gettempdir()
    if need + headroom < _free_bytes(tmp):
        return None   # /tmp has room
    # /tmp too small (commonly a ramdisk) → use the staging filesystem (real disk).
    disk_parent = staging_root.parent if staging_root else None
    if disk_parent is not None:
        try:
            disk_parent.mkdir(parents=True, exist_ok=True)
            if need + headroom < _free_bytes(str(disk_parent)):
                log_fn(f"Extracting to disk ({disk_parent}) — /tmp too small for "
                       f"~{need // (1024 * 1024)} MB.")
                return disk_parent
            log_fn(f"Warning: extract target {disk_parent} may also be low on "
                   "space.")
            return disk_parent
        except OSError:
            pass
    return None


# ---------------------------------------------------------------- extraction
def _extract_archive(archive_path: str, dest_dir: str, log_fn: LogFn) -> bool:
    """Extract *archive_path* into *dest_dir*. Native 7z → bsdtar → py7zr →
    Python zipfile/tarfile, mirroring gui.install_mod's fallback chain."""
    ext = Path(archive_path).suffix.lower()

    # tar.* and plain .tar → tarfile directly.
    if ext in (".tar", ".gz", ".bz2", ".xz", ".tgz") or \
            archive_path.lower().endswith((".tar.gz", ".tar.bz2", ".tar.xz")):
        try:
            with tarfile.open(archive_path, "r:*") as tf:
                tf.extractall(dest_dir)
            log_fn("Extracted with tarfile.")
            return True
        except Exception as exc:
            log_fn(f"tarfile failed ({exc}).")
            # fall through to the generic extractors

    _7z = (shutil.which("7zzs") or shutil.which("7zz")
           or shutil.which("7z") or shutil.which("7za"))
    if _7z:
        r = subprocess.run(
            [_7z, "x", archive_path, f"-o{dest_dir}", "-y", "-mmt=on"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if r.returncode == 0:
            log_fn("Extracted with 7z.")
            return True
        log_fn(f"7z failed ({r.stderr.strip()}), trying bsdtar…")
    if shutil.which("bsdtar"):
        r = subprocess.run(
            ["bsdtar", "-xf", archive_path, "-C", dest_dir],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if r.returncode == 0 and any(os.scandir(dest_dir)):
            log_fn("Extracted with bsdtar.")
            return True
        log_fn(f"bsdtar failed ({r.stderr.strip()}), trying py7zr…")
    try:
        import py7zr
        with py7zr.SevenZipFile(archive_path, "r") as z:
            z.extractall(dest_dir)
        log_fn("Extracted with py7zr.")
        return True
    except Exception as exc:
        log_fn(f"py7zr failed ({exc}), trying zipfile…")
    try:
        with zipfile.ZipFile(archive_path, "r") as z:
            z.extractall(dest_dir)
        log_fn("Extracted with zipfile.")
        return True
    except Exception as exc:
        log_fn(f"zipfile failed ({exc}).")
    return False


# ---------------------------------------------------------------- root detection
def _single_root_unwrap(extract_dir: Path) -> Path:
    """If the archive extracted into a single wrapper folder (and nothing else),
    descend into it — the common 'archive contains one top folder' case."""
    cur = extract_dir
    for _ in range(8):
        children = [c for c in cur.iterdir() if c.name not in (".", "..")]
        if len(children) == 1 and children[0].is_dir():
            cur = children[0]
        else:
            break
    return cur


def _looks_like_fomod(root: Path) -> Path | None:
    """Return the folder containing a fomod/ModuleConfig.xml if present."""
    for p in root.rglob("ModuleConfig.xml"):
        if p.parent.name.lower() == "fomod":
            return p.parent.parent
    return None


# ------------------------------------------------------------ prepare / finish
class PreparedInstall:
    """An extracted-but-not-yet-staged archive. `extract_dir` lives until
    `cleanup()` (so an interactive FOMOD wizard can read images + the config and
    then call `finish_install`). When `fomod_base`/`fomod_config` are set the
    caller should run the wizard; otherwise it's a plain install."""
    def __init__(self, archive: Path, game, profile_dir: Path, mod_name: str,
                 extract_dir: Path, src_root: Path,
                 fomod_base: Path | None, fomod_config):
        self.archive = archive
        self.game = game
        self.profile_dir = profile_dir
        self.mod_name = mod_name
        self.extract_dir = extract_dir
        self.src_root = src_root
        self.fomod_base = fomod_base
        self.fomod_config = fomod_config

    def is_fomod(self) -> bool:
        return self.fomod_base is not None and self.fomod_config is not None

    def cleanup(self):
        shutil.rmtree(self.extract_dir, ignore_errors=True)


def prepare_archive(archive_path: str, game, profile_dir: Path, *,
                    log_fn: LogFn, progress_fn: Optional[ProgressFn] = None,
                    preferred_name: str = "") -> PreparedInstall | None:
    """Extract *archive_path* to a kept temp dir and detect FOMOD. The caller
    either runs the wizard (is_fomod) then `finish_install(prepared, selections)`,
    or just calls `finish_install(prepared, None)` for a plain/default install.
    Returns None on failure (and cleans up)."""
    archive = Path(archive_path)
    if not archive.is_file():
        log_fn(f"Install: archive not found: {archive_path}")
        return None
    staging_root = game.get_effective_mod_staging_path()
    if staging_root is None:
        log_fn("Install: no staging folder configured.")
        return None
    mod_name = preferred_name or _clean_mod_name(archive.stem, game)

    def _p(done, total, phase=None):
        if progress_fn is not None:
            progress_fn(done, total, phase)

    _p(0, 0, "Extracting")
    # Pick a temp parent big enough — /tmp is a small ramdisk on the Deck, so a
    # large mod must extract to the staging disk instead (Tk parity).
    parent = _choose_extract_parent(str(archive), Path(staging_root), log_fn)
    extract_dir = Path(tempfile.mkdtemp(prefix="mm_install_",
                                        dir=str(parent) if parent else None))
    if not _extract_archive(str(archive), str(extract_dir), log_fn):
        log_fn("Install failed: could not extract the archive.")
        shutil.rmtree(extract_dir, ignore_errors=True)
        return None

    src_root = _single_root_unwrap(extract_dir)
    fomod_base = _looks_like_fomod(extract_dir)
    config = None
    if fomod_base is not None:
        try:
            from Utils.fomod_parser import parse_module_config
            config = parse_module_config(str(fomod_base / "fomod" / "ModuleConfig.xml"))
        except Exception as exc:
            log_fn(f"FOMOD parse failed ({exc}); will install verbatim.")
            fomod_base = None
    return PreparedInstall(archive, game, profile_dir, mod_name,
                           extract_dir, src_root, fomod_base, config)


def finish_install(prepared: "PreparedInstall", fomod_selections, *,
                   log_fn: LogFn, progress_fn: Optional[ProgressFn] = None
                   ) -> str | None:
    """Stage the prepared archive. *fomod_selections* is the wizard's
    {step_idx: {group: [plugins]}} dict (or None → FOMOD defaults / plain copy).
    Always cleans up the extract dir. Returns the installed mod name."""
    p = prepared
    staging_root = Path(p.game.get_effective_mod_staging_path())
    staging_root.mkdir(parents=True, exist_ok=True)
    dest_root = staging_root / p.mod_name

    def _pp(done, total, phase=None):
        if progress_fn is not None:
            progress_fn(done, total, phase)

    # Fresh install replaces an existing same-named folder cleanly, so stale
    # files (e.g. a previous FOMOD selection's variant folders) never linger.
    if dest_root.exists():
        log_fn(f"Replacing existing mod folder: {p.mod_name}")
        shutil.rmtree(dest_root, ignore_errors=True)

    try:
        if p.is_fomod():
            ok = _install_fomod(p.fomod_base, p.fomod_config, dest_root,
                                fomod_selections, log_fn, _pp)
            if not ok:
                log_fn("FOMOD resolve failed — installing all files verbatim.")
                _copy_tree(p.src_root, dest_root, log_fn, _pp)
        else:
            _copy_tree(p.src_root, dest_root, log_fn, _pp)
    finally:
        p.cleanup()

    if not dest_root.is_dir() or not any(dest_root.iterdir()):
        log_fn(f"Install failed: nothing was staged for '{p.mod_name}'.")
        try:
            dest_root.rmdir()
        except OSError:
            pass
        return None

    _write_install_meta(dest_root, p.archive, p.game, log_fn)
    _pp(0, 0, "Indexing")
    _update_indexes(p.game, p.profile_dir, p.mod_name, dest_root, log_fn)
    _add_to_modlist(p.profile_dir, p.mod_name, log_fn)
    _add_plugins(p.game, p.profile_dir, dest_root, log_fn)
    log_fn(f"Installed '{p.mod_name}'.")
    return p.mod_name


def install_archive(archive_path: str, game, profile_dir: Path, *,
                    log_fn: LogFn, progress_fn: Optional[ProgressFn] = None,
                    preferred_name: str = "") -> str | None:
    """Non-interactive install (FOMOD → default selections). Convenience wrapper
    over prepare_archive + finish_install."""
    prepared = prepare_archive(archive_path, game, profile_dir, log_fn=log_fn,
                               progress_fn=progress_fn, preferred_name=preferred_name)
    if prepared is None:
        return None
    return finish_install(prepared, None, log_fn=log_fn, progress_fn=progress_fn)


# ---------------------------------------------------------------- helpers
def _clean_mod_name(stem: str, game) -> str:
    """Best-effort folder name from the archive stem (strips Nexus -NNNNN- id /
    version tails) + sanitises reserved chars."""
    name = stem
    try:
        from gui.mod_name_utils import _strip_title_metadata, sanitize_mod_folder_name
        name = _strip_title_metadata(stem) or stem
        name = sanitize_mod_folder_name(name) or name
    except Exception:
        # mod_name_utils may pull Tk transitively — fall back to a basic clean.
        import re
        name = re.sub(r"-\d+-.*$", "", stem).strip() or stem
        name = re.sub(r'[<>:"/\\|?*]', "_", name).rstrip(". ")
    return name or stem


def _copy_tree(src_root: Path, dest_root: Path, log_fn: LogFn, _p) -> None:
    files = [p for p in src_root.rglob("*") if p.is_file()]
    total = len(files)
    dest_root.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(files, 1):
        rel = f.relative_to(src_root)
        # Skip installer-only fomod/ metadata in a plain copy.
        if rel.parts and rel.parts[0].lower() == "fomod":
            continue
        target = dest_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
        if i % 25 == 0 or i == total:
            _p(i, total, "Copying files")


def _install_fomod(fomod_base: Path, config, dest_root: Path,
                   selections, log_fn: LogFn, _p) -> bool:
    """Stage a FOMOD's files. *selections* is the wizard's
    {step_idx_str: {group_name: [plugin_names]}} dict; None → the FOMOD's own
    default selections. Uses the neutral `resolve_files` to map src→dst and
    apply requiredInstallFiles + conditional installs. Returns False on failure
    (caller falls back to verbatim copy)."""
    try:
        from Utils.fomod_installer import (
            resolve_files, get_default_selections, update_flags)
    except Exception as exc:
        log_fn(f"FOMOD installer unavailable ({exc}).")
        return False

    if not selections:
        # Build default selections per step, threading flag state through.
        selections = {}
        flag_state: dict = {}
        for i, step in enumerate(getattr(config, "steps", []) or []):
            sels = get_default_selections(step, flag_state, set())
            selections[str(i)] = sels
            flag_state = update_flags(step, sels, flag_state)
        log_fn("FOMOD: using default/recommended options.")

    try:
        files = resolve_files(config, selections)   # [(src_rel, dst_rel, is_folder)]
    except Exception as exc:
        log_fn(f"FOMOD resolve_files failed ({exc}).")
        return False
    if not files:
        return False

    _p(0, 0, "Installing FOMOD files")
    # Use the SHARED, proven copier (case-insensitive resolution + dst dedup +
    # priority "later wins"). fomod_base is the src root; resolve_files already
    # produced the src→dst mapping.
    _copy_file_list(files, str(fomod_base), dest_root, log_fn)
    return any(dest_root.iterdir())


def _write_install_meta(dest_root: Path, archive: Path, game, log_fn: LogFn) -> None:
    try:
        from Nexus.nexus_meta import (
            write_meta, resolve_nexus_meta_for_archive, NexusModMeta)
        from datetime import datetime
        meta_path = dest_root / "meta.ini"
        meta = None
        domain = getattr(game, "nexus_game_domain", None) or getattr(game, "game_id", "")
        try:
            meta = resolve_nexus_meta_for_archive(archive, domain, log_fn=log_fn)
        except Exception:
            meta = None
        if meta is None:
            meta = NexusModMeta()
        # Always stamp the local install fields.
        meta.installation_file = archive.name
        if not getattr(meta, "installed", ""):
            meta.installed = datetime.now().isoformat(timespec="seconds")
        write_meta(meta_path, meta)
    except Exception as exc:
        log_fn(f"meta.ini write skipped ({exc}).")


def _update_indexes(game, profile_dir: Path, mod_name: str, dest_root: Path,
                    log_fn: LogFn) -> None:
    try:
        from Utils.filemap import _scan_dir, update_mod_index
        strip = frozenset(s.lower() for s in (getattr(game, "strip_prefixes", None) or []))
        exts = frozenset(e.lower() for e in (getattr(game, "install_extensions", None) or []))
        root = frozenset(s.lower() for s in (getattr(game, "root_deploy_folders", None) or []))
        # _scan_dir returns (name, normal, root, extras); take the first three.
        scan = _scan_dir(mod_name, str(dest_root), strip, exts, root)
        normal_files, root_files = scan[1], scan[2]
        # The index MUST live where build_filemap reads it — next to the
        # effective filemap (= staging.parent / game root), NOT the profile dir.
        # Writing it to the profile dir leaves a fresh install invisible to the
        # filemap rebuild → no conflicts detected (the bug this fixes).
        try:
            index_dir = game.get_effective_filemap_path().parent
        except Exception:
            index_dir = profile_dir
        index_path = index_dir / "modindex.bin"
        norm_case = getattr(game, "normalize_folder_case", True)
        update_mod_index(index_path, mod_name, normal_files, root_files,
                         normalize_folder_case=norm_case)
        archive_exts = frozenset(getattr(game, "archive_extensions", frozenset()) or frozenset())
        if archive_exts:
            from Utils.bsa_filemap import update_bsa_index
            update_bsa_index(index_dir / "bsa_index.bin", mod_name, dest_root, archive_exts)
    except Exception as exc:
        log_fn(f"index update skipped ({exc}) — next rebuild will rescan.")


def _add_to_modlist(profile_dir: Path, mod_name: str, log_fn: LogFn) -> None:
    try:
        from Utils.modlist import prepend_mod
        prepend_mod(profile_dir / "modlist.txt", mod_name, enabled=True)
    except Exception as exc:
        log_fn(f"modlist update failed ({exc}).")


def _add_plugins(game, profile_dir: Path, dest_root: Path, log_fn: LogFn) -> None:
    exts = [e.lower() for e in (getattr(game, "plugin_extensions", []) or [])]
    if not exts:
        return
    try:
        from Utils.plugins import append_plugin
        star = getattr(game, "plugins_use_star_prefix", True)
        plugins_path = profile_dir / "plugins.txt"
        for entry in sorted(dest_root.iterdir()):
            if entry.is_file() and entry.suffix.lower() in exts:
                append_plugin(plugins_path, entry.name, enabled=True, star_prefix=star)
    except Exception as exc:
        log_fn(f"plugins update skipped ({exc}).")
