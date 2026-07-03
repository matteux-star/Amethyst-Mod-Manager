# Amethyst Mod Manager — Translations

This folder holds the UI translations the manager downloads on startup. Each
language is a compiled `amethyst_<code>.qm` file; the app scans this folder and
offers every language it finds in **Settings ▸ Language** (and on the first-run
onboarding screen).

Because translations are fetched from here at runtime, **new languages and fixes
reach users without an app update** — just add or update a `.qm` in this folder.

## Files here

| File | What it is |
|------|-----------|
| `amethyst_<code>.qm` | Compiled translation the app loads (e.g. `amethyst_fr.qm`). **This is what ships.** |
| `amethyst_<code>.ts` | The editable source for that language (XML). Edit this, then compile it to `.qm`. |
| `amethyst_en.ts` | The English reference — every translatable string, with the English text. Start new languages from this. Not a shipped language (English is built into the app). |
| `tools/` | Helper scripts (see below). |

`<code>` is an ISO 639-1 language code: `fr` French, `de` German, `es` Spanish,
`pt` Portuguese, `it` Italian, `pl` Polish, `ru` Russian, `zh` Chinese,
`ja` Japanese, …

## Add a new language

1. **Create the file** from the English reference:

   ```sh
   python3 tools/new_language.py de        # makes amethyst_de.ts
   ```

2. **Translate.** Open `amethyst_de.ts` in **Qt Linguist** (nicest) or any text
   editor. For each entry, replace the text inside `<translation>` with your
   translation; the `<source>` tag shows the English. Entries start marked
   `type="unfinished"` so Linguist can highlight what's left.

   **Keep placeholders intact.** Some strings contain `{0}`, `{1}`, … — these are
   filled in at runtime (a mod name, a count, etc.). Keep every placeholder; you
   may reorder them to fit your language's grammar.

   ```xml
   <source>Removed {0} archive(s)</source>
   <translation>{0} Archiv(e) entfernt</translation>
   ```

3. **Compile** the `.ts` into the `.qm` the app loads:

   ```sh
   ./tools/compile.sh amethyst_de.ts
   ```

4. **Submit** both `amethyst_de.ts` and `amethyst_de.qm`.

On the next launch the manager detects the new language automatically — no app
update needed. Users can also drop a `.qm` straight into
`~/.config/AmethystModManager/languages/` to test it locally, and use the
**Sync language files** button (Settings / onboarding) to pull the latest.

## Fix or update an existing language

1. Edit its `amethyst_<code>.ts`.
2. `./tools/compile.sh amethyst_<code>.ts`
3. Submit the updated `.ts` + `.qm`.

## When the app adds new strings

When the manager gains new UI text, the English reference (`amethyst_en.ts`)
here is refreshed with the new strings, and each existing `amethyst_<code>.ts`
gains those strings marked `unfinished` (existing translations are preserved).
Re-open your `.ts`, translate the new `unfinished` entries, recompile, and
submit — the rest of your work is untouched.

## Requirements for compiling

`tools/compile.sh` needs a Qt **lrelease**. Any of these works (it auto-detects):

- `pip install PySide6` → gives `pyside6-lrelease` *(easiest)*
- your distro's Qt6 tools package (`qt6-tools`, `qttools5-dev-tools`, …) →
  gives `lrelease` / `lrelease-qt6`

Qt Linguist for editing comes from the same Qt tools package (`pyside6-linguist`
if you installed PySide6).

## Notes

- **English is built into the app** — it needs no file here and is always
  available as the source language.
- **Qt's own dialog text** (OK/Cancel and other standard buttons) is localised
  automatically from Qt's bundled translations — you don't translate those.
- Machine translation (e.g. DeepL) is fine for a first pass to get coverage, but
  it makes context mistakes (e.g. "Disabled" as *disabled person* vs *turned
  off*) — a human review is worth it.
