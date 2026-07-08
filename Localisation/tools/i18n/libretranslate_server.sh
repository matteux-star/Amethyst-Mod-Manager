#!/bin/bash
# Manage a LOCAL LibreTranslate server for machine-translating the app's
# strings for free (the DeepL fallback). Handles the fiddly one-time setup:
# a throwaway venv, model downloads, and start/stop.
#
#   ./tools/libretranslate_server.sh start [lang...]   # set up + run (background)
#   ./tools/libretranslate_server.sh stop              # stop it
#   ./tools/libretranslate_server.sh status            # is it up? which langs?
#   ./tools/libretranslate_server.sh setup [lang...]   # just install venv+models
#
# With no lang args, start/setup use the app's shipped set (matches
# src/translations/). Models are cached in ~/.local/share/argos-translate, so
# they're only downloaded once — re-running is fast.
#
# The venv lives in /tmp (throwaway; NEVER the app .venv). The server listens on
# 127.0.0.1:5000; refresh_translations.sh / i18n_libre.py pick it up there.
set -e
cd "$(dirname "$0")/../.."

LTVENV="${AMM_LT_VENV:-/tmp/ltvenv}"
LT_HOST="127.0.0.1"
LT_PORT="${AMM_LT_PORT:-5000}"
LT_LOG="/tmp/libretranslate.log"
LT_URL="http://$LT_HOST:$LT_PORT"

# App's shipped languages → the LibreTranslate codes to load. Mirrors
# i18n_libre.py _LT_TARGET (pt_BR→pt-BR, zh→zh-Hans). Keep in sync when adding a
# language.
_default_lt_codes() {
    echo "en fr de es it pt pt-BR ru pl zh-Hans ja nl cs"
}

_ensure_venv() {
    if [ ! -x "$LTVENV/bin/libretranslate" ]; then
        echo ">> creating throwaway venv + installing libretranslate ($LTVENV)…"
        python3 -m venv "$LTVENV"
        "$LTVENV/bin/pip" install -q --upgrade pip >/dev/null 2>&1 || true
        "$LTVENV/bin/pip" install -q libretranslate
    fi
}

# argos MODEL codes differ from the API/load codes: pt-BR model = "pb",
# zh-Hans model = "zh". Map an API/load code -> argos model to_code.
_argos_code() {
    case "$1" in
        pt-BR|pt_BR) echo "pb" ;;
        zh-Hans|zh)  echo "zh" ;;
        zh-Hant)     echo "zt" ;;
        *)           echo "$1" ;;
    esac
}

_install_models() {
    _ensure_venv
    local codes=("$@")
    [ "${#codes[@]}" -eq 0 ] && read -r -a codes <<< "$(_default_lt_codes)"
    # Build the argos to_code list (unique, minus en which is the source).
    local argos=()
    for c in "${codes[@]}"; do
        [ "$c" = "en" ] && continue
        argos+=("$(_argos_code "$c")")
    done
    echo ">> ensuring en-> models installed: ${argos[*]}"
    AMM_ARGOS="${argos[*]}" "$LTVENV/bin/python3" - <<'PY'
import os
import argostranslate.package as pkg
pkg.update_package_index()
avail = pkg.get_available_packages()
installed = {(p.from_code, p.to_code) for p in pkg.get_installed_packages()}
want = os.environ["AMM_ARGOS"].split()
for code in want:
    if ("en", code) in installed:
        print(f"   {code}: already installed"); continue
    p = next((p for p in avail if p.from_code == "en" and p.to_code == code), None)
    if p is None:
        print(f"   {code}: NO PACKAGE (skipped)"); continue
    pkg.install_from_path(p.download())
    print(f"   {code}: installed")
PY
}

_is_up() { curl -s -o /dev/null -m 3 "$LT_URL/languages" 2>/dev/null; }

case "${1:-}" in
    setup)
        shift || true
        _install_models "$@"
        echo "done. Start it with: $0 start"
        ;;
    start)
        shift || true
        if _is_up; then
            echo "already running at $LT_URL"; exit 0
        fi
        _install_models "$@"
        echo ">> starting LibreTranslate at $LT_URL (log: $LT_LOG)…"
        nohup "$LTVENV/bin/libretranslate" --host "$LT_HOST" --port "$LT_PORT" \
            --threads 2 > "$LT_LOG" 2>&1 &
        disown || true
        # Wait for it to load models + answer.
        for i in $(seq 1 60); do
            if _is_up; then break; fi
            sleep 2
        done
        if _is_up; then
            echo "up. Loaded languages:"
            curl -s -m 8 "$LT_URL/languages" 2>/dev/null \
                | "$LTVENV/bin/python3" -c \
                  'import sys,json;print("  ",sorted(x["code"] for x in json.load(sys.stdin)))'
            echo ""
            echo "Now translate — refresh_translations.sh auto-detects it:"
            echo "  ./tools/refresh_translations.sh src/translations"
        else
            echo "!! server didn't come up — check $LT_LOG" >&2
            tail -5 "$LT_LOG" >&2 || true
            exit 1
        fi
        ;;
    stop)
        pkill -f "libretranslate --host $LT_HOST" 2>/dev/null || true
        sleep 1
        if _is_up; then echo "!! still up (check for other instances)"; exit 1; fi
        echo "stopped."
        ;;
    status)
        if _is_up; then
            echo "UP at $LT_URL. Languages:"
            curl -s -m 8 "$LT_URL/languages" 2>/dev/null \
                | python3 -c \
                  'import sys,json;print("  ",sorted(x["code"] for x in json.load(sys.stdin)))' \
                2>/dev/null || echo "  (couldn't list)"
        else
            echo "not running."
        fi
        ;;
    *)
        sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
        exit 2
        ;;
esac
