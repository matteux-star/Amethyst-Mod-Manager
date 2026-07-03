#!/bin/bash
# Compile an edited Amethyst translation (.ts) into the .qm the app loads.
#
#   ./tools/compile.sh amethyst_fr.ts        # compile one file
#   ./tools/compile.sh                        # compile every amethyst_*.ts here
#
# Run this from the Localisation/ folder after you finish translating a .ts.
# It produces amethyst_<code>.qm next to the .ts — that .qm is what you commit
# (and what the manager downloads on startup).
#
# Requires a Qt "lrelease". The script auto-detects, in order:
#   1. pyside6-lrelease            (pip install PySide6)
#   2. lrelease-qt6 / lrelease6    (system Qt6 tools, e.g. qt6-tools)
#   3. lrelease                    (system Qt5/Qt6 tools)
set -e
cd "$(dirname "$0")/.."   # -> Localisation/

# Find a working lrelease.
LRELEASE=""
for cand in pyside6-lrelease lrelease-qt6 lrelease6 lrelease; do
    if command -v "$cand" >/dev/null 2>&1; then
        LRELEASE="$cand"
        break
    fi
done
if [ -z "$LRELEASE" ]; then
    echo "error: no 'lrelease' found. Install one of:" >&2
    echo "  pip install PySide6            (gives pyside6-lrelease)" >&2
    echo "  or your distro's Qt6 tools package (qt6-tools / qttools5-dev-tools)" >&2
    exit 1
fi
echo "using: $LRELEASE"

if [ "$#" -gt 0 ]; then
    FILES=("$@")
else
    FILES=(amethyst_*.ts)
fi

for ts in "${FILES[@]}"; do
    # Skip the English reference base — it's only a copy-paste source.
    case "$ts" in
        amethyst_en.ts) echo "skip $ts (English reference, not a shipped language)"; continue ;;
    esac
    [ -f "$ts" ] || { echo "skip $ts (not found)"; continue; }
    echo ">> $ts"
    "$LRELEASE" "$ts"
done

echo "done. Commit the generated amethyst_<code>.qm (and your edited .ts)."
