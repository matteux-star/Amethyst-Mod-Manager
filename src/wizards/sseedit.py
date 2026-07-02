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

import subprocess
from Utils.steam_finder import proton_run_command
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import customtkinter as ctk

from Utils.xdg import open_url
from Utils.portal_filechooser import pick_file
from gui.path_utils import _to_wine_path

# GUI-neutral helpers now live in Utils.xedit_tools (shared with the Qt wizard
# views); re-exported under their original private names for back-compat.
from Utils.xedit_tools import (
    XEDIT_SAVE_TEMP_RE as _XEDIT_SAVE_TEMP_RE,
    collect_dirty_plugins as _collect_dirty_plugins_neutral,
    finalize_xedit_saves as _finalize_xedit_saves,
    flatten_subdirs as _flatten_subdirs,
    restore_after_xedit as _restore_after_xedit_neutral,
    seed_xedit_viewsettings as _seed_xedit_viewsettings,
    set_winxp_compat as _set_winxp_compat,
    xedit_settings_ext as _xedit_settings_ext,
)
from Utils.xedit_tools import applications_dir as _applications_dir

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


def _get_applications_dir(game: "BaseGame", app_dir: str = _APP_DIR) -> Path:
    return _applications_dir(game, app_dir)


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
        """Fully un-deploy the game after xEdit closes so edited plugins land
        back in their mod folders.  Logic lives in
        ``Utils.xedit_tools.restore_after_xedit`` (see its docstring for the
        QAC-overwrite rationale); shared with the Qt wizard."""
        _restore_after_xedit_neutral(
            self._game, self._tool_display_name, log_fn=self._log)

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
        """LOOT-flagged dirty plugins for the QAC list — shared with the Qt
        wizard via ``Utils.xedit_tools.collect_dirty_plugins``."""
        return _collect_dirty_plugins_neutral(self._game)

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
