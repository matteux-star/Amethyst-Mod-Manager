"""
Texture-tool run dialogs/panels: VRAMr, BENDr, ParallaxR.

Extracted from gui/dialogs.py (which re-exports these names for backwards
compatibility). Each picks options / confirms, then runs the corresponding
``wrappers.*`` pipeline in a background thread.
"""

import threading
import tkinter as tk
from pathlib import Path

import customtkinter as ctk

import gui.theme as _theme
from gui.theme import (
    ACCENT,
    ACCENT_HOV,
    BG_DEEP,
    BG_HEADER,
    BG_HOVER,
    BG_OVERLAY_DEEP,
    BG_PANEL,
    BORDER,
    FONT_BOLD,
    FONT_NORMAL,
    FONT_SMALL,
    TEXT_DIM,
    TEXT_MAIN,
    TEXT_ON_ACCENT,
    TEXT_WHITE,
)


# VRAMr preset panel — overlay on plugin panel
# ---------------------------------------------------------------------------
class VRAMrPresetPanel(ctk.CTkFrame):
    """Inline panel overlaying the plugin panel. User picks a preset, clicks Run,
    then the panel hides and VRAMr runs in a background thread."""

    _PRESETS = [
        ("hq",          "High Quality",  "2K / 2K / 1K / 1K  — 4K modlist downscaled to 2K"),
        ("quality",     "Quality",       "2K / 1K / 1K / 1K  — Balance of quality & savings"),
        ("optimum",     "Optimum",       "2K / 1K / 512 / 512 — Good starting point"),
        ("performance", "Performance",   "2K / 512 / 512 / 512 — Big gains, lower close-up"),
        ("vanilla",     "Vanilla",       "512 / 512 / 512 / 512 — Just run the game"),
    ]

    def __init__(self, parent, *, bat_dir: Path, game_data_dir: Path,
                 output_dir: Path, log_fn, on_done=None):
        super().__init__(parent, fg_color=BG_DEEP, corner_radius=0)
        self._bat_dir = bat_dir
        self._game_data_dir = game_data_dir
        self._output_dir = output_dir
        self._log = log_fn
        self._on_done = on_done or (lambda p: None)
        self._preset_var = tk.StringVar(value="optimum")
        self._build()

    def _build(self):
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Title bar
        title_bar = ctk.CTkFrame(self, fg_color=BG_HEADER, corner_radius=0, height=40)
        title_bar.grid(row=0, column=0, sticky="ew")
        title_bar.grid_propagate(False)
        ctk.CTkLabel(
            title_bar, text="VRAMr — Choose Preset",
            font=FONT_BOLD, text_color=TEXT_MAIN, anchor="w",
        ).pack(side="left", padx=12, pady=8)
        ctk.CTkButton(
            title_bar, text="✕", width=32, height=32, font=FONT_BOLD,
            fg_color="transparent", hover_color=BG_HOVER, text_color=TEXT_MAIN,
            command=self._on_close,
        ).pack(side="right", padx=4, pady=4)

        # Body
        body = ctk.CTkFrame(self, fg_color=BG_DEEP, corner_radius=0)
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            body, text="VRAMr Texture Optimiser",
            font=FONT_BOLD, text_color=TEXT_MAIN,
        ).pack(anchor="w", padx=20, pady=(20, 4))
        ctk.CTkLabel(
            body, text="Select an optimisation preset, then click Run.",
            font=FONT_SMALL, text_color=TEXT_DIM,
        ).pack(anchor="w", padx=20, pady=(0, 12))

        frame = ctk.CTkFrame(body, fg_color=BG_PANEL, corner_radius=6)
        frame.pack(fill="x", padx=20, pady=4)
        for key, label, desc in self._PRESETS:
            row = ctk.CTkFrame(frame, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=3)
            ctk.CTkRadioButton(
                row, text=label, variable=self._preset_var, value=key,
                font=FONT_NORMAL, text_color=TEXT_MAIN,
                fg_color=ACCENT, hover_color=ACCENT_HOV, border_color=BORDER,
            ).pack(side="left")
            ctk.CTkLabel(
                row, text=desc,
                font=FONT_SMALL, text_color=TEXT_DIM,
            ).pack(side="left", padx=(12, 0))

        ctk.CTkLabel(
            body, text=f"Output: {self._output_dir}",
            font=FONT_SMALL, text_color=TEXT_DIM, wraplength=480,
        ).pack(anchor="w", padx=20, pady=(12, 4))

        ctk.CTkButton(
            body, text="▶  Run VRAMr", width=160, height=36,
            font=FONT_BOLD,
            fg_color=ACCENT, hover_color=ACCENT_HOV, text_color=TEXT_ON_ACCENT,
            command=self._on_run,
        ).pack(pady=(8, 20))

    def _on_close(self):
        self._on_done(self)

    def _on_run(self):
        preset = self._preset_var.get()
        self._log(f"VRAMr: starting with '{preset}' preset...")
        bat_dir = self._bat_dir
        game_data_dir = self._game_data_dir
        output_dir = self._output_dir
        log_fn = self._log
        app = self.winfo_toplevel()
        if hasattr(app, "_status"):
            app._status.show_log()
        self._on_done(self)

        def _log_safe(msg: str):
            try:
                if hasattr(app, "call_threadsafe"):
                    app.call_threadsafe(lambda m=msg: log_fn(m))
                else:
                    log_fn(msg)
            except Exception:
                pass

        def _worker():
            try:
                from wrappers.vramr import run_vramr
                run_vramr(
                    bat_dir=bat_dir,
                    game_data_dir=game_data_dir,
                    output_dir=output_dir,
                    preset=preset,
                    log_fn=_log_safe,
                )
            except Exception as exc:
                _log_safe(f"VRAMr error: {exc}")

        threading.Thread(target=_worker, daemon=True).start()


# BENDr run dialog
# ---------------------------------------------------------------------------
class _BENDrRunDialog(ctk.CTkToplevel):
    """Modal confirmation dialog that runs the BENDr pipeline in a background thread."""

    def __init__(self, parent, *, bat_dir: Path, game_data_dir: Path,
                 output_dir: Path, log_fn):
        super().__init__(parent, fg_color=BG_OVERLAY_DEEP)
        self.title("BENDr — Normal Map Processor")
        self.geometry("480x260")
        self.resizable(False, False)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._make_modal)

        self._bat_dir = bat_dir
        self._game_data_dir = game_data_dir
        self._output_dir = output_dir
        self._log = log_fn
        self._build()

    def _make_modal(self):
        try:
            self.grab_set()
            self.focus_set()
        except Exception:
            pass

    def _on_close(self):
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

    def _build(self):
        ctk.CTkLabel(
            self, text="BENDr Normal Map Processor",
            font=(_theme.FONT_FAMILY, 16, "bold"), text_color=TEXT_MAIN,
        ).pack(pady=(16, 4))
        ctk.CTkLabel(
            self,
            text=(
                "Processes normal maps and parallax textures:\n"
                "BSA extract → filter → parallax prep → bend normals → BC7 compress"
            ),
            font=(_theme.FONT_FAMILY, 12), text_color=TEXT_DIM, justify="center",
        ).pack(pady=(0, 12))

        ctk.CTkLabel(
            self, text=f"Output: {self._output_dir}",
            font=(_theme.FONT_FAMILY, 11), text_color=TEXT_DIM, wraplength=440,
        ).pack(pady=(4, 12))

        ctk.CTkButton(
            self, text="▶  Run BENDr", width=160, height=36,
            font=(_theme.FONT_FAMILY, 13, "bold"),
            fg_color=ACCENT, hover_color=ACCENT_HOV, text_color=TEXT_WHITE,
            command=self._on_run,
        ).pack(pady=(0, 16))

    def _on_run(self):
        self._log("BENDr: starting pipeline...")

        bat_dir = self._bat_dir
        game_data_dir = self._game_data_dir
        output_dir = self._output_dir
        log_fn = self._log
        app = self.winfo_toplevel().master
        if hasattr(app, "_status"):
            app._status.show_log()
        self._on_close()

        def _log_safe(msg: str):
            try:
                if hasattr(app, "call_threadsafe"):
                    app.call_threadsafe(lambda m=msg: log_fn(m))
                else:
                    log_fn(msg)
            except Exception:
                pass

        def _worker():
            try:
                from wrappers.bendr import run_bendr
                run_bendr(
                    bat_dir=bat_dir,
                    game_data_dir=game_data_dir,
                    output_dir=output_dir,
                    log_fn=_log_safe,
                )
            except Exception as exc:
                _log_safe(f"BENDr error: {exc}")

        threading.Thread(target=_worker, daemon=True).start()


# ParallaxR run dialog
# ---------------------------------------------------------------------------
class _ParallaxRRunDialog(ctk.CTkToplevel):
    """Modal confirmation dialog that runs the ParallaxR pipeline in a background thread."""

    def __init__(self, parent, *, bat_dir: Path, game_data_dir: Path,
                 output_dir: Path, log_fn):
        super().__init__(parent, fg_color=BG_OVERLAY_DEEP)
        self.title("ParallaxR — Parallax Texture Processor")
        self.geometry("480x260")
        self.resizable(False, False)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._make_modal)

        self._bat_dir = bat_dir
        self._game_data_dir = game_data_dir
        self._output_dir = output_dir
        self._log = log_fn
        self._build()

    def _make_modal(self):
        try:
            self.grab_set()
            self.focus_set()
        except Exception:
            pass

    def _on_close(self):
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

    def _build(self):
        ctk.CTkLabel(
            self, text="ParallaxR Parallax Texture Processor",
            font=(_theme.FONT_FAMILY, 16, "bold"), text_color=TEXT_MAIN,
        ).pack(pady=(16, 4))
        ctk.CTkLabel(
            self,
            text=(
                "Processes normal maps and parallax textures:\n"
                "BSA extract → filter pairs → height maps → output QC"
            ),
            font=(_theme.FONT_FAMILY, 12), text_color=TEXT_DIM, justify="center",
        ).pack(pady=(0, 12))

        ctk.CTkLabel(
            self, text=f"Output: {self._output_dir}",
            font=(_theme.FONT_FAMILY, 11), text_color=TEXT_DIM, wraplength=440,
        ).pack(pady=(4, 12))

        ctk.CTkButton(
            self, text="▶  Run ParallaxR", width=160, height=36,
            font=(_theme.FONT_FAMILY, 13, "bold"),
            fg_color=ACCENT, hover_color=ACCENT_HOV, text_color=TEXT_WHITE,
            command=self._on_run,
        ).pack(pady=(0, 16))

    def _on_run(self):
        self._log("ParallaxR: starting pipeline...")

        bat_dir = self._bat_dir
        game_data_dir = self._game_data_dir
        output_dir = self._output_dir
        log_fn = self._log
        app = self.winfo_toplevel().master
        if hasattr(app, "_status"):
            app._status.show_log()
        self._on_close()

        def _log_safe(msg: str):
            try:
                if hasattr(app, "call_threadsafe"):
                    app.call_threadsafe(lambda m=msg: log_fn(m))
                else:
                    log_fn(msg)
            except Exception:
                pass

        def _worker():
            try:
                from wrappers.parallaxr import run_parallaxr
                run_parallaxr(
                    bat_dir=bat_dir,
                    game_data_dir=game_data_dir,
                    output_dir=output_dir,
                    log_fn=_log_safe,
                )
            except Exception as exc:
                _log_safe(f"ParallaxR error: {exc}")

        threading.Thread(target=_worker, daemon=True).start()
