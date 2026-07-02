"""
RE Engine PAK repair wizard.

RE Engine games (Resident Evil 2/3/7/8, RE4 Remake, Street Fighter 6, …) load
loose mod files by *invalidating* the matching entry inside the game's PAK
archives — the 8-byte hash of each replaced entry is zeroed so the engine falls
back to the loose file on disk.  The manager normally undoes this on restore
using per-profile backups under ``Profiles/<game>/profiles/<profile>/pak_patches/``.

If those backups are lost — e.g. the manager was reinstalled or its Profiles/
folder was deleted while mods were still deployed — the PAKs stay invalidated
and the game can fail to load (black screen) because the vanilla files can be
found neither in the PAK nor on disk.

As a failsafe, deploy also writes a manifest of the original hash bytes into the
game root itself (``.mm_pak_restore.json``), right next to the PAKs.  This
wizard reads that manifest and writes the original bytes back, repairing the
PAKs even with zero manager-side state.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import customtkinter as ctk

if TYPE_CHECKING:
    from Games.base_game import BaseGame

from gui.theme import (
    ACCENT, ACCENT_HOV, BG_DEEP, BG_HEADER, BG_PANEL,
    TEXT_ON_ACCENT,
    TEXT_DIM, TEXT_MAIN,
    FONT_NORMAL, FONT_BOLD, FONT_SMALL,
)

from Utils.re_pak_patcher import (
    ROOT_MANIFEST_NAME,
    restore_from_root_manifest,
    root_manifest_path,
)


class RePakRestoreWizard(ctk.CTkFrame):
    """Repair RE Engine PAKs from the game-root failsafe manifest."""

    def __init__(
        self,
        parent,
        game: "BaseGame",
        log_fn=None,
        *,
        on_close=None,
    ):
        super().__init__(parent, fg_color=BG_DEEP, corner_radius=0)
        self._on_close_cb = on_close or (lambda: None)

        self._game = game
        self._log_fn = log_fn or (lambda _: None)
        self._game_root: Path | None = game.get_game_path()
        self._running = False

        title_bar = ctk.CTkFrame(self, fg_color=BG_HEADER, corner_radius=0, height=40)
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)
        ctk.CTkLabel(
            title_bar, text=f"Repair PAK files — {game.name}",
            font=FONT_BOLD, text_color=TEXT_MAIN, anchor="w",
        ).pack(side="left", padx=12, pady=8)
        ctk.CTkButton(
            title_bar, text="✕", width=32, height=32, font=FONT_BOLD,
            fg_color="transparent", hover_color=BG_PANEL, text_color=TEXT_MAIN,
            command=self._on_close,
        ).pack(side="right", padx=4, pady=4)

        self._build()

    # ------------------------------------------------------------------ utils

    def _on_close(self):
        if self._running:
            return
        self._on_close_cb()

    def _log(self, msg: str):
        self._log_fn(msg)
        try:
            self._log_text.configure(state="normal")
            self._log_text.insert("end", msg + "\n")
            self._log_text.see("end")
            self._log_text.configure(state="disabled")
        except Exception:
            pass

    def _manifest_summary(self) -> tuple[int, int]:
        """Return (pak_count, entry_count) described by the root manifest."""
        if not self._game_root:
            return (0, 0)
        manifest = root_manifest_path(self._game_root)
        if not manifest.exists():
            return (0, 0)
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            paks = data.get("paks", {})
        except (json.JSONDecodeError, OSError):
            return (0, 0)
        if not isinstance(paks, dict):
            return (0, 0)
        entries = sum(len(v) for v in paks.values() if isinstance(v, list))
        return (len(paks), entries)

    # ------------------------------------------------------------------ build

    def _build(self):
        body = ctk.CTkFrame(self, fg_color=BG_DEEP)
        body.pack(fill="both", expand=True, padx=20, pady=20)

        if not self._game_root or not self._game_root.is_dir():
            ctk.CTkLabel(
                body, text="Game path is not set or invalid.",
                font=FONT_NORMAL, text_color="#e06c6c",
            ).pack(pady=12)
            ctk.CTkButton(
                body, text="Close", width=100, height=32, font=FONT_BOLD,
                fg_color=ACCENT, hover_color=ACCENT_HOV, text_color=TEXT_ON_ACCENT,
                command=self._on_close,
            ).pack(pady=12)
            return

        ctk.CTkLabel(
            body,
            text=(
                "If the game won't load (black screen) after removing mods, the\n"
                "PAK archives may still have invalidated entries. This restores the\n"
                "original PAK data from the failsafe manifest in the game root."
            ),
            font=FONT_NORMAL, text_color=TEXT_MAIN, justify="left",
        ).pack(anchor="w", pady=(0, 8))

        ctk.CTkLabel(
            body, text=f"Game root: {self._game_root}",
            font=FONT_SMALL, text_color=TEXT_DIM, wraplength=460,
        ).pack(anchor="w", pady=(0, 8))

        pak_count, entry_count = self._manifest_summary()
        if pak_count == 0:
            self._status_lbl = ctk.CTkLabel(
                body,
                text=(
                    f"No restore manifest ({ROOT_MANIFEST_NAME}) found in the game root.\n"
                    "There is nothing to repair — either no PAK-patching mods were\n"
                    "deployed, or the manifest was already consumed by a clean restore.\n\n"
                    "If the game is still broken, verify the game files via Steam."
                ),
                font=FONT_SMALL, text_color=TEXT_DIM, justify="left",
            )
            self._status_lbl.pack(anchor="w", pady=(0, 12))
            self._repair_btn = None
        else:
            self._status_lbl = ctk.CTkLabel(
                body,
                text=(
                    f"Found a restore manifest covering {pak_count} PAK file"
                    f"{'' if pak_count == 1 else 's'} "
                    f"and {entry_count} invalidated entr"
                    f"{'y' if entry_count == 1 else 'ies'}."
                ),
                font=FONT_NORMAL, text_color=TEXT_MAIN, justify="left",
            )
            self._status_lbl.pack(anchor="w", pady=(0, 12))
            self._repair_btn = ctk.CTkButton(
                body, text="Repair PAK files", width=200, height=36, font=FONT_BOLD,
                fg_color=ACCENT, hover_color=ACCENT_HOV, text_color=TEXT_ON_ACCENT,
                command=self._do_repair,
            )
            self._repair_btn.pack(anchor="w", pady=(0, 12))

        ctk.CTkLabel(
            body, text="Log:", font=FONT_SMALL, text_color=TEXT_DIM,
        ).pack(anchor="w", pady=(4, 2))

        self._log_text = ctk.CTkTextbox(
            body, font=("Consolas", 12), fg_color=BG_PANEL,
            text_color=TEXT_MAIN, height=140, state="disabled",
        )
        self._log_text.pack(fill="both", expand=True, pady=(0, 8))

        ctk.CTkButton(
            body, text="Close", width=100, height=32, font=FONT_BOLD,
            fg_color=BG_PANEL, hover_color="#3d3d3d", text_color=TEXT_MAIN,
            command=self._on_close,
        ).pack(anchor="e")

    # ----------------------------------------------------------------- repair

    def _do_repair(self):
        if self._running or not self._game_root:
            return
        self._running = True
        if self._repair_btn is not None:
            self._repair_btn.configure(state="disabled")
        self._log("Repairing PAK files from game-root manifest …")

        game_root = self._game_root

        def run():
            try:
                restored = restore_from_root_manifest(game_root, log_fn=self._log_threadsafe)
                if restored:
                    msg = (f"Repair complete — restored {restored} entr"
                           f"{'y' if restored == 1 else 'ies'} to vanilla.")
                else:
                    msg = ("Nothing to repair — the PAK entries are already vanilla "
                           "(or no manifest was found).")
                self.after(0, lambda: self._finish(msg))
            except Exception as e:
                self.after(0, lambda e=e: self._finish(f"Error: {e}"))

        threading.Thread(target=run, daemon=True).start()

    def _log_threadsafe(self, msg: str):
        self.after(0, lambda: self._log(msg))

    def _finish(self, msg: str):
        self._log(msg)
        self._running = False
        # The manifest is an append-only ledger that persists after a repair,
        # so the button stays enabled — re-running is always a safe no-op when
        # the PAKs are already vanilla.
        if self._repair_btn is not None:
            self._repair_btn.configure(state="normal")
