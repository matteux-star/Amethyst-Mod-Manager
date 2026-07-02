"""
Mewgenics deploy/launch dialogs and inline overlay panels.

Extracted from gui/dialogs.py (which re-exports these names for backwards
compatibility). Lets the user choose a deploy method (Steam launch command
vs. repack) and shows the generated ``-modpaths`` launch string with a copy
button.
"""

import tkinter as tk

import customtkinter as ctk

import gui.theme as _theme
from gui.theme import (
    ACCENT,
    ACCENT_HOV,
    BG_DEEP,
    BG_HEADER,
    BG_HOVER,
    BG_PANEL,
    BG_ROW,
    BORDER,
    TEXT_DIM,
    TEXT_MAIN,
    TEXT_ON_ACCENT,
    font_sized_px,
    scaled,
)


class _MewgenicsDeployChoiceDialog(ctk.CTkToplevel):
    """Thin modal wrapper around MewgenicsDeployChoicePanel.

    Callers access ``result`` (``"steam"`` | ``"repack"`` | ``None``).
    """

    def __init__(self, parent):
        super().__init__(parent, fg_color=BG_DEEP)
        self.title("Mewgenics — Deploy method")
        self.geometry("420x220")
        self.resizable(False, False)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.after(100, self._make_modal)

        self.result: str | None = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        def _on_choice(choice):
            self.result = choice
            self._on_cancel()

        panel = MewgenicsDeployChoicePanel(self, on_choice=_on_choice)
        panel.grid(row=0, column=0, sticky="nsew")

    def _make_modal(self):
        try:
            self.grab_set()
            self.focus_set()
        except Exception:
            pass

    def _on_cancel(self):
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()


class _MewgenicsLaunchCommandDialog(ctk.CTkToplevel):
    """Thin non-modal wrapper around MewgenicsLaunchCommandPanel."""

    def __init__(self, parent, launch_string: str, modpaths_file=None):
        super().__init__(parent, fg_color=BG_DEEP)
        self.title("Mewgenics — Steam / Lutris launch command")
        self.geometry("560x310")
        self.resizable(True, True)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        panel = MewgenicsLaunchCommandPanel(
            self,
            launch_string=launch_string,
            modpaths_file=modpaths_file,
            on_close=self.destroy,
        )
        panel.grid(row=0, column=0, sticky="nsew")


class MewgenicsDeployChoicePanel(tk.Frame):
    """Inline overlay panel: choose Steam launch command or repack modded files.

    Place this over the mod-list container with::

        panel.place(relx=0, rely=0, relwidth=1, relheight=1)

    ``on_choice(result)`` is called with ``"steam"``, ``"repack"``, or ``None``
    (cancel) and the caller is responsible for destroying the panel.
    """

    def __init__(self, parent, on_choice):
        super().__init__(parent, bg=BG_DEEP)
        self._on_choice = on_choice
        self._build()

    def _build(self):
        # Centred inner card
        card = tk.Frame(self, bg=BG_PANEL, bd=0, highlightthickness=1,
                        highlightbackground=BORDER, highlightcolor=BORDER)
        card.place(relx=0.5, rely=0.5, anchor="center")

        # Title bar
        title_bar = tk.Frame(card, bg=BG_HEADER, height=scaled(42))
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)
        tk.Label(
            title_bar, text="Mewgenics — Deploy method",
            font=font_sized_px(_theme.FONT_FAMILY, 13, "bold"),
            fg=TEXT_MAIN, bg=BG_HEADER, anchor="w",
        ).pack(side="left", padx=scaled(14), pady=scaled(8))
        tk.Button(
            title_bar, text="✕",
            bg=BG_HEADER, fg=TEXT_DIM, activebackground=BG_HOVER,
            activeforeground=TEXT_MAIN, relief="flat", bd=0,
            highlightthickness=0, cursor="hand2",
            font=font_sized_px(_theme.FONT_FAMILY, 12),
            command=lambda: self._on_choice(None),
        ).pack(side="right", padx=scaled(8))

        body = tk.Frame(card, bg=BG_PANEL)
        body.pack(fill="both", padx=scaled(16), pady=scaled(12))

        _lbl_font  = font_sized_px(_theme.FONT_FAMILY, 12)
        _desc_font = font_sized_px(_theme.FONT_FAMILY, 10)

        # --- Steam launch command button ---
        ctk.CTkButton(
            body, text="Steam launch command  (Safer / Recommended)",
            font=_lbl_font, fg_color=BG_HEADER, hover_color=BG_HOVER,
            text_color=TEXT_MAIN, anchor="w",
            command=lambda: self._on_choice("steam"),
        ).pack(fill="x", pady=(0, scaled(2)))
        tk.Label(
            body,
            text="Generates a launch script for Steam. Set it once in Launch Options (no repack).",
            font=_desc_font, fg=TEXT_DIM, bg=BG_PANEL, anchor="w",
            wraplength=scaled(420),
        ).pack(fill="x", padx=scaled(4), pady=(0, scaled(10)))

        # --- Repack button ---
        ctk.CTkButton(
            body, text="Repack gpak  (No command needed / not recommended)",
            font=_lbl_font, fg_color=BG_HEADER, hover_color=BG_HOVER,
            text_color=TEXT_MAIN, anchor="w",
            command=lambda: self._on_choice("repack"),
        ).pack(fill="x", pady=(0, scaled(2)))
        tk.Label(
            body,
            text="Unpack resources.gpak, merge mods, repack.",
            font=_desc_font, fg=TEXT_DIM, bg=BG_PANEL, anchor="w",
        ).pack(fill="x", padx=scaled(4), pady=(0, scaled(4)))


class MewgenicsLaunchCommandPanel(tk.Frame):
    """Inline overlay panel: shows the -modpaths launch string with copy button.

    Place over the mod-list container with::

        panel.place(relx=0, rely=0, relwidth=1, relheight=1)

    ``on_close()`` is called when the user clicks Close; caller destroys panel.
    """

    def __init__(self, parent, launch_string: str, modpaths_file=None, on_close=None):
        super().__init__(parent, bg=BG_DEEP)
        self._launch_string = launch_string
        self._modpaths_file = modpaths_file
        self._on_close = on_close or (lambda: None)
        self._build()

    def _build(self):
        card = tk.Frame(self, bg=BG_PANEL, bd=0, highlightthickness=1,
                        highlightbackground=BORDER, highlightcolor=BORDER)
        card.place(relx=0.5, rely=0.5, anchor="center")

        # Title bar
        title_bar = tk.Frame(card, bg=BG_HEADER, height=scaled(42))
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)
        tk.Label(
            title_bar, text="Mewgenics — Steam / Lutris launch command",
            font=font_sized_px(_theme.FONT_FAMILY, 13, "bold"),
            fg=TEXT_MAIN, bg=BG_HEADER, anchor="w",
        ).pack(side="left", padx=scaled(14), pady=scaled(8))
        tk.Button(
            title_bar, text="✕",
            bg=BG_HEADER, fg=TEXT_DIM, activebackground=BG_HOVER,
            activeforeground=TEXT_MAIN, relief="flat", bd=0,
            highlightthickness=0, cursor="hand2",
            font=font_sized_px(_theme.FONT_FAMILY, 12),
            command=self._on_close,
        ).pack(side="right", padx=scaled(8))

        body = tk.Frame(card, bg=BG_PANEL)
        body.pack(fill="both", padx=scaled(16), pady=(scaled(10), 0))

        _lbl_font  = font_sized_px(_theme.FONT_FAMILY, 11)
        _desc_font = font_sized_px(_theme.FONT_FAMILY, 10)
        _mono_font = font_sized_px("Consolas", 11)

        tk.Label(
            body,
            text="Paste this into Steam Launch Options (Properties → General):",
            font=_lbl_font, fg=TEXT_MAIN, bg=BG_PANEL, anchor="w",
            wraplength=scaled(500),
        ).pack(fill="x", pady=(0, scaled(6)))

        # Monospace textbox
        txt_frame = tk.Frame(body, bg=BG_ROW, bd=1, relief="flat",
                             highlightthickness=1, highlightbackground=BORDER)
        txt_frame.pack(fill="x", pady=(0, scaled(8)))
        txt = tk.Text(
            txt_frame, font=_mono_font, bg=BG_ROW, fg=TEXT_MAIN,
            insertbackground=TEXT_MAIN, relief="flat", bd=0,
            wrap="word", height=4, width=scaled(52),
        )
        txt.pack(fill="both", padx=scaled(6), pady=scaled(6))
        txt.insert("1.0", self._launch_string)
        txt.configure(state="disabled")

        if self._modpaths_file is not None:
            tk.Label(
                body,
                text=(
                    f"Script written to:\n{self._modpaths_file}"
                    "\n\nUpdate this whenever you change your mod list."
                ),
                font=_desc_font, fg=TEXT_DIM, bg=BG_PANEL, anchor="w",
                justify="left", wraplength=scaled(500),
            ).pack(fill="x", pady=(0, scaled(8)))

        # Button bar
        sep = tk.Frame(card, bg=BORDER, height=1)
        sep.pack(fill="x")
        bar = tk.Frame(card, bg=BG_HEADER, height=scaled(48))
        bar.pack(fill="x")
        bar.pack_propagate(False)

        ctk.CTkButton(
            bar, text="Copy to clipboard",
            width=140, height=30,
            font=font_sized_px(_theme.FONT_FAMILY, 11),
            fg_color=ACCENT, hover_color=ACCENT_HOV, text_color=TEXT_ON_ACCENT,
            command=self._copy,
        ).pack(side="right", padx=(scaled(4), scaled(10)), pady=scaled(8))
        ctk.CTkButton(
            bar, text="Close",
            width=80, height=30,
            font=font_sized_px(_theme.FONT_FAMILY, 11),
            fg_color=BG_PANEL, hover_color=BG_HOVER, text_color=TEXT_MAIN,
            command=self._on_close,
        ).pack(side="right", padx=scaled(4), pady=scaled(8))

    def _copy(self):
        try:
            self.clipboard_clear()
            self.clipboard_append(self._launch_string)
            self.update_idletasks()
        except Exception:
            pass
