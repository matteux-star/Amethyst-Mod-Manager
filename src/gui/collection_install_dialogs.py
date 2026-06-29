"""
Collection install/continue/update overlay dialogs.

Extracted from gui/dialogs.py (which re-exports these names for backwards
compatibility). These are tk.Frame overlays shown by collections_dialog.py
during collection install: choosing an install mode, continuing a partial
install, and reviewing updates.
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
    BG_ROW,
    BORDER,
    BTN_DANGER_ALT,
    BTN_DANGER_ALT_HOV,
    BTN_INFO_DEEP,
    BTN_INFO_DEEP_HOV,
    BTN_SUCCESS,
    BTN_SUCCESS_HOV,
    BTN_WARN_ORANGE,
    BTN_WARN_ORANGE_HOV,
    FONT_BOLD,
    FONT_NORMAL,
    TEXT_DIM,
    TEXT_MAIN,
    TEXT_ON_ACCENT,
    TEXT_WHITE,
    TK_FONT_BOLD,
    TK_FONT_NORMAL,
    TK_FONT_SMALL,
    scaled,
)


class CollectionInstallModeDialog(tk.Frame):
    """Overlay panel that asks how to install a collection.

    Placed over the mod list panel with place(relx=0, rely=0, relwidth=1, relheight=1).
    Calls on_done(result) when finished, where result is one of:
      ("new", None, False, False)                              — create a new profile
      ("append", profile_name, overwrite_existing, skip_existing)  — append into existing profile
      None                                                     — cancelled
    """

    def __init__(self, parent, existing_profiles: list[str], on_done, force_new_profile: bool = False):
        super().__init__(parent, bg=BG_DEEP)
        self._on_done = on_done
        self._existing_profiles = existing_profiles
        self._force_new_profile = force_new_profile

        self._mode_var = tk.StringVar(value="new")
        self._overwrite_var = tk.BooleanVar(value=False)
        self._skip_existing_var = tk.BooleanVar(value=False)
        self._profile_var = tk.StringVar(
            value=existing_profiles[0] if existing_profiles else ""
        )

        self._build()

    def _build(self):
        # Full-size container so we can centre the card
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Centred card
        card = tk.Frame(self, bg=BG_PANEL, bd=0, highlightthickness=1,
                        highlightbackground=BORDER)
        card.grid(row=0, column=0)
        card.grid_columnconfigure(0, weight=1)

        row = 0

        # Header bar
        header = tk.Frame(card, bg=BG_HEADER, height=scaled(42))
        header.grid(row=row, column=0, sticky="ew")
        header.grid_propagate(False)
        tk.Label(
            header, text="Install Collection",
            font=TK_FONT_BOLD, fg=TEXT_MAIN, bg=BG_HEADER,
        ).pack(side="left", padx=12, pady=8)
        row += 1

        # Separator
        tk.Frame(card, bg=BORDER, height=1).grid(row=row, column=0, sticky="ew")
        row += 1

        # Body
        body = tk.Frame(card, bg=BG_PANEL)
        body.grid(row=row, column=0, sticky="ew", padx=24, pady=(16, 8))
        body.grid_columnconfigure(0, weight=1)
        row += 1

        tk.Label(
            body, text="How would you like to install this collection?",
            font=TK_FONT_BOLD, fg=TEXT_MAIN, bg=BG_PANEL, anchor="center", justify="center",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 14))

        ctk.CTkRadioButton(
            body, text="Create a new profile",
            variable=self._mode_var, value="new",
            font=FONT_NORMAL, text_color=TEXT_MAIN,
            fg_color=ACCENT, hover_color=ACCENT_HOV, border_color=BORDER,
            command=self._on_mode_change,
        ).grid(row=1, column=0, sticky="w", pady=(0, 6))

        if self._force_new_profile:
            tk.Label(
                body,
                text="This collection requires a new profile and cannot be\nappended to an existing one.",
                font=TK_FONT_SMALL,
                fg=TEXT_DIM, bg=BG_PANEL, anchor="w", justify="left",
            ).grid(row=2, column=0, sticky="w", pady=(0, 8))
        else:
            ctk.CTkRadioButton(
                body, text="Append to existing profile",
                variable=self._mode_var, value="append",
                font=FONT_NORMAL, text_color=TEXT_MAIN,
                fg_color=ACCENT, hover_color=ACCENT_HOV, border_color=BORDER,
                command=self._on_mode_change,
            ).grid(row=2, column=0, sticky="w", pady=(0, 8))

        if not self._force_new_profile:
            self._profile_menu = ctk.CTkOptionMenu(
                body, values=self._existing_profiles or ["(no profiles)"],
                variable=self._profile_var,
                font=FONT_NORMAL, text_color=TEXT_MAIN,
                fg_color=BG_DEEP, button_color=BG_HEADER, button_hover_color=BG_HOVER,
                dropdown_fg_color=BG_PANEL, dropdown_text_color=TEXT_MAIN,
                dropdown_hover_color=BG_HOVER,
                state="disabled", width=280,
            )
            self._profile_menu.grid(row=3, column=0, sticky="w", padx=(16, 0), pady=(0, 6))

            self._overwrite_cb = ctk.CTkCheckBox(
                body, text="Overwrite existing mods",
                variable=self._overwrite_var,
                font=FONT_NORMAL, text_color=TEXT_DIM,
                fg_color=ACCENT, hover_color=ACCENT_HOV, border_color=BORDER,
                checkmark_color="white",
                state="disabled",
            )
            self._overwrite_cb.grid(row=4, column=0, sticky="w", padx=(16, 0), pady=(0, 4))

            self._skip_existing_cb = ctk.CTkCheckBox(
                body, text="Skip already installed mods",
                variable=self._skip_existing_var,
                font=FONT_NORMAL, text_color=TEXT_DIM,
                fg_color=ACCENT, hover_color=ACCENT_HOV, border_color=BORDER,
                checkmark_color="white",
                state="disabled",
            )
            self._skip_existing_cb.grid(row=5, column=0, sticky="w", padx=(16, 0), pady=(0, 4))

        # Separator before buttons
        tk.Frame(card, bg=BORDER, height=1).grid(row=row, column=0, sticky="ew")
        row += 1

        # Button bar
        bar = tk.Frame(card, bg=BG_HEADER, height=scaled(44))
        bar.grid(row=row, column=0, sticky="ew")
        bar.grid_propagate(False)
        ctk.CTkButton(
            bar, text="Cancel", width=80, height=28, font=FONT_NORMAL,
            fg_color=BG_DEEP, hover_color=BG_HOVER, text_color=TEXT_MAIN,
            command=self._on_cancel,
        ).pack(side="right", padx=(4, 12), pady=8)
        ctk.CTkButton(
            bar, text="Install", width=80, height=28, font=FONT_BOLD,
            fg_color=ACCENT, hover_color=ACCENT_HOV, text_color=TEXT_ON_ACCENT,
            command=self._on_ok,
        ).pack(side="right", padx=4, pady=8)

    def _on_mode_change(self):
        is_append = self._mode_var.get() == "append"
        state = "normal" if is_append else "disabled"
        if hasattr(self, "_profile_menu"):
            self._profile_menu.configure(state=state)
        if hasattr(self, "_overwrite_cb"):
            self._overwrite_cb.configure(
                state=state,
                text_color=TEXT_MAIN if is_append else TEXT_DIM,
            )
        if hasattr(self, "_skip_existing_cb"):
            self._skip_existing_cb.configure(
                state=state,
                text_color=TEXT_MAIN if is_append else TEXT_DIM,
            )

    def _on_ok(self):
        mode = self._mode_var.get()
        if mode == "new":
            result = ("new", None, False, False)
        else:
            profile = self._profile_var.get()
            if not profile or profile == "(no profiles)":
                return
            result = ("append", profile, self._overwrite_var.get(), self._skip_existing_var.get())
        self._on_done(result)

    def _on_cancel(self):
        self._on_done(None)


class CollectionContinueInstallDialog(tk.Frame):
    """Overlay panel shown when a collection is already installed in a profile.

    Instead of offering new/append, shows a single 'Continue Install' action
    targeting the profile that already contains this collection's URL.
    """

    def __init__(self, parent, profile_name: str, on_done):
        super().__init__(parent, bg=BG_DEEP)
        self._on_done = on_done
        self._profile_name = profile_name
        self._build()

    def _build(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        card = tk.Frame(self, bg=BG_PANEL, bd=0, highlightthickness=1,
                        highlightbackground=BORDER)
        card.grid(row=0, column=0)
        card.grid_columnconfigure(0, weight=1)

        row = 0

        # Header bar
        header = tk.Frame(card, bg=BG_HEADER, height=scaled(42))
        header.grid(row=row, column=0, sticky="ew")
        header.grid_propagate(False)
        tk.Label(
            header, text="Continue Collection Install",
            font=TK_FONT_BOLD, fg=TEXT_MAIN, bg=BG_HEADER,
        ).pack(side="left", padx=12, pady=8)
        row += 1

        # Separator
        tk.Frame(card, bg=BORDER, height=1).grid(row=row, column=0, sticky="ew")
        row += 1

        # Body
        body = tk.Frame(card, bg=BG_PANEL)
        body.grid(row=row, column=0, sticky="ew", padx=24, pady=(16, 8))
        body.grid_columnconfigure(0, weight=1)
        row += 1

        tk.Label(
            body, text=f"This collection is already installed in profile\n'{self._profile_name}'",
            font=TK_FONT_BOLD, fg=TEXT_MAIN, bg=BG_PANEL, anchor="center", justify="center",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 14))

        # Separator before buttons
        tk.Frame(card, bg=BORDER, height=1).grid(row=row, column=0, sticky="ew")
        row += 1

        # Button bar
        bar = tk.Frame(card, bg=BG_HEADER, height=scaled(44))
        bar.grid(row=row, column=0, sticky="ew")
        bar.grid_propagate(False)
        ctk.CTkButton(
            bar, text="Cancel", width=80, height=28, font=FONT_NORMAL,
            fg_color=BG_DEEP, hover_color=BG_HOVER, text_color=TEXT_MAIN,
            command=self._on_cancel,
        ).pack(side="right", padx=(4, 12), pady=8)
        ctk.CTkButton(
            bar, text="Continue Install", width=120, height=28, font=FONT_BOLD,
            fg_color=ACCENT, hover_color=ACCENT_HOV, text_color=TEXT_ON_ACCENT,
            command=self._on_ok,
        ).pack(side="right", padx=4, pady=8)

    def _on_ok(self):
        self._on_done(("continue", self._profile_name, False, False))

    def _on_cancel(self):
        self._on_done(None)


class CollectionUpdateDialog(tk.Frame):
    """Overlay shown when the user clicks **Update Collection**.

    Presents the reconciliation between the installed revision and the newly
    selected one as four expandable sections: mods to remove, mods to update,
    mods to add, and orphans (collection-origin mods without mod_id/file_id
    that the new manifest cannot verify). The user confirms with
    ``Apply Update`` or backs out with ``Cancel``.
    """

    def __init__(
        self,
        parent,
        *,
        profile_name: str,
        from_revision: "int | None",
        to_revision: "int | None",
        to_remove: list[str],
        to_update: list[str],         # "old mod name -> new file_id label"
        to_add: list[str],
        orphans: list[str],
        on_done,
    ):
        super().__init__(parent, bg=BG_DEEP)
        self._on_done = on_done
        self._profile_name = profile_name
        self._from_rev = from_revision
        self._to_rev = to_revision
        self._to_remove = list(to_remove)
        self._to_update = list(to_update)
        self._to_add = list(to_add)
        self._orphans = list(orphans)
        self._expanded: dict[str, bool] = {
            "remove": False, "update": False, "add": False, "orphan": False,
        }
        self._section_bodies: dict[str, tk.Frame] = {}
        self._build()

    # --------------------------------------------------------------
    def _build(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        card = tk.Frame(self, bg=BG_PANEL, bd=0,
                        highlightthickness=1, highlightbackground=BORDER)
        card.grid(row=0, column=0, padx=20, pady=20)
        card.grid_columnconfigure(0, weight=1)
        # Body row (scrollable region) is the one that should grow.
        # Rows 0-2 are fixed-height (header, summary); rows after that are the
        # body, separator, and button bar.
        card.grid_rowconfigure(3, weight=1)
        # Size is recomputed from the toplevel window once it's actually rendered,
        # since this overlay is place()'d to fill its parent and `self` has no
        # dimensions until after that completes.
        self._card = card
        card.configure(width=900, height=640)
        card.grid_propagate(False)
        self.after(10, self._resize_card_to_toplevel)

        row = 0

        header = tk.Frame(card, bg=BG_HEADER, height=scaled(42))
        header.grid(row=row, column=0, sticky="ew")
        header.grid_propagate(False)
        tk.Label(
            header, text="Update Collection",
            font=TK_FONT_BOLD, fg=TEXT_MAIN, bg=BG_HEADER,
        ).pack(side="left", padx=12, pady=8)
        row += 1

        tk.Frame(card, bg=BORDER, height=1).grid(row=row, column=0, sticky="ew")
        row += 1

        summary = tk.Frame(card, bg=BG_PANEL)
        summary.grid(row=row, column=0, sticky="ew", padx=24, pady=(14, 6))
        summary.grid_columnconfigure(0, weight=1)
        row += 1

        from_label = f"Rev {self._from_rev}" if self._from_rev is not None else "Unknown"
        to_label = f"Rev {self._to_rev}" if self._to_rev is not None else "(latest)"
        tk.Label(
            summary,
            text=f"Profile '{self._profile_name}': {from_label} → {to_label}",
            font=TK_FONT_BOLD, fg=TEXT_MAIN, bg=BG_PANEL,
            anchor="center", justify="center",
        ).grid(row=0, column=0, sticky="ew")

        counts = tk.Label(
            summary,
            text=(
                f"Remove {len(self._to_remove)}  ·  "
                f"Update {len(self._to_update)}  ·  "
                f"Add {len(self._to_add)}  ·  "
                f"Orphans {len(self._orphans)}"
            ),
            font=TK_FONT_NORMAL, fg=TEXT_DIM, bg=BG_PANEL,
            anchor="center", justify="center",
        )
        counts.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        warning_lbl = tk.Label(
            summary,
            text=(
                "Your existing load order and separators will be preserved. "
                "New mods will be inserted relative to their neighbors from "
                "the new collection manifest; mods with no defined position "
                "will be placed at the top of the list."
            ),
            font=TK_FONT_NORMAL, fg=TEXT_DIM, bg=BG_PANEL,
            anchor="center", justify="center",
        )
        warning_lbl.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        # Re-wrap the warning label whenever the dialog card resizes so the
        # text fits the current width.
        def _rewrap(_event=None):
            try:
                w = card.winfo_width() - 80
                if w > 120:
                    warning_lbl.configure(wraplength=w)
            except Exception:
                pass
        card.bind("<Configure>", _rewrap)

        # Scrollable body: four expandable sections, scrolled via canvas + scrollbar.
        scroll_wrap = tk.Frame(card, bg=BG_PANEL)
        scroll_wrap.grid(row=row, column=0, sticky="nsew", padx=(24, 8), pady=(10, 10))
        scroll_wrap.grid_rowconfigure(0, weight=1)
        scroll_wrap.grid_columnconfigure(0, weight=1)
        row += 1

        canvas = tk.Canvas(
            scroll_wrap, bg=BG_PANEL, bd=0, highlightthickness=0,
            takefocus=0,
        )
        canvas.grid(row=0, column=0, sticky="nsew")
        vsb = ctk.CTkScrollbar(
            scroll_wrap, orientation="vertical", command=canvas.yview,
            width=14,
        )
        vsb.grid(row=0, column=1, sticky="ns", padx=(2, 0))
        canvas.configure(yscrollcommand=vsb.set)

        body = tk.Frame(canvas, bg=BG_PANEL)
        body.grid_columnconfigure(0, weight=1)
        body_window = canvas.create_window((0, 0), window=body, anchor="nw")

        def _on_body_configure(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
        body.bind("<Configure>", _on_body_configure)

        def _on_canvas_configure(event):
            # Keep the inner frame's width in sync with the canvas so labels
            # lay out to the full width instead of shrinking to content.
            canvas.itemconfigure(body_window, width=event.width)
        canvas.bind("<Configure>", _on_canvas_configure)

        # Mousewheel scrolling — bind to canvas and every descendant we add.
        # Linux uses Button-4/5; Windows/Mac use MouseWheel.
        def _on_mousewheel(event):
            y0, y1 = canvas.yview()
            if y0 <= 0.0 and y1 >= 1.0:
                return "break"
            if getattr(event, "num", None) == 4:
                canvas.yview_scroll(-1, "units")
            elif getattr(event, "num", None) == 5:
                canvas.yview_scroll(1, "units")
            else:
                delta = int(-1 * (event.delta / 120)) if abs(event.delta) >= 120 else (-1 if event.delta > 0 else 1)
                canvas.yview_scroll(delta, "units")
            return "break"
        self._wheel_handler = _on_mousewheel
        self._wheel_canvas = canvas
        # Bind wheel at the card level so scrolling works from anywhere in
        # the dialog (header, summary, body, buttons).
        for w in (card, scroll_wrap, canvas, body):
            w.bind("<MouseWheel>", _on_mousewheel)
            w.bind("<Button-4>", _on_mousewheel)
            w.bind("<Button-5>", _on_mousewheel)

        self._build_section(body, 0, "remove", "Remove", self._to_remove,
                            BTN_DANGER_ALT, BTN_DANGER_ALT_HOV)
        self._build_section(body, 1, "update", "Update", self._to_update,
                            BTN_INFO_DEEP, BTN_INFO_DEEP_HOV)
        self._build_section(body, 2, "add", "Add", self._to_add,
                            BTN_SUCCESS, BTN_SUCCESS_HOV)
        self._build_section(body, 3, "orphan", "Orphans", self._orphans,
                            BTN_WARN_ORANGE, BTN_WARN_ORANGE_HOV)

        if not (self._to_remove or self._to_update or self._to_add or self._orphans):
            tk.Label(
                body,
                text="No changes detected between these revisions.",
                font=TK_FONT_NORMAL, fg=TEXT_DIM, bg=BG_PANEL,
            ).grid(row=8, column=0, sticky="ew", pady=12)

        tk.Frame(card, bg=BORDER, height=1).grid(row=row, column=0, sticky="ew")
        row += 1

        bar = tk.Frame(card, bg=BG_HEADER, height=scaled(44))
        bar.grid(row=row, column=0, sticky="ew")
        bar.grid_propagate(False)
        ctk.CTkButton(
            bar, text="Cancel", width=80, height=28, font=FONT_NORMAL,
            fg_color=BG_DEEP, hover_color=BG_HOVER, text_color=TEXT_MAIN,
            command=self._on_cancel,
        ).pack(side="right", padx=(4, 12), pady=8)
        apply_btn_enabled = bool(
            self._to_remove or self._to_update or self._to_add or self._orphans
        )
        apply_btn = ctk.CTkButton(
            bar, text="Apply Update", width=120, height=28, font=FONT_BOLD,
            fg_color=BTN_INFO_DEEP, hover_color=BTN_INFO_DEEP_HOV,
            text_color=TEXT_WHITE,
            command=self._on_ok,
        )
        if not apply_btn_enabled:
            apply_btn.configure(state="disabled")
        apply_btn.pack(side="right", padx=4, pady=8)

    # --------------------------------------------------------------
    def _bind_wheel(self, widget) -> None:
        """Forward mousewheel events from *widget* to the scrollable canvas."""
        handler = getattr(self, "_wheel_handler", None)
        if handler is None:
            return
        widget.bind("<MouseWheel>", handler)
        widget.bind("<Button-4>", handler)
        widget.bind("<Button-5>", handler)

    def _build_section(self, parent, grid_row: int, key: str,
                       label: str, items: list[str],
                       accent: str, accent_hov: str) -> None:
        count = len(items)
        header_row = tk.Frame(parent, bg=BG_PANEL)
        header_row.grid(row=grid_row * 2, column=0, sticky="ew", pady=(2, 0))
        header_row.grid_columnconfigure(1, weight=1)
        self._bind_wheel(header_row)

        toggle_text = f"▶ {label} ({count})" if count else f"  {label} (0)"
        toggle_btn = tk.Label(
            header_row,
            text=toggle_text,
            font=TK_FONT_BOLD, fg=accent, bg=BG_PANEL,
            anchor="w", cursor="hand2" if count else "",
        )
        toggle_btn.grid(row=0, column=0, sticky="w")
        self._bind_wheel(toggle_btn)
        if count:
            toggle_btn.bind("<Button-1>", lambda _e, k=key, b=toggle_btn, lbl=label, n=count: self._toggle(k, b, lbl, n))

        body = tk.Frame(parent, bg=BG_ROW, bd=0)
        body.grid(row=grid_row * 2 + 1, column=0, sticky="ew", padx=(18, 0), pady=(0, 2))
        body.grid_columnconfigure(0, weight=1)
        body.grid_remove()  # hidden by default
        self._section_bodies[key] = body
        self._bind_wheel(body)

        # Pre-populate the body with mod names.
        for i, name in enumerate(items):
            lbl = tk.Label(
                body, text=name, font=TK_FONT_NORMAL, fg=TEXT_MAIN, bg=BG_ROW,
                anchor="w", justify="left",
            )
            lbl.grid(row=i, column=0, sticky="ew", padx=8, pady=1)
            self._bind_wheel(lbl)

    def _toggle(self, key: str, label_widget: tk.Label, label: str, count: int) -> None:
        expanded = not self._expanded.get(key, False)
        self._expanded[key] = expanded
        body = self._section_bodies.get(key)
        if body is None:
            return
        if expanded:
            body.grid()
            label_widget.configure(text=f"▼ {label} ({count})")
        else:
            body.grid_remove()
            label_widget.configure(text=f"▶ {label} ({count})")
        # Recompute the scroll region once the layout settles.
        canvas = getattr(self, "_wheel_canvas", None)
        if canvas is not None:
            self.after_idle(
                lambda: canvas.configure(scrollregion=canvas.bbox("all"))
            )

    def _resize_card_to_toplevel(self) -> None:
        """Size the dialog card relative to the toplevel window, now that the
        overlay has been placed and has real dimensions."""
        card = getattr(self, "_card", None)
        if card is None or not card.winfo_exists():
            return
        try:
            top = self.winfo_toplevel()
            top.update_idletasks()
            w = top.winfo_width()
            h = top.winfo_height()
        except Exception:
            return
        # Generous defaults, capped to the window with a 60px margin.
        card_w = max(560, min(960, w - 60))
        card_h = max(360, min(720, h - 60))
        try:
            card.configure(width=card_w, height=card_h)
        except Exception:
            pass

    def _on_ok(self):
        self._on_done(True)

    def _on_cancel(self):
        self._on_done(False)

