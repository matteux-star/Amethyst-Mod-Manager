"""
install_question.py
Generic single-choice question overlay for install-time wizards.

Some game handlers need to ask the user a multiple-choice question while a mod
is being installed — e.g. Dragon Age's DAO-Modmanager ``.override`` mods carry
an ``OverrideConfig.xml`` that offers variant choices (eye colour, armour
style, ...). The install runs on a worker thread and ``additional_install_logic``
callables receive no parent window, so ``ask_choice`` resolves the root window
itself and shows an in-app overlay (a CTkFrame placed over the mod-panel
container, matching BainDialog / the FOMOD installer) rather than a popup
Toplevel.

``ask_choice(title, prompt, options, default_index) -> str | None`` returns the
chosen option label, or None if cancelled / no GUI is available (callers treat
None as "keep defaults").
"""

from __future__ import annotations

import threading
import tkinter as tk

import customtkinter as ctk

from gui.theme import (
    BG_DEEP, BG_PANEL, BG_HEADER, BG_CARD, BORDER,
    ACCENT, ACCENT_HOV, TEXT_ON_ACCENT, TEXT_MAIN, TEXT_DIM,
    scaled,
)


class _ChoiceOverlay(ctk.CTkFrame):
    """Full-panel overlay asking the user to pick one of several options.

    ``on_done(result)`` is called with the chosen label, or None on cancel.
    """

    def __init__(self, parent, title: str, prompt: str,
                 options: list[str], default_index: int = 0, on_done=None):
        super().__init__(parent, fg_color=BG_DEEP, corner_radius=0)
        self._on_done = on_done or (lambda r: None)
        self.result: str | None = None
        self._options = options

        # Header bar
        bar = ctk.CTkFrame(self, fg_color=BG_HEADER, corner_radius=0, height=scaled(40))
        bar.pack(fill="x")
        bar.pack_propagate(False)
        ctk.CTkLabel(
            bar, text=title, text_color=TEXT_MAIN,
            font=ctk.CTkFont(size=scaled(15), weight="bold"),
        ).pack(side="left", padx=scaled(16))

        # Body
        body = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        body.pack(fill="both", expand=True, padx=scaled(24), pady=scaled(20))

        ctk.CTkLabel(
            body, text=prompt, justify="left", text_color=TEXT_DIM,
            wraplength=scaled(520),
        ).pack(anchor="w", pady=(0, scaled(16)))

        default_index = (
            max(0, min(default_index, len(options) - 1)) if options else 0
        )
        self._var = tk.StringVar(value=options[default_index] if options else "")

        card = ctk.CTkFrame(body, fg_color=BG_PANEL, corner_radius=8)
        card.pack(fill="x", anchor="w")
        for opt in options:
            ctk.CTkRadioButton(
                card, text=opt, variable=self._var, value=opt,
                text_color=TEXT_MAIN, fg_color=ACCENT, hover_color=ACCENT_HOV,
            ).pack(anchor="w", padx=scaled(16), pady=scaled(6))

        # Footer bar with actions
        footer = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=0,
                              height=scaled(56))
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        ctk.CTkFrame(footer, fg_color=BORDER, height=1, corner_radius=0).pack(
            fill="x", side="top")
        ctk.CTkButton(
            footer, text="OK", width=scaled(100), fg_color=ACCENT,
            hover_color=ACCENT_HOV, text_color=TEXT_ON_ACCENT,
            command=self._on_ok,
        ).pack(side="right", padx=scaled(16), pady=scaled(10))
        ctk.CTkButton(
            footer, text="Cancel", width=scaled(100), fg_color=BG_CARD,
            hover_color=BG_HEADER, text_color=TEXT_DIM,
            command=self._on_cancel,
        ).pack(side="right", pady=scaled(10))

    def _on_ok(self) -> None:
        self.result = self._var.get() or None
        self._finish(self.result)

    def _on_cancel(self) -> None:
        self.result = None
        self._finish(None)

    def _finish(self, result) -> None:
        cb = self._on_done
        try:
            self.destroy()
        finally:
            cb(result)


def _resolve_root() -> "tk.Misc | None":
    root = getattr(tk, "_default_root", None)
    try:
        if root is not None and root.winfo_exists():
            return root
    except Exception:
        return None
    return None


def _make_overlay(root, title, prompt, options, default_index, on_done):
    """Create + place the overlay on the mod-panel container. Main thread only."""
    container = getattr(root, "_mod_panel_container", None) or root
    panel = _ChoiceOverlay(container, title, prompt, options,
                           default_index, on_done=on_done)
    if panel.winfo_exists():
        panel.place(relx=0, rely=0, relwidth=1, relheight=1)
        panel.lift()
        panel.focus_set()
    return panel


def ask_choice(title: str, prompt: str, options: list[str],
               default_index: int = 0, log_fn=None) -> str | None:
    """Ask the user to pick one of ``options``. Returns the label or None.

    Safe to call from a worker thread: the overlay is created and awaited via
    the main thread. Returns None when no GUI root is available (headless /
    collection install with no window), so callers fall back to defaults.
    """
    _log = log_fn or (lambda _: None)
    if not options:
        return None
    root = _resolve_root()
    if root is None:
        _log("  [DAO] no Tk root (tk._default_root) — cannot show overlay; "
             "keeping defaults.")
        return None

    # Main thread: block on a Tk variable so the event loop keeps running while
    # the overlay is up (the idiom used for the FOMOD/BAIN install overlays).
    if threading.current_thread() is threading.main_thread():
        done_var = tk.BooleanVar(value=False)
        holder: list = [None]

        def _on_done(result):
            holder[0] = result
            done_var.set(True)

        try:
            _make_overlay(root, title, prompt, options, default_index, _on_done)
            root.wait_variable(done_var)
        except Exception as exc:
            _log(f"  [DAO] overlay failed (main thread): {exc!r}")
            return None
        return holder[0]

    # Worker thread: marshal creation onto the main thread, wait on an Event.
    holder = [None]
    done = threading.Event()
    err: list = [None]

    def _spawn():
        def _on_done(result):
            holder[0] = result
            done.set()
        try:
            _make_overlay(root, title, prompt, options, default_index, _on_done)
        except Exception as exc:
            import traceback
            err[0] = (exc, traceback.format_exc())
            holder[0] = None
            done.set()

    root.after(0, _spawn)
    done.wait()
    if err[0] is not None:
        _log(f"  [DAO] overlay failed (worker thread): {err[0][0]!r}")
        for _line in err[0][1].rstrip().splitlines():
            _log(f"    {_line}")
    return holder[0]
