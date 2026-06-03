"""
dao_xml.py
Deploy-time generation of Dragon Age: Origins registry XML.

DAO discovers installed DLC-style content (AddIns and Offers) through two
registry files the game reads at launch:

    Settings/AddIns.xml   — <AddInsList> of every installed AddIn
    Settings/Offers.xml   — <OfferList>  of every installed Offer

Each .dazip ships a Manifest.xml whose AddInItem/OfferItem must be merged into
these lists, or the content is installed on disk but invisible in-game. We
rebuild both files at deploy time by scanning the deployed addins/<uid>/ and
offers/<uid>/ Manifests, so the registry always matches the enabled mod set.

``RequiresAuthorization="1"`` is rewritten to ``"0"`` so the game does not gate
the content behind an online/DLC-key check.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

# (subdir, manifest item tag, list root tag, output filename)
_REGISTRIES = (
    ("AddIns", "AddInItem", "AddInsList", "AddIns.xml"),
    ("Offers", "OfferItem", "OfferList", "Offers.xml"),
)


def _iter_manifests(search_root: Path, subdir: str):
    """Yield every Manifest.xml that sits under an ``<subdir>/`` path segment.

    Walks recursively so it works both for the flat deployed layout
    (``<data_root>/addins/<uid>/Manifest.xml``) and the nested staging layout
    (``<staging>/<mod>/addins/<uid>/Manifest.xml``). Matching is by the
    presence of the subdir name (case-insensitive) in the path.
    """
    import os
    want = subdir.casefold()
    if not search_root.is_dir():
        return
    for dirpath, _dn, fns in os.walk(search_root):
        for fn in fns:
            if fn.casefold() != "manifest.xml":
                continue
            parts = [p.casefold() for p in Path(dirpath).parts]
            if want in parts:
                yield Path(dirpath) / fn


def build_registry_xml(data_root: Path, mod_staging: "Path | None" = None,
                       log_fn=None) -> int:
    """(Re)build Settings/AddIns.xml and Settings/Offers.xml from Manifests.

    data_root   — DAO data folder (output Settings/ lives here)
    mod_staging — optional staging root; Manifests are read from here so the
                  registry reflects every enabled mod even when Manifest.xml is
                  not deployed into the data folder. Falls back to data_root.
    Returns the total number of registry items written across both files.
    """
    _log = log_fn or (lambda _: None)
    settings_dir = data_root / "Settings"
    settings_dir.mkdir(parents=True, exist_ok=True)

    search_root = mod_staging if mod_staging and mod_staging.is_dir() else data_root

    total = 0
    for subdir, item_tag, list_tag, out_name in _REGISTRIES:
        items: dict[str, ET.Element] = {}  # UID → item element (dedup, last wins)
        for manifest in _iter_manifests(search_root, subdir):
            try:
                root = ET.parse(manifest).getroot()
            except ET.ParseError as exc:
                _log(f"  [DAO] skipping bad Manifest {manifest}: {exc}")
                continue
            container = root.find(list_tag)
            if container is None:
                continue
            for item in container.findall(item_tag):
                uid = item.get("UID")
                if uid:
                    items[uid] = item

        out_path = settings_dir / out_name
        if not items:
            # No content of this type — write an empty list so the game finds a
            # valid (vanilla-equivalent) registry rather than stale entries.
            _write_list(out_path, list_tag, [])
            _log(f"  [DAO] {out_name}: no items (wrote empty list).")
            continue

        _write_list(out_path, list_tag, list(items.values()))
        _log(f"  [DAO] {out_name}: wrote {len(items)} item(s).")
        total += len(items)

    return total


def _write_list(out_path: Path, list_tag: str, items: list[ET.Element]) -> None:
    """Write a registry file containing list_tag with the given items."""
    root = ET.Element(list_tag)
    for item in items:
        root.append(item)
    xml_str = ET.tostring(root, encoding="unicode")
    xml_str = xml_str.replace(
        'RequiresAuthorization="1"', 'RequiresAuthorization="0"'
    )
    out_path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n' + xml_str,
        encoding="utf-8",
    )


def reset_registry_xml(data_root: Path, log_fn=None) -> None:
    """Reset AddIns.xml / Offers.xml to empty vanilla lists (used on restore)."""
    _log = log_fn or (lambda _: None)
    settings_dir = data_root / "Settings"
    if not settings_dir.is_dir():
        return
    for _subdir, _item_tag, list_tag, out_name in _REGISTRIES:
        out_path = settings_dir / out_name
        if out_name == "Offers.xml" and not out_path.exists():
            # Vanilla installs ship AddIns.xml but not always Offers.xml.
            continue
        _write_list(out_path, list_tag, [])
        _log(f"  [DAO] reset {out_name} to empty list.")
