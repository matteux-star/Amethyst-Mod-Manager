"""
Wizard tool-selection dialog.

Shows a list of game-specific helper tools declared via
``BaseGame.wizard_tools``.  Clicking a tool opens its dedicated wizard dialog.
"""

from __future__ import annotations

import importlib
import tkinter as tk
from typing import TYPE_CHECKING

import customtkinter as ctk

if TYPE_CHECKING:
    from Games.base_game import BaseGame, WizardTool

from Utils.plugin_loader import get_all_wizard_tools

from gui.wheel_compat import LEGACY_WHEEL_REDUNDANT
from gui.theme import (
    BG_DEEP,
    BG_PANEL,
    BG_HEADER,
    BG_HOVER,
    ACCENT,
    ACCENT_HOV,
    TEXT_ON_ACCENT,
    TEXT_MAIN,
    TEXT_DIM,
    BORDER,
    FONT_NORMAL,
    FONT_BOLD,
    FONT_SMALL,
)


# ---------------------------------------------------------------------------
# Category grouping
# ---------------------------------------------------------------------------
#
# Tools are grouped under category headers in the picker.  A tool may declare
# its own ``category`` on its WizardTool; if it doesn't, one is inferred from
# its id/label below.  ``CATEGORY_ORDER`` fixes the display order of the
# headers; anything not listed falls under "Other" at the bottom.

CATEGORY_ORDER = [
    "Setup & Installers",
    "Body & Outfits",
    "Animation & Physics",
    "LOD & Textures",
    "RSuite (experimental)",
    "Patchers & Cleanup",
    "Load Order & Config",
    "Other",
]

# Ordered (substring-in-id, category) rules.  First match wins.  ids are the
# stable machine keys (e.g. "run_dyndolod_skyrimse") so these survive label
# wording changes.
_CATEGORY_RULES: list[tuple[tuple[str, ...], str]] = [
    # Body & outfits
    (("bodyslide", "outfitstudio", "outfit_studio"), "Body & Outfits"),
    # Animation & physics
    (("pandora",), "Animation & Physics"),
    # RSuite (experimental) — checked before LOD so these don't fall into it
    (("vramr", "bendr", "parallaxr"), "RSuite (experimental)"),
    # LOD & textures
    (("texgen", "dyndolod", "xlodgen"), "LOD & Textures"),
    # Patchers & cleanup
    #   xEdit ships under many build names (SSEEdit, FO4Edit, FNVEdit, TES5Edit,
    #   SF1Edit, …) whose wizard ids share the "<build>edit_<suffix>" shape, so
    #   match the generic "edit_" infix to catch the whole family — not just
    #   SSEEdit.  Trailing "_" keeps it from matching unrelated ids like
    #   "editor"/"credits".
    (("pgpatcher", "edit_", "eslifier", "skygen", "plugin_audit",
      "script_merger", "gpak"), "Patchers & Cleanup"),
    # Load order & config
    (("wrye_bash", "bethini"), "Load Order & Config"),
    # Setup & installers (script extenders, downgraders, patches, framework installs)
    (("install_se", "install_reshade", "install_bepinex", "install_mgexe",
      "install_mcp", "downgrade", "4gb_patch", "dtkit", "_patch"),
     "Setup & Installers"),
]


def _infer_category(tool: "WizardTool") -> str:
    """Return the display category for *tool* (explicit if set, else inferred)."""
    if getattr(tool, "category", ""):
        return tool.category
    key = (tool.id or "").lower()
    for needles, cat in _CATEGORY_RULES:
        if any(n in key for n in needles):
            return cat
    return "Other"


def _group_by_category(tools: list["WizardTool"]) -> list[tuple[str, list["WizardTool"]]]:
    """Group *tools* into ``[(category, [tools…]), …]`` in CATEGORY_ORDER.

    Tools within a category keep their incoming (alphabetical) order.  Empty
    categories are omitted; unknown categories are appended after the known
    ones, before falling through to "Other".
    """
    buckets: dict[str, list["WizardTool"]] = {}
    for tool in tools:
        buckets.setdefault(_infer_category(tool), []).append(tool)

    order = list(CATEGORY_ORDER)
    for cat in buckets:
        if cat not in order:
            order.insert(len(order) - 1, cat)  # before trailing "Other"

    return [(cat, buckets[cat]) for cat in order if buckets.get(cat)]


def _add_category_header(parent, text: str, padx=0, first=False) -> None:
    """Render a category spacer/header above its group of tool rows."""
    ctk.CTkLabel(
        parent, text=text.upper(),
        font=FONT_SMALL, text_color=ACCENT, anchor="w",
    ).pack(anchor="w", fill="x", padx=padx, pady=((4 if first else 12), 6))


def _add_tool_row(parent, tool: "WizardTool", open_fn, padx=0) -> None:
    """Render a clickable row for a single wizard tool."""
    row = ctk.CTkFrame(parent, fg_color=BG_PANEL, corner_radius=6)
    row.pack(fill="x", pady=(0, 8), padx=padx)

    inner = ctk.CTkFrame(row, fg_color="transparent")
    inner.pack(fill="x", padx=12, pady=10)

    text_frame = ctk.CTkFrame(inner, fg_color="transparent")
    text_frame.pack(side="left", fill="x", expand=True)

    ctk.CTkLabel(
        text_frame, text=tool.label,
        font=FONT_BOLD, text_color=TEXT_MAIN, anchor="w",
    ).pack(anchor="w")

    if tool.description:
        ctk.CTkLabel(
            text_frame, text=tool.description,
            font=FONT_SMALL, text_color=TEXT_DIM, anchor="w",
            wraplength=280,
        ).pack(anchor="w")

    ctk.CTkButton(
        inner, text="Open", width=70, height=30, font=FONT_BOLD,
        fg_color=ACCENT, hover_color=ACCENT_HOV, text_color=TEXT_ON_ACCENT,
        command=lambda t=tool: open_fn(t),
    ).pack(side="right", padx=(8, 0))


def _resolve_dialog_class(dotted_path: str) -> type:
    """Import and return the class referenced by *dotted_path*.

    Example: ``"wizards.fallout_downgrade.FalloutDowngradeWizard"``
    """
    module_path, class_name = dotted_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


class WizardDialog(ctk.CTkToplevel):
    """Modal dialog listing the available wizard tools for a game."""

    def __init__(self, parent, game: "BaseGame", log_fn=None):
        super().__init__(parent, fg_color=BG_DEEP)
        self.title(f"Wizard — {game.name}")
        self.geometry("440x480")
        self.resizable(False, True)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._make_modal)

        self._game = game
        self._log = log_fn or (lambda msg: None)
        self._parent = parent
        self._build()

    # ------------------------------------------------------------------
    # Modal helpers
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build(self):
        header = ctk.CTkFrame(self, fg_color=BG_DEEP)
        header.pack(fill="x", padx=16, pady=(16, 0))

        ctk.CTkLabel(
            header,
            text=f"Wizard — {self._game.name}",
            font=FONT_BOLD,
            text_color=TEXT_MAIN,
        ).pack(pady=(0, 4))

        ctk.CTkLabel(
            header,
            text="Select a helper tool:",
            font=FONT_SMALL,
            text_color=TEXT_DIM,
        ).pack(pady=(0, 8))

        tools = get_all_wizard_tools(self._game)
        if not tools:
            ctk.CTkLabel(
                header,
                text="No tools available for this game.",
                font=FONT_NORMAL,
                text_color=TEXT_DIM,
            ).pack(pady=20)
            return

        # Sort tools alphabetically by label (case-insensitive).
        self._tools = sorted(tools, key=lambda t: (t.label or "").lower())

        body = ctk.CTkScrollableFrame(
            self, fg_color=BG_DEEP, corner_radius=0,
            scrollbar_button_color=BG_HEADER,
            scrollbar_button_hover_color=ACCENT,
        )
        body.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        self._body = body

        self._render_rows("")
        self._bind_scroll(body)

        # Search bar at the bottom.
        search_frame = ctk.CTkFrame(self, fg_color=BG_DEEP)
        search_frame.pack(fill="x", padx=16, pady=(0, 16))
        self._search_var = tk.StringVar()
        search_entry = ctk.CTkEntry(
            search_frame, textvariable=self._search_var,
            placeholder_text="Search tools…",
            font=FONT_NORMAL, fg_color=BG_PANEL, border_color=BORDER,
            text_color=TEXT_MAIN,
        )
        search_entry.pack(fill="x")
        self._search_var.trace_add("write", lambda *_: self._render_rows(self._search_var.get()))

    def _render_rows(self, query: str) -> None:
        """(Re)build the tool rows in the body, filtered by *query*."""
        for child in self._body.winfo_children():
            child.destroy()

        q = query.strip().lower()
        matches = [
            t for t in self._tools
            if not q
            or q in (t.label or "").lower()
            or q in (t.description or "").lower()
        ]

        if not matches:
            ctk.CTkLabel(
                self._body, text="No tools match your search.",
                font=FONT_NORMAL, text_color=TEXT_DIM,
            ).pack(pady=20)
            return

        groups = _group_by_category(matches)
        single_group = len(groups) == 1
        for gi, (category, group_tools) in enumerate(groups):
            if not single_group:
                _add_category_header(self._body, category, first=(gi == 0))
            for tool in group_tools:
                _add_tool_row(self._body, tool, self._open_tool)

    def _bind_scroll(self, scrollable: ctk.CTkScrollableFrame) -> None:
        """Bind mousewheel to the dialog so scrolling works anywhere in the window."""
        canvas = scrollable._parent_canvas

        if not LEGACY_WHEEL_REDUNDANT:
            self.bind("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"), add="+")
            self.bind("<Button-5>", lambda e: canvas.yview_scroll(1, "units"), add="+")
        # On Tk >= 8.7, CTkScrollableFrame's own bind_all("<MouseWheel>") handler
        # already scrolls the canvas (with event.delta=±120 per notch). Binding another
        # MouseWheel here would stack on top, making scroll far too fast.

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _open_tool(self, tool: "WizardTool"):
        """Close this picker and open the tool's dedicated wizard dialog."""
        game = self._game
        log = self._log
        parent = self._parent
        path = tool.dialog_class_path
        extra = dict(tool.extra)
        pre_resolved = extra.pop("_dialog_class", None)

        # Close the picker first
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

        # Resolve and open the tool dialog on the next event-loop tick
        def _launch():
            try:
                cls = pre_resolved if pre_resolved is not None else _resolve_dialog_class(path)
                dlg = cls(parent, game, log, **extra)
                parent.wait_window(dlg)
            except Exception as exc:
                log(f"Wizard error: {exc}")

        parent.after(50, _launch)


class WizardPanel(ctk.CTkFrame):
    """Inline panel for wizard tool selection — overlays the plugin panel while open."""

    def __init__(self, parent, game: "BaseGame", log_fn=None, on_done=None, on_open_tool=None):
        super().__init__(parent, fg_color=BG_DEEP, corner_radius=0)
        self._game = game
        self._log = log_fn or (lambda msg: None)
        self._on_done = on_done or (lambda p: None)
        self._on_open_tool = on_open_tool  # callable(cls, game, log_fn, extra) or None
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
            title_bar, text=f"Wizard — {self._game.name}",
            font=FONT_BOLD, text_color=TEXT_MAIN, anchor="w",
        ).pack(side="left", padx=12, pady=8)
        ctk.CTkButton(
            title_bar, text="✕", width=32, height=32, font=FONT_BOLD,
            fg_color="transparent", hover_color=BG_HOVER, text_color=TEXT_MAIN,
            command=self._on_close,
        ).pack(side="right", padx=4, pady=4)
        ctk.CTkButton(
            title_bar, text="Manage Prefixes…", width=140, height=30,
            font=FONT_NORMAL,
            fg_color=BG_PANEL, hover_color=BG_HOVER, text_color=TEXT_MAIN,
            command=self._open_prefix_manager,
        ).pack(side="right", padx=4, pady=5)

        # Body
        body = ctk.CTkScrollableFrame(
            self, fg_color=BG_DEEP, corner_radius=0,
            scrollbar_button_color=BG_HEADER,
            scrollbar_button_hover_color=ACCENT,
        )
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)
        self._body = body

        self._heading = ctk.CTkLabel(
            body, text="Select a helper tool:",
            font=FONT_SMALL, text_color=TEXT_DIM,
        )
        self._heading.pack(pady=(12, 12), anchor="w", padx=16)

        tools = get_all_wizard_tools(self._game)
        if not tools:
            ctk.CTkLabel(
                body, text="No tools available for this game.",
                font=FONT_NORMAL, text_color=TEXT_DIM,
            ).pack(pady=20)
            return

        # Sort tools alphabetically by label (case-insensitive).
        self._tools = sorted(tools, key=lambda t: (t.label or "").lower())
        self._rows_container = ctk.CTkFrame(body, fg_color="transparent")
        self._rows_container.pack(fill="x")
        self._rows_container.grid_columnconfigure(0, weight=1)

        canvas = body._parent_canvas

        def _scroll_up(e):   canvas.yview_scroll(-1, "units")
        def _scroll_down(e): canvas.yview_scroll(1, "units")

        self._scroll_up = _scroll_up
        self._scroll_down = _scroll_down

        self._render_rows("")

        self._bind_tree(body)
        self._bind_tree(canvas)

        # Search bar at the bottom.
        self.grid_rowconfigure(2, weight=0)
        search_frame = ctk.CTkFrame(self, fg_color=BG_HEADER, corner_radius=0)
        search_frame.grid(row=2, column=0, sticky="ew")
        self._search_var = tk.StringVar()
        search_entry = ctk.CTkEntry(
            search_frame, textvariable=self._search_var,
            placeholder_text="Search tools…",
            font=FONT_NORMAL, fg_color=BG_PANEL, border_color=BORDER,
            text_color=TEXT_MAIN,
        )
        search_entry.pack(fill="x", padx=12, pady=8)
        self._search_var.trace_add("write", lambda *_: self._render_rows(self._search_var.get()))

    def _bind_tree(self, widget):
        if not LEGACY_WHEEL_REDUNDANT:
            widget.bind("<Button-4>", self._scroll_up, add="+")
            widget.bind("<Button-5>", self._scroll_down, add="+")
        for child in widget.winfo_children():
            self._bind_tree(child)

    def _render_rows(self, query: str) -> None:
        """(Re)build the tool rows in the container, filtered by *query*."""
        for child in self._rows_container.winfo_children():
            child.destroy()

        q = query.strip().lower()
        matches = [
            t for t in self._tools
            if not q
            or q in (t.label or "").lower()
            or q in (t.description or "").lower()
        ]

        if not matches:
            ctk.CTkLabel(
                self._rows_container, text="No tools match your search.",
                font=FONT_NORMAL, text_color=TEXT_DIM,
            ).pack(pady=20)
            return

        groups = _group_by_category(matches)
        single_group = len(groups) == 1
        for gi, (category, group_tools) in enumerate(groups):
            if not single_group:
                _add_category_header(self._rows_container, category, padx=16, first=(gi == 0))
            for tool in group_tools:
                _add_tool_row(self._rows_container, tool, self._open_tool, padx=16)

        if not LEGACY_WHEEL_REDUNDANT:
            self._bind_tree(self._rows_container)

    def _open_tool(self, tool: "WizardTool"):
        """Close the panel and open the tool's dedicated wizard."""
        game = self._game
        log = self._log
        path = tool.dialog_class_path
        extra = dict(tool.extra)
        pre_resolved = extra.pop("_dialog_class", None)
        on_open_tool = self._on_open_tool

        self._on_done(self)

        def _launch():
            try:
                cls = pre_resolved if pre_resolved is not None else _resolve_dialog_class(path)
                if on_open_tool is not None:
                    on_open_tool(cls, game, log, extra)
                else:
                    toplevel = self.winfo_toplevel()
                    dlg = cls(toplevel, game, log, **extra)
                    toplevel.wait_window(dlg)
            except Exception as exc:
                log(f"Wizard error: {exc}")

        self.after(50, _launch)

    def _open_prefix_manager(self):
        """Close this panel and open the tool-prefix manager overlay."""
        toplevel = self.winfo_toplevel()
        self._on_done(self)

        def _launch():
            try:
                if hasattr(toplevel, "show_prefix_manager_panel"):
                    toplevel.show_prefix_manager_panel()
            except Exception as exc:
                self._log(f"Prefix manager error: {exc}")

        self.after(50, _launch)

    def _on_close(self):
        self._on_done(self)
