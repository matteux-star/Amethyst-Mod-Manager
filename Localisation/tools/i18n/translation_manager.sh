#!/bin/bash
# Launch the Translation Manager GUI (PySide6 front-end over the i18n tooling).
#
#   ./tools/translation_manager.sh
#
# Uses the project-root .venv (same one the app uses — it has PySide6).
cd "$(dirname "$0")/../.."
VENV=".venv"
if [ ! -x "$VENV/bin/python3" ]; then
    echo "error: $VENV not found. Run src/run_qt.sh once to build it." >&2
    exit 1
fi
exec "$VENV/bin/python3" tools/i18n/i18n_gui.py "$@"
