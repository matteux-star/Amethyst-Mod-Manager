"""
sseedit.py
Wizard for running xEdit (SSEEdit / FO4Edit / FNVEdit / FO3Edit / TES4Edit /
TES5Edit / SF1Edit ...) with a Bethesda game.

Workflow
--------
1. Prompt the user to download the matching xEdit build from Nexus Mods
   (manual download only).
2. Auto-detect and extract the archive to Profiles/<game>/Applications/<dir>/.
3. Deploy the modlist.
4. User picks the Proton version; xEdit gets its own isolated prefix
   (prefix_<ProtonName>/ next to the exe), independent of the game's Proton.
5. Run <xEdit>.exe via Proton with -d:<game>/Data, after seeding the game's
   Installed Path into the prefix registry, symlinking the profile's
   plugins.txt into the prefix AppData, linking the game prefix's My Games
   folder (xEdit fatals without the game INI) and setting the per-app
   WinXP compat flag in the tool prefix.

Plugins that xEdit creates or cleans are not handled here: they are rescued by
the game's ``restore()`` (which calls ``restore_data_core`` with ``overwrite_dir``
+ ``staging_root``) on the next deploy. That logic is generic to every Bethesda
game, so this wizard only needs the per-game exe name + Nexus URL, supplied via
the ``WizardTool.extra`` kwargs below (with SSEEdit defaults for back-compat).
"""

from __future__ import annotations

import os
import re as _re
import shutil
import subprocess
from Utils.steam_finder import proton_run_command
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import customtkinter as ctk

from Utils.atomic_write import write_atomic_text
from Utils.xdg import open_url
from Utils.portal_filechooser import pick_file
from gui.path_utils import _to_wine_path

if TYPE_CHECKING:
    from Games.base_game import BaseGame

from gui.theme import (
    ACCENT, ACCENT_HOV, BG_DEEP, BG_HEADER, BG_PANEL,
    TEXT_ON_ACCENT,
    TEXT_DIM, TEXT_MAIN,
    FONT_NORMAL, FONT_BOLD,
)

_NEXUS_URL   = "https://www.nexusmods.com/skyrimspecialedition/mods/164?tab=files&file_id=495506"
_EXE_NAME         = "SSEEdit.exe"
_APP_DIR          = "SSEEdit"

# xEdit / QuickAutoClean can save the cleaned plugin to a temp file and queue
# the rename to the real name "on shutdown" (e.g.
# ``AlternatePerspective.esp.save.2026_06_19_00_38_14`` -> ``…esp``).  Matches
# ``<plugin>.save.<timestamp>`` so _finalize_xedit_saves can complete the rename.
_XEDIT_SAVE_TEMP_RE = _re.compile(r"^(?P<base>.+)\.save\.[0-9_]+$", _re.IGNORECASE)


def _finalize_xedit_saves(data_dir: Path, log_fn=None) -> int:
    """Complete any pending xEdit ``<plugin>.save.<timestamp>`` renames in
    *data_dir* so the cleaned plugin sits at its real name before we rebuild the
    filemap/index.  Returns the number of temps finalised.

    Only acts on the top level of Data/ (where xEdit writes plugins).  If both a
    temp and the base name exist, the temp wins (it is the freshly-saved copy)
    and replaces the base via ``os.replace`` (atomic, clobbers a stale symlink).
    """
    _log = log_fn or (lambda _: None)
    finalised = 0
    try:
        entries = list(data_dir.iterdir())
    except OSError:
        return 0
    for entry in entries:
        m = _XEDIT_SAVE_TEMP_RE.match(entry.name)
        if m is None:
            continue
        # Only finalise temps for actual plugins; ignore unrelated ".save." names.
        base_name = m.group("base")
        if not base_name.lower().endswith((".esp", ".esm", ".esl")):
            continue
        base_path = entry.with_name(base_name)
        try:
            os.replace(str(entry), str(base_path))
            finalised += 1
            _log(f"Finalised xEdit save: {entry.name} -> {base_name}")
        except OSError as exc:
            _log(f"WARN: could not finalise xEdit save {entry.name}: {exc}")
    return finalised


def _get_applications_dir(game: "BaseGame", app_dir: str = _APP_DIR) -> Path:
    return game.get_mod_staging_path().parent / "Applications" / app_dir


def _sseedit_exe_path(
    game: "BaseGame", exe_name: str = _EXE_NAME, app_dir: str = _APP_DIR
) -> Path | None:
    p = _get_applications_dir(game, app_dir) / exe_name
    return p if p.is_file() else None


def _find_archive(downloads_dir: Path, name_hint: str = "sseedit") -> Path | None:
    if not downloads_dir.is_dir():
        return None
    hint = name_hint.lower()
    candidates = [
        p for p in downloads_dir.iterdir()
        if p.is_file()
        and p.suffix.lower() in {".zip", ".7z", ".rar"}
        and hint in p.name.lower()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _flatten_subdirs(dest: Path, exe_name: str) -> None:
    """Collapse single-subdir wrappers until exe_name is at the top level."""
    while True:
        all_entries = [e for e in dest.iterdir() if e.name != "__MACOSX"]
        subdirs = [e for e in all_entries if e.is_dir()]
        if len(subdirs) == 1 and not (dest / exe_name).is_file():
            wrapper = subdirs[0]
            tmp = dest.parent / (dest.name + "_flatten_tmp")
            wrapper.rename(tmp)
            for item in tmp.iterdir():
                shutil.move(str(item), str(dest / item.name))
            tmp.rmdir()
        else:
            break


def _set_winxp_compat(prefix_path: Path, exe: Path, log_fn=None) -> None:
    """Set the Wine per-app Windows version for *exe* to Windows XP.

    This writes the same entry that winecfg writes when you select an
    application and change its Windows Version to "Windows XP":
        HKCU\\Software\\Wine\\AppDefaults\\<exe.name>  "Version"="winxp"
    in user.reg.
    """
    import time as _time

    _log = log_fn or (lambda _: None)

    # Accept either pfx/ directly or its compatdata parent
    if not (prefix_path / "user.reg").is_file() and (prefix_path / "pfx" / "user.reg").is_file():
        prefix_path = prefix_path / "pfx"
    user_reg = prefix_path / "user.reg"
    if not user_reg.is_file():
        _log(f"Warning: user.reg not found at {user_reg}; skipping WinXP version flag.")
        return

    try:
        text = user_reg.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        _log(f"Warning: could not read user.reg: {exc}")
        return

    section_header = f"[Software\\\\Wine\\\\AppDefaults\\\\{exe.name}]"
    lines = text.splitlines(keepends=True)

    section_start: int | None = None
    section_end: int | None = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.lower().startswith(section_header.lower()):
            section_start = i
        elif section_start is not None and stripped.startswith("["):
            section_end = i
            break

    _filetime_hex = format(int((_time.time() + 11644473600) * 1e7), "x")
    entry_line = '"Version"="winxp"\n'

    if section_start is None:
        if lines and not lines[-1].endswith("\n"):
            lines.append("\n")
        lines.append("\n")
        lines.append(f"{section_header} {_filetime_hex}\n")
        lines.append(f"#time={_filetime_hex}\n")
        lines.append(entry_line)
        _log(f"SSEEdit: set Windows version to WinXP for {exe.name}.")
    else:
        body_start = section_start + 1
        body_end = section_end if section_end is not None else len(lines)
        key_lines = lines[body_start:body_end]

        lines[section_start] = f"{section_header} {_filetime_hex}\n"
        for j, kline in enumerate(key_lines):
            if kline.lower().startswith("#time="):
                key_lines[j] = f"#time={_filetime_hex}\n"
                break

        found = False
        for j, kline in enumerate(key_lines):
            if kline.lower().startswith('"version"='):
                if kline.strip() != entry_line.strip():
                    key_lines[j] = entry_line
                    _log(f"SSEEdit: updated Windows version to WinXP for {exe.name}.")
                found = True
                break
        if not found:
            key_lines.append(entry_line)
            _log(f"SSEEdit: set Windows version to WinXP for {exe.name}.")

        lines[body_start:body_end] = key_lines

    try:
        write_atomic_text(user_reg, "".join(lines))
    except OSError as exc:
        _log(f"Warning: could not write user.reg: {exc}")


def _xedit_settings_ext(xedit_name: str) -> str:
    """Derive the xEdit viewsettings extension from the build name.

    xEdit names its per-game settings file ``Plugins.<mode>viewsettings``
    where ``<mode>`` is the build name minus the trailing ``Edit``, lowercased:
      FO4Edit  -> fo4   (Plugins.fo4viewsettings)
      SSEEdit  -> sse   (Plugins.sseviewsettings)
      TES4Edit -> tes4  (Plugins.tes4viewsettings)
      SF1Edit  -> sf1   (Plugins.sf1viewsettings)
    """
    name = xedit_name
    if name.lower().endswith("edit"):
        name = name[: -len("edit")]
    return name.lower()


def _seed_xedit_viewsettings(game: "BaseGame", pfx: Path, xedit_name: str, log_fn=None) -> None:
    """Pre-create the xEdit viewsettings file so the first-run messages
    ("What's New" + developer message) never appear in a fresh tool prefix.

    A fresh prefix has no ``Plugins.<mode>viewsettings`` next to the game's
    AppData/Local data dir, so xEdit shows its nag dialogs every time the
    prefix is recreated. Seeding the gate keys suppresses them:

      [Options]          ShowTip=0            — no Tip of the Day on startup
      [WhatsNew]         Version=<very high>  — newer than any running build
      [DeveloperMessage] LastShownOn=<far-future Delphi date serial>

    ``LastShownOn`` is a Delphi ``TDateTime`` integer (days since 1899-12-30);
    xEdit re-shows the message when it is older than today, so we write a
    date well in the future. Skips if a settings file already exists (the
    user's real layout/preferences must win).
    """
    _log = log_fn or (lambda _: None)

    subpath = getattr(game, "_APPDATA_SUBPATH", None)
    if subpath is None:
        return
    data_dir = pfx / subpath
    ext = _xedit_settings_ext(xedit_name)
    settings_file = data_dir / f"Plugins.{ext}viewsettings"

    if settings_file.exists():
        return  # real settings already present — don't clobber

    # Far-future Delphi date serial (1899-12-30 epoch) so the developer
    # message stays dismissed: 2099-01-01 -> 72686.
    last_shown = 72686
    content = (
        "[Options]\r\n"
        "ShowTip=0\r\n"
        "\r\n"
        "[WhatsNew]\r\n"
        "Version=99999999\r\n"
        "\r\n"
        "[DeveloperMessage]\r\n"
        f"LastShownOn={last_shown}\r\n"
        "Version=99999999\r\n"
    )
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        write_atomic_text(settings_file, content)
        _log(f"seeded {settings_file.name} to suppress first-run messages")
    except OSError as exc:
        _log(f"could not seed {settings_file.name}: {exc}")


from wizards._proton_prefix import ProtonPrefixStepMixin, shutdown_prefix_wineserver


class SSEEditWizard(ProtonPrefixStepMixin, ctk.CTkFrame):
    """Step-by-step wizard to set up and run an xEdit build for a Bethesda game.

    Per-game configuration is supplied via ``WizardTool.extra`` kwargs:
      ``xedit_exe``     — exe name, e.g. ``"FO4Edit.exe"`` (default SSEEdit.exe)
      ``nexus_url``     — Nexus download page for the matching xEdit build
      ``app_dir``       — extraction subfolder under Applications/ (default exe stem)
      ``display_name``  — short name shown in the UI (default exe stem)
    When omitted, the SSEEdit defaults below are used (back-compat for Skyrim SE).
    """

    _wizard_title = "Run SSEEdit"
    _exe_name     = _EXE_NAME

    # QAC subclasses set this to the QuickAutoClean exe suffix; None = full xEdit.
    _qac          = False

    _proton_step_title = "Step 5: Choose Proton Version"

    def _proton_next_step(self):
        self._show_step_run()

    def __init__(
        self,
        parent,
        game: "BaseGame",
        log_fn=None,
        *,
        on_close=None,
        xedit_exe: str | None = None,
        nexus_url: str | None = None,
        app_dir: str | None = None,
        display_name: str | None = None,
        **_kwargs,
    ):
        super().__init__(parent, fg_color=BG_DEEP, corner_radius=0)
        self._on_close_cb = on_close or (lambda: None)
        self._game        = game
        self._log         = log_fn or (lambda msg: None)
        self._archive_path: Path | None = None

        # Resolve per-game config from kwargs, falling back to SSEEdit defaults.
        base_exe = xedit_exe or self._exe_name
        self._exe_name = (
            base_exe[: -len(".exe")] + "QuickAutoClean.exe"
            if self._qac and base_exe.lower().endswith(".exe")
            else base_exe
        )
        self._nexus_url   = nexus_url or _NEXUS_URL
        self._app_dir     = app_dir or base_exe.removesuffix(".exe")
        short = display_name or base_exe.removesuffix(".exe")
        self._xedit_name        = short  # build name w/o QAC, e.g. "FO4Edit"
        self._tool_display_name = short + (" QAC" if self._qac else "")
        self._wizard_title      = "Run " + self._tool_display_name

        self._exe         = _sseedit_exe_path(game, self._exe_name, self._app_dir)
        self._proton_name = ""
        self._tool_exe_name     = self._exe_name
        self._exe_missing_text  = (
            f"{self._exe_name} was not found.\n"
            f"Please restart the wizard and install {short} first."
        )

        title_bar = ctk.CTkFrame(self, fg_color=BG_HEADER, corner_radius=0, height=40)
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)
        ctk.CTkLabel(
            title_bar,
            text=f"{self._wizard_title} \u2014 {game.name}",
            font=FONT_BOLD, text_color=TEXT_MAIN, anchor="w",
        ).pack(side="left", padx=12, pady=8)
        ctk.CTkButton(
            title_bar, text="\u2715", width=32, height=32, font=FONT_BOLD,
            fg_color="transparent", hover_color=BG_PANEL, text_color=TEXT_MAIN,
            command=self._on_close_cb,
        ).pack(side="right", padx=4, pady=4)

        self._body = ctk.CTkFrame(self, fg_color=BG_DEEP)
        self._body.pack(fill="both", expand=True, padx=20, pady=20)

        self._show_step_download()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _clear_body(self):
        for w in self._body.winfo_children():
            w.destroy()

    def _set_label(self, attr: str, text: str, color: str = TEXT_DIM):
        def _apply(t=text, c=color):
            try:
                widget = getattr(self, attr, None)
                if widget is not None and widget.winfo_exists():
                    widget.configure(text=t, text_color=c)
            except Exception:
                pass
        self.after(0, _apply)

    def _restore_after_xedit(self) -> None:
        """Fully un-deploy the game (Data/ + Root_Folder) after xEdit closes,
        moving any plugin xEdit edited in Data/ back into its owning mod folder
        BEFORE the panel refresh rescans staging.

        This mirrors the Restore button: ``game.restore()`` undoes the Data/
        deploy, then ``restore_root_folder()`` removes the root-deployed files
        from the game directory.  Earlier this only ran ``game.restore()``,
        leaving root-folder deployed files behind in the game install.

        QuickAutoClean backs the original plugin up into ``Data/<tool> Backups/``
        — which, under symlink-mode deploy, consumes the staging copy (the Data
        entry was a symlink into staging) — and writes the cleaned plugin as a
        fresh regular file in Data/.  If we let the wizard-close ``_reload``
        rescan staging now, ``rebuild_mod_index`` finds the mod folder missing
        its plugin and drops it from the index; the next Restore then can't
        recognise the cleaned file and buries it in overwrite/.

        Running ``restore()`` first walks Data/ while the index still knows the
        plugin, so its orphan-rescue moves the cleaned file back into the mod
        folder.  The rescan that follows then sees the restored plugin and keeps
        it.  No-op for games without ``restore``; failures are logged, not
        raised (a normal redeploy/restore can still recover).
        """
        game = self._game
        if not hasattr(game, "restore"):
            return
        name = self._tool_display_name
        # Restore against the last-deployed profile so the cleaned file lands in
        # the right mod staging folder (mirrors the Deploy/Restore button flow).
        saved_profile_dir = getattr(game, "_active_profile_dir", None)
        restored_ok = False
        try:
            last_deployed = game.get_last_deployed_profile()
            if last_deployed:
                game.set_active_profile_dir(
                    game.get_profile_root() / "profiles" / last_deployed
                )
                # Reload so the last-deployed profile's path overrides apply.
                game.load_paths()
            try:
                game.restore(log_fn=lambda m: self._log(f"{name} Wizard: {m}"))
                # Restore Root_Folder too, so root-deployed files are removed
                # from the game directory exactly like the Restore button does
                # (game.restore only handles the Data/ deploy).
                from Utils.deploy import restore_root_folder
                root_folder_dir = game.get_effective_root_folder_path()
                game_root = game.get_game_path()
                if root_folder_dir.is_dir() and game_root:
                    restore_root_folder(
                        root_folder_dir, game_root,
                        log_fn=lambda m: self._log(f"{name} Wizard: {m}"),
                        data_deploy_dirs=game.root_restore_protect_dirs()
                        if hasattr(game, "root_restore_protect_dirs") else None,
                    )
                restored_ok = True
            except RuntimeError as exc:
                self._log(f"{name} Wizard: restore skipped: {exc}")
        except Exception as exc:
            self._log(f"{name} Wizard: post-edit restore failed: {exc}")
        finally:
            # Leave the active profile exactly as we found it so _reload_mod_panel
            # rebuilds the profile the user actually has selected.
            if saved_profile_dir is not None:
                try:
                    game.set_active_profile_dir(saved_profile_dir)
                    game.load_paths()
                except Exception:
                    pass
        # The game is no longer deployed — drop the deploy-active flag so the
        # profile dropdown loses its green "deployed" highlight (mirrors what the
        # Restore button does).  _on_done refreshes the menu colour afterwards.
        if restored_ok:
            try:
                game.clear_deploy_active()
            except Exception:
                pass

    def _on_done(self):
        try:
            topbar = self.winfo_toplevel()._topbar
        except Exception:
            topbar = None
        self._on_close_cb()
        if topbar is not None:
            try:
                topbar.after(0, topbar._reload_mod_panel)
                # _reload_mod_panel does NOT refresh the profile dropdown colour,
                # so clear the green "deployed" highlight explicitly now that
                # _restore_after_xedit dropped the deploy-active flag (mirrors the
                # Restore button, which also calls this after _reload_mod_panel).
                if hasattr(topbar, "_update_profile_menu_color"):
                    topbar.after(0, topbar._update_profile_menu_color)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Step 1 — Download xEdit (skipped if already extracted)
    # ------------------------------------------------------------------

    def _show_step_download(self):
        if _sseedit_exe_path(self._game, self._exe_name, self._app_dir) is not None:
            self._show_step_deploy()
            return

        self._clear_body()

        ctk.CTkLabel(
            self._body, text=f"Step 1: Download {self._xedit_name}",
            font=FONT_BOLD, text_color=TEXT_MAIN,
        ).pack(pady=(0, 12))

        ctk.CTkLabel(
            self._body,
            text=(
                f"Click the button below to open the {self._xedit_name} page on Nexus Mods.\n\n"
                "Download the archive manually (do NOT use the Mod Manager\n"
                "download button), then click Next."
            ),
            font=FONT_NORMAL, text_color=TEXT_DIM, justify="center",
        ).pack(pady=(0, 16))

        ctk.CTkButton(
            self._body, text="Open Download Page", width=220, height=36,
            font=FONT_BOLD,
            fg_color="#da8e35", hover_color="#e5a04a", text_color="white",
            command=lambda: open_url(self._nexus_url),
        ).pack(pady=(0, 20))

        ctk.CTkButton(
            self._body, text="Next \u2192", width=120, height=36,
            font=FONT_BOLD,
            fg_color=ACCENT, hover_color=ACCENT_HOV, text_color=TEXT_ON_ACCENT,
            command=self._show_step_locate,
        ).pack(side="bottom")

    # ------------------------------------------------------------------
    # Step 2 — Locate archive
    # ------------------------------------------------------------------

    def _show_step_locate(self):
        self._clear_body()

        ctk.CTkLabel(
            self._body, text="Step 2: Locate the Archive",
            font=FONT_BOLD, text_color=TEXT_MAIN,
        ).pack(pady=(0, 12))

        self._locate_status = ctk.CTkLabel(
            self._body, text="Searching Downloads folder\u2026",
            font=FONT_NORMAL, text_color=TEXT_DIM, justify="center", wraplength=460,
        )
        self._locate_status.pack(pady=(0, 12))

        btn_frame = ctk.CTkFrame(self._body, fg_color="transparent")
        btn_frame.pack(side="bottom", pady=(8, 0))

        ctk.CTkButton(
            btn_frame, text="Try Again", width=100, height=36,
            font=FONT_BOLD,
            fg_color=BG_HEADER, hover_color="#3d3d3d", text_color=TEXT_MAIN,
            command=self._scan_downloads,
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            btn_frame, text="Browse\u2026", width=100, height=36,
            font=FONT_BOLD,
            fg_color=BG_HEADER, hover_color="#3d3d3d", text_color=TEXT_MAIN,
            command=self._browse_archive,
        ).pack(side="right")

        self._scan_downloads()

    def _scan_downloads(self):
        found = _find_archive(Path.home() / "Downloads", self._xedit_name)
        if found:
            self._archive_path = found
            self._locate_status.configure(text=f"Found: {found.name}", text_color="#6bc76b")
            self.after(300, self._show_step_extract)
        else:
            self._archive_path = None
            self._locate_status.configure(
                text=(
                    f"{self._xedit_name} archive not found in Downloads.\n"
                    "Make sure you downloaded it, then press Try Again,\n"
                    "or use Browse to select it manually."
                ),
                text_color="#e06c6c",
            )

    def _browse_archive(self):
        def _on_picked(path: Path | None) -> None:
            if path and path.is_file():
                self._archive_path = path
                self._locate_status.configure(text=f"Selected: {path.name}", text_color="#6bc76b")
                self.after(300, self._show_step_extract)

        pick_file(f"Select the {self._xedit_name} archive", lambda p: self.after(0, lambda: _on_picked(p)))

    # ------------------------------------------------------------------
    # Step 3 — Extract archive
    # ------------------------------------------------------------------

    def _show_step_extract(self):
        self._clear_body()

        ctk.CTkLabel(
            self._body, text=f"Step 3: Extract {self._xedit_name}",
            font=FONT_BOLD, text_color=TEXT_MAIN,
        ).pack(pady=(0, 12))

        self._extract_status = ctk.CTkLabel(
            self._body, text="Extracting\u2026",
            font=FONT_NORMAL, text_color=TEXT_DIM, justify="center", wraplength=460,
        )
        self._extract_status.pack(pady=(0, 16))

        threading.Thread(target=self._do_extract, daemon=True).start()

    def _do_extract(self):
        try:
            from wizards.script_extender import _extract_archive

            archive = self._archive_path
            if archive is None or not archive.is_file():
                raise RuntimeError("Archive not found.")

            dest = _get_applications_dir(self._game, self._app_dir)
            dest.mkdir(parents=True, exist_ok=True)

            self._set_label("_extract_status", f"Extracting {archive.name}\u2026")
            self._log(f"{self._tool_display_name} Wizard: extracting {archive.name} \u2192 {dest}")

            paths = _extract_archive(archive, dest)
            file_count = len([p for p in paths if p.is_file()])
            self._log(f"{self._tool_display_name} Wizard: extracted {file_count} file(s).")

            _flatten_subdirs(dest, self._exe_name)

            exe = dest / self._exe_name
            if not exe.is_file():
                raise RuntimeError(
                    f"{self._exe_name} not found after extraction.\n"
                    f"Check that the archive contains {self._exe_name}."
                )
            self._exe = exe

            self._set_label("_extract_status", f"Extracted {file_count} file(s).", color="#6bc76b")
            self.after(0, self._show_step_deploy)

        except Exception as exc:
            self._set_label("_extract_status", f"Error: {exc}", color="#e06c6c")
            self._log(f"{self._tool_display_name} Wizard: extract error: {exc}")

    # ------------------------------------------------------------------
    # Step 4 — Deploy modlist
    # ------------------------------------------------------------------

    def _show_step_deploy(self):
        self._clear_body()

        ctk.CTkLabel(
            self._body, text="Step 4: Deploy Modlist",
            font=FONT_BOLD, text_color=TEXT_MAIN,
        ).pack(pady=(0, 12))

        self._deploy_status = ctk.CTkLabel(
            self._body, text="Deploying\u2026",
            font=FONT_NORMAL, text_color=TEXT_DIM, justify="center", wraplength=460,
        )
        self._deploy_status.pack(pady=(0, 12))

        ctk.CTkButton(
            self._body, text="Skip", width=100, height=32,
            font=FONT_NORMAL,
            fg_color=BG_HEADER, hover_color="#3d3d3d", text_color=TEXT_DIM,
            command=self._show_step_proton,
        ).pack(side="bottom")

        from gui.dialogs import confirm_deploy_appdata
        if not confirm_deploy_appdata(self.winfo_toplevel(), self._game):
            self._set_label("_deploy_status", "Deploy cancelled — AppData folder missing.", color="#e06c6c")
            return
        threading.Thread(target=self._do_deploy, daemon=True).start()

    def _do_deploy(self):
        try:
            # Use the canonical deploy orchestration (same as the Deploy button)
            # so root-flagged mods are deployed into the game root via
            # filemap_root.txt + deploy_root_flagged_mods.
            from Utils.deploy_pipeline import run_deploy_pipeline

            game = self._game
            try:
                root_win = self.winfo_toplevel()
                profile  = root_win._topbar._profile_var.get()
            except Exception:
                profile = "default"

            def _tlog(msg):
                self.after(0, lambda m=msg: self._log(m))

            success = run_deploy_pipeline(game, profile, log_fn=_tlog)

            if success:
                self._set_label("_deploy_status", "Deploy complete.", color="#6bc76b")
                self._refresh_topbar_deploy_state()
                self.after(0, self._show_step_proton)
            else:
                self._set_label("_deploy_status", "Deploy failed — see log.", color="#e06c6c")

        except Exception as exc:
            self._set_label("_deploy_status", f"Deploy error: {exc}", color="#e06c6c")
            self._log(f"{self._tool_display_name} Wizard: deploy error: {exc}")

    # ------------------------------------------------------------------
    # Step 6 — Run xEdit
    # ------------------------------------------------------------------

    def _collect_dirty_plugins(self) -> "list[tuple[str, str]]":
        """Return [(plugin_name, summary), ...] for plugins LOOT flags as dirty.

        Reads ``loot.json`` from the active profile dir (the same data the
        Plugins panel uses for its brush icon), so QuickAutoClean users can see
        which plugins need cleaning without closing the wizard to read the panel
        underneath it.  Empty list if LOOT has never run or nothing is dirty.
        """
        profile_dir = getattr(self._game, "_active_profile_dir", None)
        if profile_dir is None:
            return []
        try:
            from LOOT.loot_sorter import read_loot_info
            data = read_loot_info(profile_dir)
        except Exception:
            return []
        plugins = data.get("plugins", {}) if isinstance(data, dict) else {}
        version = data.get("version", 1) if isinstance(data, dict) else 1
        if version < 2 or not isinstance(plugins, dict):
            # v1 stored only a raw message list with no CRC-matched dirty data.
            return []
        out: "list[tuple[str, str]]" = []
        for name, info in plugins.items():
            if not isinstance(info, dict):
                continue
            dirty = info.get("dirty") or []
            if not dirty:
                continue
            parts: list[str] = []
            for d in dirty:
                if not isinstance(d, dict):
                    continue
                bits = []
                if d.get("itm"):
                    bits.append(f"{d['itm']} ITM")
                if d.get("udr"):
                    bits.append(f"{d['udr']} UDR")
                if d.get("nav"):
                    bits.append(f"{d['nav']} deleted navmesh")
                if bits:
                    parts.append(", ".join(bits))
            summary = "; ".join(parts) if parts else "needs cleaning"
            out.append((name, summary))
        out.sort(key=lambda t: t[0].lower())
        return out

    def _build_dirty_plugins_panel(self) -> None:
        """Render the dirty-plugin list into step 6 (QAC wizards only).

        Packed with ``expand=True`` so the list fills whatever vertical space is
        left between the header and the run-status/Done widgets (which are packed
        ``side="bottom"`` first).  Mouse-wheel scrolling is bound globally so it
        works while the pointer is over any child row, not just the canvas gaps.
        """
        dirty = self._collect_dirty_plugins()
        if not dirty:
            return

        ctk.CTkLabel(
            self._body,
            text=f"Plugins needing cleaning ({len(dirty)}):",
            font=FONT_BOLD, text_color=TEXT_MAIN, anchor="w",
        ).pack(fill="x", padx=4, pady=(0, 4))

        box = ctk.CTkScrollableFrame(self._body, fg_color=BG_DEEP)
        box.pack(fill="both", expand=True, padx=4, pady=(0, 12))

        for name, summary in dirty:
            row = ctk.CTkFrame(box, fg_color="transparent")
            row.pack(fill="x", padx=2, pady=1)
            ctk.CTkLabel(
                row, text=name, font=FONT_BOLD, text_color=TEXT_MAIN,
                anchor="w",
            ).pack(side="top", fill="x")
            ctk.CTkLabel(
                row, text=summary, font=FONT_NORMAL, text_color=TEXT_DIM,
                anchor="w",
            ).pack(side="top", fill="x", padx=(12, 0))

        self._bind_dirty_scroll(box)

    def _bind_dirty_scroll(self, box: "ctk.CTkScrollableFrame") -> None:
        """Make the mouse wheel scroll the dirty-plugin list from anywhere over
        it.  On Tk 8.6 (Linux) the wheel arrives as Button-4/5 which the
        CTkScrollableFrame bind_all doesn't cover; supplement them, scoped to
        when the pointer is actually over the list."""
        from gui.wheel_compat import LEGACY_WHEEL_REDUNDANT
        if LEGACY_WHEEL_REDUNDANT:
            return
        canvas = getattr(box, "_parent_canvas", None)
        if canvas is None:
            return

        def _on_scroll(event):
            try:
                if not box.winfo_exists():
                    return
                sx, sy = box.winfo_rootx(), box.winfo_rooty()
                sw, sh = box.winfo_width(), box.winfo_height()
            except Exception:
                return
            if not (sx <= event.x_root < sx + sw and sy <= event.y_root < sy + sh):
                return
            num = getattr(event, "num", None)
            if num == 4:
                canvas.yview("scroll", -3, "units")
            elif num == 5:
                canvas.yview("scroll", 3, "units")

        root = self.winfo_toplevel()
        self._dirty_scroll_root = root
        root.bind_all("<Button-4>", _on_scroll, add="+")
        root.bind_all("<Button-5>", _on_scroll, add="+")
        # Tear the global handlers down when the wizard is destroyed — a leftover
        # bind_all referencing the dead canvas would fire on every wheel notch in
        # any window sharing this Tk interpreter.
        self.bind("<Destroy>", self._on_dirty_scroll_destroy, add="+")

    def _on_dirty_scroll_destroy(self, event):
        if event.widget is not self:
            return  # ignore child-widget destroys bubbling through
        root = getattr(self, "_dirty_scroll_root", None)
        if root is None:
            return
        for seq in ("<Button-4>", "<Button-5>"):
            try:
                root.unbind_all(seq)
            except Exception:
                pass
        self._dirty_scroll_root = None

    def _show_step_run(self):
        self._clear_body()

        ctk.CTkLabel(
            self._body, text=f"Step 6: {self._wizard_title}",
            font=FONT_BOLD, text_color=TEXT_MAIN,
        ).pack(pady=(0, 12))

        exe = self._exe
        if exe is None:
            ctk.CTkLabel(
                self._body,
                text=self._exe_missing_text,
                font=FONT_NORMAL, text_color="#e06c6c", justify="center",
            ).pack(pady=(0, 16))
            ctk.CTkButton(
                self._body, text="Close", width=120, height=36,
                font=FONT_BOLD,
                fg_color=BG_HEADER, hover_color="#3d3d3d", text_color=TEXT_MAIN,
                command=self._on_close_cb,
            ).pack(side="bottom")
            return

        # Pack the bottom widgets first so they reserve their space; the dirty
        # list (packed last with expand=True) then absorbs everything between
        # the header and the run status.
        self._done_btn = ctk.CTkButton(
            self._body, text="Done", width=120, height=36,
            font=FONT_BOLD,
            fg_color="#2d7a2d", hover_color="#3a9e3a", text_color="white",
            command=self._on_done, state="disabled",
        )
        self._done_btn.pack(side="bottom")

        self._run_status = ctk.CTkLabel(
            self._body, text=f"Launching {self._tool_display_name}\u2026",
            font=FONT_NORMAL, text_color=TEXT_DIM, justify="center", wraplength=460,
        )
        self._run_status.pack(side="bottom", pady=(0, 12))

        if self._qac:
            self._build_dirty_plugins_panel()

        threading.Thread(target=lambda: self._do_run(exe), daemon=True).start()

    def _do_run(self, exe: Path):
        proton_script, env, compat_data = self._get_tool_env()
        if proton_script is None:
            self._set_label(
                "_run_status",
                f"Could not find Proton '{self._proton_name}' — "
                "check that it is installed in Steam.",
                color="#e06c6c",
            )
            return

        game_path = self._game.get_game_path()
        if game_path is None:
            self._set_label("_run_status", "Game path not configured.", color="#e06c6c")
            return

        pfx = compat_data / "pfx"
        data_arg = f'-d:{_to_wine_path(game_path / "Data", pfx)}'

        # xEdit reads the game's Installed Path from the registry — a fresh
        # tool prefix never has it (idempotent, marker-guarded).
        from Utils.bethesda_registry import maybe_register_for_game
        maybe_register_for_game(
            prefix_dir=compat_data,
            proton_script=proton_script,
            env=env,
            game=self._game,
            log_fn=lambda msg: self._log(f"{self._tool_display_name} Wizard: {msg}"),
        )

        # Load order + game INIs: xEdit reads plugins.txt from AppData and
        # fatals when My Games/<Game>/*.ini is missing.
        self._link_plugins_txt(pfx)
        self._link_mygames(pfx)

        # Suppress xEdit's first-run nag dialogs (What's New + developer
        # message) which reappear every time this tool prefix is recreated.
        _seed_xedit_viewsettings(
            self._game, pfx, self._xedit_name,
            log_fn=lambda msg: self._log(f"{self._tool_display_name} Wizard: {msg}"),
        )

        _set_winxp_compat(compat_data, exe, log_fn=self._log)

        name = self._tool_display_name
        self._log(f"{name} Wizard: launching {exe} via Proton with {data_arg}")
        try:
            proc = subprocess.Popen(
                proton_run_command(proton_script, "run", str(exe), data_arg),
                env=env,
                cwd=str(exe.parent),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._set_label(
                "_run_status",
                f"{name} is running.\nClose it when you are done, then click Done.",
                color="#6bc76b",
            )
            self.after(0, lambda: self._done_btn.configure(state="normal"))
            proc.wait()

            shutdown_prefix_wineserver(
                proton_script, compat_data,
                log_fn=lambda m: self._log(f"{name} Wizard: {m}"),
            )

            # xEdit can write the cleaned plugin to a temp and queue the rename to
            # its real name "on shutdown"; the wineserver is now down so any such
            # rename has run.  Finalise any temp that slipped through before the
            # restore/rebuild below.
            _data_dir = game_path / "Data"
            _n = _finalize_xedit_saves(
                _data_dir, log_fn=lambda m: self._log(f"{name} Wizard: {m}"))
            if _n:
                self._log(f"{name} Wizard: finalised {_n} pending xEdit save(s).")

            # Move any edited plugin back into its mod folder while the modindex
            # still knows it — BEFORE the panel refresh rescans staging.  This is
            # the core fix for QAC-cleaned plugins landing in overwrite/ (the
            # rescan would otherwise drop the plugin because QAC consumed the
            # staging copy into a Data-side backup).  Runs here on the worker
            # thread so the UI doesn't hang.
            self._restore_after_xedit()
            self._log(f"{name} Wizard: {name} closed.")

            self._set_label("_run_status", f"{name} finished.", color="#6bc76b")
            self.after(0, self._on_done)
        except Exception as exc:
            self._set_label("_run_status", f"Launch error: {exc}", color="#e06c6c")
            self._log(f"{name} Wizard: launch error: {exc}")


class SSEEditQACWizard(SSEEditWizard):
    """Variant that runs the QuickAutoClean exe for whatever xEdit build the
    game configures (SSEEditQuickAutoClean.exe, FO4EditQuickAutoClean.exe, ...).
    """

    _qac = True
