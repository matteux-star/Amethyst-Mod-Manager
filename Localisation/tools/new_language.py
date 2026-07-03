#!/usr/bin/env python3
"""Start a new Amethyst translation from the English reference.

    python3 tools/new_language.py de        # create amethyst_de.ts

Creates ``amethyst_<code>.ts`` in the Localisation/ folder by cloning
``amethyst_en.ts`` (the full list of every translatable string, with the
English text as a reference) and blanking each translation so you can fill it
in. Then:

  1. Edit ``amethyst_<code>.ts`` — translate each ``<translation>``. Use Qt
     Linguist (nicer) or any text editor; the <source> tag shows the English.
     The English text is pre-filled as a starting point — replace it.
  2. Compile:  ./tools/compile.sh amethyst_<code>.ts
  3. Commit both ``amethyst_<code>.ts`` and the generated ``amethyst_<code>.qm``.

The manager auto-detects the new language on next launch (it scans this folder
for ``amethyst_*.qm``), so no app update is needed.

``<code>`` is an ISO 639-1 language code: de (German), es (Spanish),
pt (Portuguese), it (Italian), pl (Polish), ru (Russian), zh (Chinese),
ja (Japanese), ...

Pure standard library — no dependencies.
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

LOC_DIR = Path(__file__).resolve().parent.parent
EN_TS = LOC_DIR / "amethyst_en.ts"


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1].startswith("-"):
        print(__doc__)
        return 2
    code = sys.argv[1].strip().lower()

    if not EN_TS.is_file():
        print(f"error: {EN_TS.name} not found in {LOC_DIR}", file=sys.stderr)
        return 1

    out = LOC_DIR / f"amethyst_{code}.ts"
    if out.exists():
        print(f"error: {out.name} already exists — edit it, don't recreate.",
              file=sys.stderr)
        return 1

    tree = ET.parse(EN_TS)
    root = tree.getroot()
    root.set("language", code)
    n = 0
    for msg in root.iter("message"):
        src = msg.find("source")
        tr = msg.find("translation")
        if src is None or tr is None:
            continue
        # Pre-fill with the English source as a starting point, and mark
        # unfinished so Qt Linguist highlights what still needs work.
        tr.text = src.text or ""
        tr.set("type", "unfinished")
        n += 1

    body = ET.tostring(root, encoding="unicode")
    with out.open("w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE TS>\n')
        f.write(body)
        f.write("\n")

    print(f"created {out.name} with {n} strings to translate.")
    print(f"next: edit {out.name}, then ./tools/compile.sh {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
