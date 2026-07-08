# i18n tooling

Everything for translating the app's UI lives here. Paths below are from the
repo root.

## Quick start (GUI)

```sh
./tools/i18n/translation_manager.sh
```

A window to: pick the translations folder, see each language's status vs the
English base, pick a backend (DeepL / LibreTranslate / Auto), start/stop the
local LibreTranslate server, and run a refresh with a live log.

## The workflow

Translation `.ts`/`.qm` normally live on the **Resources branch** and are synced
to users at runtime. To update after changing UI strings:

1. Copy the current language files into `src/translations/`.
2. Refresh (GUI, or `./tools/i18n/refresh_translations.sh src/translations`).
3. Move the updated files back to the Resources branch's `Localisation/`.

`src/translations/` ships **English only**; other languages come via the sync.

## Files

| File | What it does |
|------|--------------|
| `translation_manager.sh` | Launch the GUI (`i18n_gui.py`) with the app's venv. |
| `i18n_gui.py` | PySide6 GUI — a thin front-end over the scripts below. |
| `refresh_translations.sh` | **Main command.** Merge new strings into each language + machine-translate only the new ones + recompile. Auto-picks the backend. |
| `libretranslate_server.sh` | `start`/`stop`/`status`/`setup` a local LibreTranslate server (free DeepL fallback). Handles venv + model downloads. |
| `i18n_deepl.py` | DeepL backend (needs `DEEPL_API_KEY`). |
| `i18n_libre.py` | LibreTranslate backend (needs the local server). |
| `i18n_update.sh` | Extract strings → refresh the English base (`amethyst_en.ts`) + compile. |
| `i18n_wrap.py` | Dev tool: auto-wrap unwrapped `tr()` strings in a source file. |
| `i18n_batch.sh` | Run `i18n_wrap.py` over many files. |

## Translation backends

`refresh_translations.sh` auto-selects: **DeepL** (if `DEEPL_API_KEY` set and has
quota — it probes `/usage`) → **LibreTranslate** (if the local server is up) →
**none** (merge + report only). Force one with `AMM_MT_BACKEND=deepl|libre|none`.

DeepL free tier is 500k chars/month. When it's exhausted, use LibreTranslate:

```sh
./tools/i18n/libretranslate_server.sh start   # sets up + runs (models cache after 1st run)
./tools/i18n/refresh_translations.sh src/translations   # auto-detects the server
./tools/i18n/libretranslate_server.sh stop
```

## Notes

- Machine translations (both backends) are **placeholder quality** — a native
  review is worth it before calling a language "official". LibreTranslate is
  rougher than DeepL, especially for CJK.
- Placeholders (`{0}`, `{1}`) are protected during translation and verified
  after; the refresh reports 0 placeholder mismatches when clean.
- `-locations none` is used so a code edit that shifts line numbers never churns
  the `.ts` — they only change when a string does.
