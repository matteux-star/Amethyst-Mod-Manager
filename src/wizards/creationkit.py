"""
creationkit.py
Wizard for running Bethesda's Creation Kit (CreationKit.exe) for Skyrim SE via
Proton, together with Creation Kit Platform Extended (CKPE).

Workflow
--------
1. Detect CreationKit.exe in the game's root folder (installed via Steam — there
   is no download step for the CK itself).
2. Optionally download Creation Kit Platform Extended from GitHub and install it
   as a managed mod with the rootFolder flag enabled, so it deploys into the
   game root alongside CreationKit.exe (this is where CKPE's winhttp.dll loader
   must live).
3. Deploy the modlist (with a Skip option).
4. User picks the Proton version; CK gets its own isolated prefix
   (prefix_<ProtonName>/ in the game folder), like the other Bethesda tool
   wizards.
5. Run CreationKit.exe via Proton from the game root, after:
     - seeding the game's Installed Path into the prefix registry,
     - symlinking the profile's plugins.txt into the prefix AppData,
     - linking the game prefix's My Games folder (so the game INIs are present),
     - applying the winhttp=native,builtin Wine DLL override to the tool prefix
       so CKPE's loader runs.

Unlike the xEdit wizard, CK is launched from the game root with no -d:<Data>
argument. Plugins the CK creates or edits in Data/ are rescued by the game's
generic restore() on the next deploy (the same path xEdit relies on), so this
wizard adds no CK-specific plugin-rescue logic.
"""

from __future__ import annotations

import json
import subprocess
import threading
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import customtkinter as ctk

if TYPE_CHECKING:
    from Games.base_game import BaseGame

from gui.theme import (
    ACCENT, ACCENT_HOV, BG_DEEP, BG_HEADER, BG_PANEL,
    TEXT_ON_ACCENT,
    TEXT_DIM, TEXT_MAIN,
    FONT_NORMAL, FONT_BOLD,
)

from wizards._proton_prefix import ProtonPrefixStepMixin, shutdown_prefix_wineserver

_EXE_NAME = "CreationKit.exe"
_CKPE_MOD_NAME = "Creation Kit Platform Extended"
_CKPE_GITHUB_API = (
    "https://api.github.com/repos/Perchik71/Creation-Kit-Platform-Extended/releases/latest"
)


def _creationkit_exe_path(game: "BaseGame") -> Path | None:
    root = game.get_game_path()
    if root is None:
        return None
    p = root / _EXE_NAME
    return p if p.is_file() else None


def _ckpe_mod_installed(game: "BaseGame") -> bool:
    """True if a CKPE mod staging folder already exists."""
    try:
        staging = game.get_effective_mod_staging_path()
    except Exception:
        staging = None
    return staging is not None and (staging / _CKPE_MOD_NAME).is_dir()


def _pick_ckpe_asset(assets: list[dict]) -> "tuple[str, str] | None":
    """Pick the normal SSE CKPE archive (not the noavx variant).

    Returns (asset_name, download_url) or None. Prefers an archive whose name
    contains ``sse`` and not ``noavx``; falls back to the first non-noavx
    archive when no ``sse`` token is present.
    """
    from wizards.script_extender import _is_archive

    archives = [
        a for a in assets
        if _is_archive(a.get("name", "")) and "noavx" not in a.get("name", "").lower()
    ]
    if not archives:
        return None
    sse = [a for a in archives if "sse" in a.get("name", "").lower()]
    chosen = (sse or archives)[0]
    return chosen.get("name", ""), chosen.get("browser_download_url", "")


class CreationKitWizard(ProtonPrefixStepMixin, ctk.CTkFrame):
    """Step-by-step wizard to set up and run the Creation Kit (+ CKPE) for
    Skyrim SE."""

    _wizard_title = "Run Creation Kit"

    _tool_exe_name     = _EXE_NAME
    _tool_display_name = "Creation Kit"
    _proton_step_title = "Step 3: Choose Proton Version"
    _exe_missing_text  = (
        f"{_EXE_NAME} was not found in the game folder.\n"
        "Install the Creation Kit from Steam, then reopen this wizard."
    )

    def _proton_next_step(self):
        self._show_step_run()

    def __init__(self, parent, game: "BaseGame", log_fn=None, *, on_close=None, **_kwargs):
        super().__init__(parent, fg_color=BG_DEEP, corner_radius=0)
        self._on_close_cb = on_close or (lambda: None)
        self._game        = game
        self._log         = log_fn or (lambda msg: None)
        self._exe         = _creationkit_exe_path(game)
        self._proton_name = ""

        title_bar = ctk.CTkFrame(self, fg_color=BG_HEADER, corner_radius=0, height=40)
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)
        ctk.CTkLabel(
            title_bar,
            text=f"{self._wizard_title} — {game.name}",
            font=FONT_BOLD, text_color=TEXT_MAIN, anchor="w",
        ).pack(side="left", padx=12, pady=8)
        ctk.CTkButton(
            title_bar, text="✕", width=32, height=32, font=FONT_BOLD,
            fg_color="transparent", hover_color=BG_PANEL, text_color=TEXT_MAIN,
            command=self._on_close_cb,
        ).pack(side="right", padx=4, pady=4)

        self._body = ctk.CTkFrame(self, fg_color=BG_DEEP)
        self._body.pack(fill="both", expand=True, padx=20, pady=20)

        self._show_step_detect()

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

    def _on_done(self):
        try:
            topbar = self.winfo_toplevel()._topbar
        except Exception:
            topbar = None
        self._on_close_cb()
        if topbar is not None:
            try:
                topbar.after(0, topbar._reload_mod_panel)
            except Exception:
                pass

    def _close_button(self):
        ctk.CTkButton(
            self._body, text="Close", width=120, height=36,
            font=FONT_BOLD,
            fg_color=BG_HEADER, hover_color="#3d3d3d", text_color=TEXT_MAIN,
            command=self._on_close_cb,
        ).pack(side="bottom")

    # ------------------------------------------------------------------
    # Step 1 — Detect CreationKit.exe
    # ------------------------------------------------------------------

    def _show_step_detect(self):
        self._clear_body()

        ctk.CTkLabel(
            self._body, text="Step 1: Locate Creation Kit",
            font=FONT_BOLD, text_color=TEXT_MAIN,
        ).pack(pady=(0, 12))

        if self._exe is None:
            ctk.CTkLabel(
                self._body,
                text=(
                    f"{_EXE_NAME} was not found in the game folder.\n\n"
                    "The Creation Kit is installed through Steam:\n"
                    "Skyrim Special Edition → ⚙ → Manage → Creation Kit.\n\n"
                    "Install it, then reopen this wizard."
                ),
                font=FONT_NORMAL, text_color="#e06c6c", justify="center", wraplength=460,
            ).pack(pady=(0, 16))
            self._close_button()
            return

        ctk.CTkLabel(
            self._body,
            text=f"Found {_EXE_NAME} in the game folder.",
            font=FONT_NORMAL, text_color="#6bc76b", justify="center", wraplength=460,
        ).pack(pady=(0, 16))

        ctk.CTkButton(
            self._body, text="Next →", width=120, height=36,
            font=FONT_BOLD,
            fg_color=ACCENT, hover_color=ACCENT_HOV, text_color=TEXT_ON_ACCENT,
            command=self._show_step_ckpe,
        ).pack(side="bottom")

    # ------------------------------------------------------------------
    # Step 2 — Install / update Creation Kit Platform Extended
    # ------------------------------------------------------------------

    def _show_step_ckpe(self):
        self._clear_body()

        ctk.CTkLabel(
            self._body, text="Step 2: Creation Kit Platform Extended",
            font=FONT_BOLD, text_color=TEXT_MAIN,
        ).pack(pady=(0, 12))

        already = _ckpe_mod_installed(self._game)
        ctk.CTkLabel(
            self._body,
            text=(
                "Creation Kit Platform Extended (CKPE) patches the Creation Kit so it "
                "runs correctly. It is downloaded from GitHub and installed as a mod "
                "with the root flag enabled, so it deploys into the game folder next "
                "to CreationKit.exe.\n\n"
                + ("CKPE already appears to be installed. You can update it or skip."
                   if already else
                   "Click Install to download and add the latest CKPE (SSE build).")
            ),
            font=FONT_NORMAL, text_color=TEXT_DIM, justify="center", wraplength=460,
        ).pack(pady=(0, 12))

        self._ckpe_status = ctk.CTkLabel(
            self._body, text="",
            font=FONT_NORMAL, text_color=TEXT_DIM, justify="center", wraplength=460,
        )
        self._ckpe_status.pack(pady=(0, 12))

        btns = ctk.CTkFrame(self._body, fg_color="transparent")
        btns.pack(side="bottom", pady=(8, 0))

        ctk.CTkButton(
            btns, text="Skip", width=100, height=36,
            font=FONT_NORMAL,
            fg_color=BG_HEADER, hover_color="#3d3d3d", text_color=TEXT_DIM,
            command=self._show_step_deploy,
        ).pack(side="right", padx=(8, 0))

        self._ckpe_btn = ctk.CTkButton(
            btns, text=("Update CKPE" if already else "Install CKPE"), width=160, height=36,
            font=FONT_BOLD,
            fg_color=ACCENT, hover_color=ACCENT_HOV, text_color=TEXT_ON_ACCENT,
            command=self._start_ckpe_install,
        )
        self._ckpe_btn.pack(side="right")

    def _start_ckpe_install(self):
        try:
            self._ckpe_btn.configure(state="disabled")
        except Exception:
            pass
        self._set_label("_ckpe_status", "Contacting GitHub…")
        threading.Thread(target=self._do_ckpe_install, daemon=True).start()

    def _do_ckpe_install(self):
        import tempfile

        from wizards.script_extender import _extract_archive
        from wizards._install_as_mod import register_as_mod, index_installed_mod
        from Utils.ca_bundle import get_ssl_context, download_file

        def _wlog(msg):
            self._log(f"Creation Kit Wizard: {msg}")

        try:
            req = urllib.request.Request(
                _CKPE_GITHUB_API,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "ModManager/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=15, context=get_ssl_context()) as resp:
                data = json.loads(resp.read().decode())

            tag = data.get("tag_name", "unknown")
            picked = _pick_ckpe_asset(data.get("assets", []))
            if picked is None or not picked[1]:
                raise RuntimeError(
                    f"No suitable SSE archive found in the latest CKPE release ({tag})."
                )
            asset_name, url = picked

            _wlog(f"downloading CKPE {tag} ({asset_name}) from {url}")
            self._set_label("_ckpe_status", f"Downloading CKPE {tag}…")

            tmp_dir = Path(tempfile.mkdtemp())
            archive = tmp_dir / asset_name
            try:
                download_file(url, archive)

                # Create the staging mod (meta.ini rootFolder=true + modlist
                # entry + panel refresh), then extract CKPE into it so the
                # winhttp.dll loader sits at the staging root.
                mod_dir = register_as_mod(
                    self._game, _CKPE_MOD_NAME, archive,
                    parent_widget=self, log_fn=_wlog, root_folder=True,
                )

                self._set_label("_ckpe_status", "Extracting CKPE…")
                _wlog(f"extracting {archive.name} → {mod_dir}")
                paths = _extract_archive(archive, mod_dir)
                file_count = len([p for p in paths if p.is_file()])
                _wlog(f"extracted {file_count} file(s).")

                # CKPE scans a CKPEPlugins/ folder at startup and crashes with a
                # null-deref if it is missing (FindFirstFileW "Path not found" →
                # access violation in CreationKit.exe). Ship an empty one in the
                # mod payload so it deploys into the game root with CKPE. The
                # folder needs a file inside it to survive staging/deploy, so
                # drop an empty placeholder .txt.
                placeholder = mod_dir / "CKPEPlugins" / "CKPEPlugins.txt"
                placeholder.parent.mkdir(parents=True, exist_ok=True)
                placeholder.touch(exist_ok=True)
                _wlog("added empty CKPEPlugins/ folder (prevents CKPE startup crash).")

                # build_filemap reads modindex.bin (fast path), so the deploy
                # step won't see the files we just extracted unless the index
                # knows about them — index the mod now or nothing reaches the
                # game root.
                index_installed_mod(self._game, _CKPE_MOD_NAME, log_fn=_wlog)
            finally:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)

            self._set_label(
                "_ckpe_status",
                f"CKPE {tag} installed as a mod (root flag enabled).",
                color="#6bc76b",
            )
            self._safe_after(500, self._show_step_deploy)

        except Exception as exc:
            self._set_label("_ckpe_status", f"CKPE install error: {exc}", color="#e06c6c")
            _wlog(f"CKPE install error: {exc}")
            def _reenable():
                try:
                    self._ckpe_btn.configure(state="normal")
                except Exception:
                    pass
            self._safe_after(0, _reenable)

    # ------------------------------------------------------------------
    # Step 3 — Deploy modlist
    # ------------------------------------------------------------------

    def _show_step_deploy(self):
        self._clear_body()

        ctk.CTkLabel(
            self._body, text="Step 3: Deploy Modlist",
            font=FONT_BOLD, text_color=TEXT_MAIN,
        ).pack(pady=(0, 12))

        self._deploy_status = ctk.CTkLabel(
            self._body, text="Deploying…",
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
            # so root-flagged mods — including CKPE — are deployed into the game
            # root via filemap_root.txt + deploy_root_flagged_mods. The previous
            # hand-rolled sequence rebuilt the filemap without root_folder_mods,
            # so CKPE's files were swept out of the root and never put back.
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
            self._log(f"Creation Kit Wizard: deploy error: {exc}")

    # ------------------------------------------------------------------
    # Step 5 — Run Creation Kit
    # ------------------------------------------------------------------

    def _show_step_run(self):
        self._clear_body()

        ctk.CTkLabel(
            self._body, text=f"Step 4: {self._wizard_title}",
            font=FONT_BOLD, text_color=TEXT_MAIN,
        ).pack(pady=(0, 12))

        exe = self._exe
        if exe is None:
            ctk.CTkLabel(
                self._body,
                text=self._exe_missing_text,
                font=FONT_NORMAL, text_color="#e06c6c", justify="center", wraplength=460,
            ).pack(pady=(0, 16))
            self._close_button()
            return

        self._run_status = ctk.CTkLabel(
            self._body, text="Launching Creation Kit…",
            font=FONT_NORMAL, text_color=TEXT_DIM, justify="center", wraplength=460,
        )
        self._run_status.pack(pady=(0, 12))

        self._done_btn = ctk.CTkButton(
            self._body, text="Done", width=120, height=36,
            font=FONT_BOLD,
            fg_color="#2d7a2d", hover_color="#3a9e3a", text_color="white",
            command=self._on_done, state="disabled",
        )
        self._done_btn.pack(side="bottom")

        threading.Thread(target=lambda: self._do_run(exe), daemon=True).start()

    def _do_run(self, exe: Path):
        from Utils.bethesda_registry import maybe_register_for_game
        from Utils.deploy import apply_wine_dll_overrides
        from Utils.protontricks import (
            install_d3dcompiler_47, install_vcredist, is_dep_installed,
            D3D_DEP_KEY, VCREDIST_DEP_KEY,
        )

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

        # CK reads the game's Installed Path from the registry — a fresh tool
        # prefix never has it (idempotent, marker-guarded).
        maybe_register_for_game(
            prefix_dir=compat_data,
            proton_script=proton_script,
            env=env,
            game=self._game,
            log_fn=lambda msg: self._log(f"Creation Kit Wizard: {msg}"),
        )

        # Install common runtime deps into the tool prefix. CK/CKPE may not need
        # these, but they're cheap to add and rule out missing-DLL failures.
        # Both are idempotent (marked in the prefix's amethyst_deps.json keyed on
        # pfx.parent), so this is a no-op on subsequent runs. steam_id is omitted
        # for d3dcompiler so the protontricks fallback can't target the game
        # prefix instead of this tool prefix.
        _deplog = lambda msg: self._log(f"Creation Kit Wizard: {msg}")
        if not is_dep_installed(pfx, D3D_DEP_KEY):
            self._set_label("_run_status", "Installing d3dcompiler_47…")
            install_d3dcompiler_47("", log_fn=_deplog, prefix_path=pfx)
        if not is_dep_installed(pfx, VCREDIST_DEP_KEY):
            self._set_label("_run_status", "Installing VC++ Redistributable (first run only)…")
            install_vcredist(proton_script, env, log_fn=_deplog, prefix_path=pfx)

        # Load order + game INIs: CK reads plugins.txt from AppData and needs
        # My Games/<Game>/*.ini.
        self._link_plugins_txt(pfx)
        self._link_mygames(pfx)

        # Creation Kit Platform Extended ships a winhttp.dll loader; the prefix
        # must prefer the native DLL or the loader never runs.
        apply_wine_dll_overrides(
            compat_data, {"winhttp": "native,builtin"},
            log_fn=lambda msg: self._log(f"Creation Kit Wizard: {msg}"),
        )

        # CKPE crashes on startup (null-deref) if its CKPEPlugins/ folder is
        # missing from the game root. The CKPE mod ships one (deployed into the
        # root), so prefer that. Only create the folder directly as a fallback
        # for users who installed CKPE manually into the game folder.
        ckpe_plugins = game_path / "CKPEPlugins"
        if ckpe_plugins.is_dir():
            self._log("Creation Kit Wizard: CKPEPlugins/ present in game root (from CKPE mod).")
        else:
            try:
                ckpe_plugins.mkdir(exist_ok=True)
                self._log("Creation Kit Wizard: CKPEPlugins/ missing — created it in the game root (manual CKPE install fallback).")
            except OSError as exc:
                self._log(f"Creation Kit Wizard: could not create CKPEPlugins/: {exc}")

        self._log(f"Creation Kit Wizard: launching {exe} via Proton from {game_path}")
        try:
            proc = subprocess.Popen(
                ["python3", str(proton_script), "run", str(exe)],
                env=env,
                cwd=str(game_path),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._set_label(
                "_run_status",
                "Creation Kit is running.\nClose it when you are done, then click Done.",
                color="#6bc76b",
            )
            self.after(0, lambda: self._done_btn.configure(state="normal"))
            proc.wait()

            shutdown_prefix_wineserver(
                proton_script, compat_data,
                log_fn=lambda m: self._log(f"Creation Kit Wizard: {m}"),
            )
            self._log("Creation Kit Wizard: Creation Kit closed.")

            self._set_label("_run_status", "Creation Kit finished.", color="#6bc76b")
            self.after(0, self._on_done)
        except Exception as exc:
            self._set_label("_run_status", f"Launch error: {exc}", color="#e06c6c")
            self._log(f"Creation Kit Wizard: launch error: {exc}")
