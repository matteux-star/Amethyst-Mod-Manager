"""
dao_install.py
Install-time normalization for Dragon Age: Origins mods.

DAO mods ship in wildly inconsistent shapes: some carry their own
``override/`` folder, some are loose files, some bury content several folders
deep, and archives often include macOS cruft and documentation. The game,
however, only reads loose override content from
``packages/core/override/`` and DLC-style content from ``AddIns``/``Offers``.

`normalize_dao_mod` runs as an `additional_install_logic` callable
(``fn(dest_root, mod_name, log_fn)``) immediately after a mod's files are
staged. It rewrites the staged tree into DAO's layout so the filemap records
correct ``packages/core/override/...`` destinations.

Scope:
  - ``.dazip`` archives are extracted: ``Contents/*`` is merged into the
    staging root (so ``Contents/addins/<uid>`` → ``addins/<uid>`` etc.) and the
    ``Manifest.xml`` is filed under ``addins/<uid>/`` or ``offers/<uid>/`` by
    its declared Type/UID for the AddIns.xml/Offers.xml registry built at deploy.
  - ``.override`` archives (DAO-Modmanager format) are extracted with optional
    ``OverrideConfig.xml`` option handling.
  - Junk (``__MACOSX``, ``.DS_Store``, ``.bak``, top-level docs/images) is removed.
  - Files under an internal ``override/`` segment are re-rooted under
    ``packages/core/override/`` (path below ``override/`` preserved).
  - All other content is moved under ``packages/core/override/``, preserving
    the structure below the mod's top-level folder.
"""

from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

_OVERRIDE_DEST = Path("packages/core/override")

# DAO package archive formats extracted at install time.
_DAZIP_EXTS = {".dazip"}
_OVERRIDE_PKG_EXTS = {".override"}
_ARCHIVE_EXTS = _DAZIP_EXTS | _OVERRIDE_PKG_EXTS

# Files that are never game content.
_JUNK_DIR_NAMES = {"__macosx"}
_JUNK_FILE_NAMES = {".ds_store"}
_JUNK_SUFFIXES = {".bak"}

# Documentation / preview clutter that DAO never loads. Only stripped when it
# sits at (or near) the mod root — a ``.txt`` deep inside override content may
# be a legitimate config the author references, so we keep those.
_DOC_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".rtf", ".doc", ".docx", ".url"}

# Files that must stay at the mod root (not pushed into override/).
_KEEP_AT_ROOT = {"meta.ini"}

# Top-level segments that are already canonical DAO layout (from extracted
# .dazip Contents or hand-structured mods). These are left exactly where they
# are — only loose/unstructured content gets pushed into packages/core/override.
_CANONICAL_TOP = {"addins", "offers", "packages", "modules", "characters",
                  "settings", "bin_ship"}


def _is_junk(rel_parts: list[str]) -> bool:
    """True if a staged file path is cruft that should be deleted."""
    lower = [p.lower() for p in rel_parts]
    if any(seg in _JUNK_DIR_NAMES for seg in lower[:-1]):
        return True
    name = lower[-1]
    if name in _JUNK_FILE_NAMES:
        return True
    if any(name.endswith(suf) for suf in _JUNK_SUFFIXES):
        return True
    return False


def _is_top_level_doc(rel_parts: list[str]) -> bool:
    """True for documentation/preview files at the mod root (depth 1)."""
    if len(rel_parts) != 1:
        return False
    suffix = Path(rel_parts[-1]).suffix.lower()
    return suffix in _DOC_SUFFIXES


def _override_dest_rel(rel_parts: list[str]) -> Path:
    """Map a mod-relative path to its packages/core/override destination.

    Override is a FLAT namespace in DAO: the resource manager resolves loose
    files (.mmh/.msh/.mao/.dds/.gda/...) by basename within
    packages/core/override and does NOT reliably recurse into arbitrary
    mod-named subfolders. Mods ship deeply nested layouts (e.g.
    ``Anto Hairstyles/Coolsims033 Hair/hm/hm_har_coolsims033_0.mmh``) that the
    user is expected to flatten on install — otherwise the resource is
    registered in chargenmorphcfg.xml but the mesh can't be found (invisible
    hairstyle). So we flatten every override file to its bare basename.

    Cross-mod collisions (same basename in two mods) are resolved by the
    filemap's normal priority order (higher-priority mod wins).
    """
    return _OVERRIDE_DEST / rel_parts[-1]


def _merge_tree(src_dir: Path, dst_dir: Path) -> None:
    """Move every file from src_dir into dst_dir, preserving sub-paths and
    overwriting on collision. src_dir is removed afterward."""
    for dirpath, _dirnames, filenames in os.walk(src_dir):
        for fn in filenames:
            s = Path(dirpath) / fn
            rel = s.relative_to(src_dir)
            d = dst_dir / rel
            d.parent.mkdir(parents=True, exist_ok=True)
            if d.exists():
                d.unlink()
            shutil.move(str(s), str(d))
    shutil.rmtree(src_dir, ignore_errors=True)


def _file_manifest(temp_dir: Path, dest_root: Path, log_fn) -> None:
    """File a .dazip Manifest.xml under addins/<uid>/ or offers/<uid>/.

    The Manifest declares Type (AddIn/Offer) and a UID via the first
    AddInItem/OfferItem. Deploy later scans these to build AddIns.xml/Offers.xml.
    """
    src = temp_dir / "Manifest.xml"
    if not src.is_file():
        return
    try:
        root = ET.parse(src).getroot()
    except ET.ParseError as exc:
        log_fn(f"  [DAO] could not parse Manifest.xml: {exc}")
        return
    mtype = (root.get("Type") or "").casefold()
    if mtype == "addin":
        sub, item_path = "addins", "AddInsList/AddInItem"
    elif mtype == "offer":
        sub, item_path = "offers", "OfferList/OfferItem"
    else:
        log_fn(f"  [DAO] Manifest.xml has no valid Type ({mtype!r}); skipping.")
        return
    item = root.find(item_path)
    uid = item.get("UID") if item is not None else None
    if not uid:
        log_fn("  [DAO] Manifest.xml has no UID; skipping.")
        return
    dst = dest_root / sub / uid / "Manifest.xml"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    shutil.move(str(src), str(dst))


def _extract_archives(dest_root: Path, log_fn) -> int:
    """Extract any .dazip/.override archives staged at dest_root.

    Returns the number of archives extracted. For .dazip: Contents/* merges
    into the staging root and Manifest.xml is filed by UID. For .override:
    the BioWare/Dragon Age/ tree merges into the staging root.
    """
    archives = [
        Path(dp) / fn
        for dp, _dn, fns in os.walk(dest_root)
        for fn in fns
        if Path(fn).suffix.lower() in _ARCHIVE_EXTS
    ]
    if not archives:
        return 0
    count = 0
    for arc in archives:
        suffix = arc.suffix.lower()
        temp = arc.parent / (arc.stem + "_mo2unpack")
        try:
            if temp.exists():
                shutil.rmtree(temp, ignore_errors=True)
            temp.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(arc) as zf:
                zf.extractall(temp)
        except (zipfile.BadZipFile, OSError) as exc:
            log_fn(f"  [DAO] failed to extract {arc.name}: {exc}")
            shutil.rmtree(temp, ignore_errors=True)
            continue

        if suffix in _DAZIP_EXTS:
            contents = temp / "Contents"
            if contents.is_dir():
                _merge_tree(contents, dest_root)
            else:
                log_fn(f"  [DAO] {arc.name}: no Contents/ — merging extracted "
                       "tree as-is.")
                _merge_tree(temp, dest_root)
                temp.mkdir(parents=True, exist_ok=True)  # re-stub for cleanup
            _file_manifest(temp, dest_root, log_fn)
        else:  # .override (DAO-Modmanager): BioWare/Dragon Age/ tree
            bioware = temp / "BioWare" / "Dragon Age"
            if bioware.is_dir():
                _merge_tree(bioware, dest_root)
            else:
                _merge_tree(temp, dest_root)
                temp.mkdir(parents=True, exist_ok=True)

        shutil.rmtree(temp, ignore_errors=True)
        try:
            arc.unlink()
        except OSError:
            pass
        count += 1
        log_fn(f"  [DAO] extracted {arc.name} ({suffix}).")
    return count


def _maybe_apply_override_config(dest_root: Path, log_fn) -> bool:
    """Apply OverrideConfig.xml choices for a DAO-Modmanager .override mod.

    Searches the whole staged tree for an OverrideConfig.xml. This runs as its
    own normalize step (not only during .override extraction) because the mod
    may have been unpacked by the generic installer before normalize sees it —
    by then there is no .override archive left, only the unpacked tree.

    OverrideConfig.xml (DAO-Modmanager format) offers selectable variants: each
    key has an OriginalFile and alternate Value options pointing at OptionsFile
    replacements. We prompt the user via the shared GUI question hook when one
    is present; absent a hook (headless/collection), defaults are kept.

    Returns True if a config was found and handled (so callers can log it).
    """
    config = None
    for dirpath, _dn, fns in os.walk(dest_root):
        for fn in fns:
            if fn.casefold() == "overrideconfig.xml":
                config = Path(dirpath) / fn
                break
        if config:
            break
    if config is None:
        return False
    try:
        choices = _prompt_override_config(config, log_fn)
    except Exception as exc:  # never let a wizard error abort the install
        log_fn(f"  [DAO] OverrideConfig handling failed: {exc}")
        choices = []
    # Resolve OriginalFile/OptionsFile by basename anywhere in the staged tree
    # (files may already be flattened into packages/core/override).
    for original, replacement in choices:
        src = _find_in_tree(dest_root, replacement)
        dst = _find_in_tree(dest_root, original)
        if src and dst:
            try:
                shutil.copy2(src, dst)
            except OSError as exc:
                log_fn(f"  [DAO] OverrideConfig copy failed "
                       f"{replacement}→{original}: {exc}")
    # OverrideConfig.xml is an installer artifact — the game never reads it.
    # Remove it (always, even when no choices were applied) so it does not
    # deploy into the override folder.
    try:
        config.unlink()
    except OSError as exc:
        log_fn(f"  [DAO] could not remove OverrideConfig.xml: {exc}")
    return True


def _find_in_tree(root: Path, filename: str) -> "Path | None":
    if not root.is_dir() or not filename:
        return None
    target = filename.casefold()
    for dirpath, _dn, fns in os.walk(root):
        for fn in fns:
            if fn.casefold() == target:
                return Path(dirpath) / fn
    return None


def _prompt_override_config(config_path: Path, log_fn) -> list[tuple[str, str]]:
    """Parse OverrideConfig.xml and ask the user to choose option variants.

    Returns a list of (original_file, chosen_replacement_file) pairs to apply.
    Uses the shared install question hook if available; otherwise returns []
    (keep defaults) so headless/collection installs never block.
    """
    try:
        root = ET.parse(config_path).getroot()
    except ET.ParseError as exc:
        log_fn(f"  [DAO] could not parse OverrideConfig.xml: {exc}")
        return []

    options: list[dict] = []
    for section in root:
        section_name = section.get("Name", "")
        for key in section:
            key_name = key.get("Name", "")
            default = key.get("DefaultValue", "")
            original = key.get("OriginalFile", "")
            values: list[tuple[str, str]] = []  # (value_name, options_file)
            description = ""
            for val in key:
                if val.tag == "Description":
                    description = (val.text or "").strip()
                else:
                    values.append((val.get("Value", ""), val.get("OptionsFile", "")))
            if original and values:
                options.append({
                    "section": section_name, "key": key_name,
                    "default": default, "original": original,
                    "values": values, "description": description,
                })
    if not options:
        return []

    ask = _get_question_hook(log_fn)
    if ask is None:
        log_fn(f"  [DAO] OverrideConfig.xml present but no UI hook — "
               f"keeping {len(options)} default(s).")
        return []

    results: list[tuple[str, str]] = []
    for opt in options:
        labels = [v[0] for v in opt["values"]]
        default_idx = next(
            (i for i, v in enumerate(opt["values"]) if v[0] == opt["default"]), 0
        )
        chosen = ask(
            title="Dragon Age — Mod Options",
            prompt=(f"{opt['section']} — {opt['key']}\n\n"
                    f"{opt['description']}\n\n"
                    f"(default: {opt['default']})"),
            options=labels,
            default_index=default_idx,
            log_fn=log_fn,
        )
        if chosen is None:
            continue
        repl = next((f for name, f in opt["values"] if name == chosen), "")
        if repl:
            results.append((opt["original"], repl))
    return results


def _get_question_hook(log_fn=None):
    """Return a callable(title, prompt, options, default_index) -> chosen|None.

    Resolved lazily from the GUI layer so this module stays import-light and
    usable headless. Returns None when no GUI hook is available — logging the
    reason so a missing wizard isn't silent.
    """
    try:
        from gui.install_question import ask_choice  # type: ignore
        return ask_choice
    except Exception as exc:
        if log_fn:
            log_fn(f"  [DAO] OverrideConfig wizard unavailable "
                   f"(gui.install_question import failed: {exc!r}).")
        return None


def normalize_dao_mod(dest_root: Path, mod_name: str, log_fn=None) -> None:
    """Restructure a freshly-staged DAO mod into the game's layout."""
    _log = log_fn or (lambda _: None)
    dest_root = Path(dest_root)
    if not dest_root.is_dir():
        return

    # Step 0: extract any .dazip/.override archives first, so their unpacked
    # content flows through the override/AddIns normalization below.
    extracted = _extract_archives(dest_root, _log)

    # Step 0.5: handle an OverrideConfig.xml (DAO-Modmanager option wizard).
    # Runs whether the .override was unpacked by us above or by the generic
    # installer before normalize was invoked. Applies the user's variant choice
    # and removes the config so it does not deploy.
    if _maybe_apply_override_config(dest_root, _log):
        _log(f"  [DAO] {mod_name}: applied OverrideConfig.xml options.")

    # Collect the current file set first; we mutate the tree as we go.
    files: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(dest_root):
        for fn in filenames:
            files.append(Path(dirpath) / fn)

    removed = moved = kept = 0
    planned: list[tuple[Path, Path]] = []  # (src_abs, dst_rel)

    for src in files:
        rel = src.relative_to(dest_root)
        rel_parts = list(rel.parts)

        if rel_parts[-1].lower() in _KEEP_AT_ROOT:
            kept += 1
            continue
        if _is_junk(rel_parts):
            try:
                src.unlink()
                removed += 1
            except OSError as exc:
                _log(f"  [DAO] could not remove junk {rel}: {exc}")
            continue
        if _is_top_level_doc(rel_parts):
            try:
                src.unlink()
                removed += 1
            except OSError as exc:
                _log(f"  [DAO] could not remove doc {rel}: {exc}")
            continue
        lower_parts = [p.lower() for p in rel_parts]

        # Override content (anywhere an "override" segment appears, however
        # deeply nested) must be FLATTENED to packages/core/override/<basename>
        # — DAO does not recurse into mod-named subfolders for these resources.
        if "override" in lower_parts:
            dst_rel = _OVERRIDE_DEST / rel_parts[-1]
            if dst_rel != rel:
                planned.append((src, dst_rel))
            else:
                kept += 1
            continue

        # Other canonical DAO layout (addins/, offers/, packages/core/data,
        # modules/, characters/, ...) is left exactly as-is.
        if rel_parts[0].lower() in _CANONICAL_TOP:
            kept += 1
            continue

        # Loose / unstructured content → flatten into override.
        dst_rel = _override_dest_rel(rel_parts)
        if dst_rel != rel:
            planned.append((src, dst_rel))

    for src, dst_rel in planned:
        dst = dest_root / dst_rel
        if src == dst:
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            # Overwrite on collision: later-listed wins (rare; mods shouldn't
            # ship the same override file twice, but be deterministic).
            if dst.exists():
                dst.unlink()
            shutil.move(str(src), str(dst))
            moved += 1
        except OSError as exc:
            _log(f"  [DAO] failed to move {src.relative_to(dest_root)} "
                 f"→ {dst_rel}: {exc}")

    # Remove directories left empty by the moves (but keep the override tree).
    for dirpath, _dirnames, _filenames in os.walk(dest_root, topdown=False):
        p = Path(dirpath)
        if p == dest_root:
            continue
        try:
            if not any(p.iterdir()):
                p.rmdir()
        except OSError:
            pass

    _log(f"  [DAO] {mod_name}: normalized → override "
         f"(extracted {extracted} archive(s), moved {moved}, "
         f"removed {removed}, kept {kept}).")
