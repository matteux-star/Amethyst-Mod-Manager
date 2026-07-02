"""
Disable-plugins dialog/panel.

Extracted from gui/dialogs.py (which re-exports these names for backwards
compatibility). Lets the user pick which plugins to disable before a tool
run / deploy.
"""

import tkinter as tk

import customtkinter as ctk

from gui.theme import (
    ACCENT,
    ACCENT_HOV,
    BG_DEEP,
    BG_HEADER,
    BG_HOVER,
    BG_PANEL,
    BORDER,
    FONT_BOLD,
    FONT_NORMAL,
    FONT_SMALL,
    TEXT_DIM,
    TEXT_MAIN,
    TEXT_ON_ACCENT,
)


class _DisablePluginsDialog(ctk.CTkToplevel):
    """Thin modal wrapper around DisablePluginsPanel.

    Callers access ``result`` (set[str] | None).
    """

    def __init__(self, parent, mod_name: str,
                 plugin_names: list[str], disabled: set[str]):
        super().__init__(parent, fg_color=BG_DEEP)
        self.title(f"Disable Plugins — {mod_name}")
        self.resizable(False, True)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._make_modal)

        self.result: set[str] | None = None

        h = min(500, max(200, 80 + len(plugin_names) * 32 + 60 + 52))
        w = 400
        self.update_idletasks()
        try:
            x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
            y = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
            self.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            self.geometry(f"{w}x{h}")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        def _on_done(panel):
            self.result = panel.result
            self._on_close()

        panel = DisablePluginsPanel(
            self,
            mod_name=mod_name,
            plugin_names=plugin_names,
            disabled=disabled,
            on_done=_on_done,
        )
        panel.grid(row=0, column=0, sticky="nsew")

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


# ---------------------------------------------------------------------------
# DisablePluginsPanel — inline overlay version of _DisablePluginsDialog
# ---------------------------------------------------------------------------

class DisablePluginsPanel(ctk.CTkFrame):
    """
    Inline panel version of _DisablePluginsDialog. Overlays _plugin_panel_container.
    result: set[str] of plugin names to disable, or None if cancelled.
    """

    def __init__(self, parent, mod_name: str,
                 plugin_names: list[str], disabled: set[str],
                 on_done=None):
        super().__init__(parent, fg_color=BG_DEEP, corner_radius=0)
        self.result: set[str] | None = None
        self._plugin_names = plugin_names
        self._disabled_lower = {n.lower() for n in disabled}
        self._on_done = on_done or (lambda p: None)
        self._vars: list[tuple[tk.BooleanVar, str]] = []

        # Title bar
        title_bar = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=0, height=36)
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)
        ctk.CTkLabel(
            title_bar, text=f"Disable Plugins \u2014 {mod_name}",
            font=FONT_BOLD, text_color=TEXT_MAIN, anchor="w",
        ).pack(side="left", padx=12)
        ctk.CTkButton(
            title_bar, text="\u2715", width=32, height=32, font=FONT_BOLD,
            fg_color=BG_PANEL, hover_color=BG_HOVER, text_color=TEXT_MAIN,
            command=self._on_cancel,
        ).pack(side="right", padx=4)
        ctk.CTkFrame(self, fg_color=BORDER, height=1, corner_radius=0).pack(fill="x")

        self._build()

    def _build(self):
        ctk.CTkLabel(
            self,
            text="Checked plugins are enabled and will appear in plugins.txt.\n"
                 "Uncheck a plugin to exclude it.",
            font=FONT_SMALL,
            text_color=TEXT_DIM,
            anchor="w",
            justify="left",
        ).pack(anchor="w", padx=16, pady=(12, 6))

        scroll = ctk.CTkScrollableFrame(self, fg_color=BG_PANEL, corner_radius=6)
        scroll.pack(fill="both", expand=True, padx=12, pady=(0, 4))
        scroll.grid_columnconfigure(0, weight=1)

        for i, name in enumerate(self._plugin_names):
            var = tk.BooleanVar(value=name.lower() not in self._disabled_lower)
            self._vars.append((var, name))
            ctk.CTkCheckBox(
                scroll,
                text=name,
                variable=var,
                font=FONT_NORMAL,
                text_color=TEXT_MAIN,
                fg_color=ACCENT,
                hover_color=ACCENT_HOV,
                checkmark_color="white",
                border_color=BORDER,
            ).grid(row=i, column=0, sticky="w", padx=8, pady=3)

        helper = ctk.CTkFrame(self, fg_color="transparent")
        helper.pack(fill="x", padx=12, pady=(0, 4))
        ctk.CTkButton(
            helper, text="Enable All", width=90, height=24, font=FONT_SMALL,
            fg_color=BG_HEADER, hover_color=BG_HOVER, text_color=TEXT_MAIN,
            command=lambda: [v.set(True) for v, _ in self._vars],
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            helper, text="Disable All", width=90, height=24, font=FONT_SMALL,
            fg_color=BG_HEADER, hover_color=BG_HOVER, text_color=TEXT_MAIN,
            command=lambda: [v.set(False) for v, _ in self._vars],
        ).pack(side="left")

        bar = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=0, height=52)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        ctk.CTkFrame(bar, fg_color=BORDER, height=1, corner_radius=0).pack(
            side="top", fill="x"
        )
        ctk.CTkButton(
            bar, text="Cancel", width=80, height=28, font=FONT_NORMAL,
            fg_color=BG_HEADER, hover_color=BG_HOVER, text_color=TEXT_MAIN,
            command=self._on_cancel,
        ).pack(side="right", padx=(4, 12), pady=12)
        ctk.CTkButton(
            bar, text="Save", width=80, height=28, font=FONT_BOLD,
            fg_color=ACCENT, hover_color=ACCENT_HOV, text_color=TEXT_ON_ACCENT,
            command=self._on_ok,
        ).pack(side="right", padx=4, pady=12)

    def _on_ok(self):
        self.result = {name for var, name in self._vars if not var.get()}
        self._on_done(self)

    def _on_cancel(self):
        self._on_done(self)

