#!/bin/bash
# Dev helper: run i18n_wrap.py over many files. Dry-run by default (shows the
# wrappable/manual counts per file); pass --apply to actually rewrite them.
#   ./tools/i18n_batch.sh src/gui_qt/foo.py src/gui_qt/bar.py          # dry-run
#   ./tools/i18n_batch.sh --apply src/gui_qt/foo.py ...                # rewrite
# After --apply, review the SKIP lines it prints and finish those by hand.
cd "$(dirname "$0")/../.."
PY=".venv/bin/python3"
APPLY=""
FILES=()
for a in "$@"; do
    if [ "$a" = "--apply" ]; then APPLY="--apply"; else FILES+=("$a"); fi
done
for f in "${FILES[@]}"; do
    "$PY" tools/i18n/i18n_wrap.py "$f" $APPLY
    # Always show what still needs manual attention.
    "$PY" tools/i18n/i18n_wrap.py "$f" --list 2>/dev/null | grep SKIP
    # Fail loudly if the file no longer parses.
    "$PY" -c "import ast; ast.parse(open('$f').read())" || echo "!!! $f DOES NOT PARSE"
done
