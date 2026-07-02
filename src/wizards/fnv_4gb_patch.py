"""
Fallout New Vegas 4GB Patch wizard.

Pure-Python port of the FNV 4GB Patcher (FalloutNVpatch.cpp): identifies
FalloutNV.exe by SHA-1, applies the large-address-aware + NVSE-loader byte
patches in place, and keeps FalloutNV_backup.exe for restoring the original.
"""

from __future__ import annotations

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

# Patch core now lives in Utils.fnv4gb_tools (shared with the Qt wizard);
# re-exported under the original names for back-compat.
from Utils.fnv4gb_tools import (
    BACKUP_NAME as _BACKUP_NAME,
    EXE_NAME as _EXE_NAME,
    apply_4gb_patch,
    inspect_exe,
    restore_backup,
)


# ============================================================================
# Wizard dialog
# ============================================================================

class Fnv4GbPatchWizard(ctk.CTkFrame):
    """Single-page wizard to apply or revert the FNV 4GB patch."""

    def __init__(
        self,
        parent,
        game: "BaseGame",
        log_fn=None,
        *,
        on_close=None,
        **_kwargs,
    ):
        super().__init__(parent, fg_color=BG_DEEP, corner_radius=0)
        self._on_close_cb = on_close or (lambda: None)
        self._game = game
        self._log = log_fn or (lambda msg: None)
        self._game_root: Path | None = game.get_game_path()
        self._info: dict | None = None
        self._busy = False

        title_bar = ctk.CTkFrame(self, fg_color=BG_HEADER, corner_radius=0, height=40)
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)
        ctk.CTkLabel(
            title_bar, text=f"4GB Patch — {game.name}",
            font=FONT_BOLD, text_color=TEXT_MAIN, anchor="w",
        ).pack(side="left", padx=12, pady=8)
        ctk.CTkButton(
            title_bar, text="✕", width=32, height=32, font=FONT_BOLD,
            fg_color="transparent", hover_color=BG_PANEL, text_color=TEXT_MAIN,
            command=self._on_cancel,
        ).pack(side="right", padx=4, pady=4)

        body = ctk.CTkFrame(self, fg_color=BG_DEEP)
        body.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            body,
            text=(
                "Patches FalloutNV.exe so the game can use 4 GB of memory\n"
                "and loads NVSE automatically at startup.\n\n"
                "Under Proton this mostly silences in-game warnings from mods\n"
                "that check for the patch, but it is safe and recommended.\n\n"
                "The original exe is kept as FalloutNV_backup.exe."
            ),
            font=FONT_NORMAL, text_color=TEXT_DIM, justify="center", wraplength=480,
        ).pack(pady=(0, 16))

        self._exe_status = ctk.CTkLabel(
            body, text="Checking FalloutNV.exe…",
            font=FONT_NORMAL, text_color=TEXT_DIM, justify="center", wraplength=480,
        )
        self._exe_status.pack(pady=(0, 6))

        self._backup_status = ctk.CTkLabel(
            body, text="", font=FONT_SMALL, text_color=TEXT_DIM,
            justify="center", wraplength=480,
        )
        self._backup_status.pack(pady=(0, 12))

        btn_frame = ctk.CTkFrame(body, fg_color="transparent")
        btn_frame.pack(side="bottom", pady=(8, 0))

        self._apply_btn = ctk.CTkButton(
            btn_frame, text="Apply 4GB Patch", width=150, height=36,
            font=FONT_BOLD,
            fg_color=ACCENT, hover_color=ACCENT_HOV, text_color=TEXT_ON_ACCENT,
            command=self._on_apply, state="disabled",
        )
        self._apply_btn.pack(side="right", padx=(8, 0))

        self._restore_btn = ctk.CTkButton(
            btn_frame, text="Restore Backup", width=140, height=36,
            font=FONT_BOLD,
            fg_color="#7a3a2d", hover_color="#9e4a38", text_color="white",
            command=self._on_restore, state="disabled",
        )
        self._restore_btn.pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            btn_frame, text="Close", width=100, height=36,
            font=FONT_BOLD,
            fg_color=BG_HEADER, hover_color="#3d3d3d", text_color=TEXT_MAIN,
            command=self._on_cancel,
        ).pack(side="right")

        self._refresh()

    def _on_cancel(self):
        self._on_close_cb()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def _refresh(self):
        """Re-hash the exe in a background thread and update the labels."""
        game_root = self._game_root
        if game_root is None or not game_root.is_dir():
            self._set_exe_status("Game path is not configured.", color="#e06c6c")
            return

        self._set_exe_status("Checking FalloutNV.exe…")
        self._set_buttons(apply=False, restore=False)

        def _worker():
            try:
                info = inspect_exe(game_root)
            except Exception as exc:
                self._set_exe_status(f"Error reading exe: {exc}", color="#e06c6c")
                return
            self._info = info
            state = info["state"]
            if state == "missing":
                self._set_exe_status(
                    f"{_EXE_NAME} not found in the game folder.", color="#e06c6c")
            elif state == "patched":
                self._set_exe_status(
                    f"{_EXE_NAME} is already 4GB patched.", color="#6bc76b")
            elif state == "patchable":
                self._set_exe_status(
                    f"Unpatched {_EXE_NAME} detected ({info['variant']} version) "
                    "— ready to patch.")
            else:
                self._set_exe_status(
                    f"Unrecognised {_EXE_NAME} version.\n"
                    f"SHA-1: {info['hash']}\n"
                    "It may already be modified. Verify game files in Steam/Heroic "
                    "to get a clean exe, then try again.",
                    color="#e0a06c",
                )
            if info["backup_exists"]:
                self._set_backup_status(f"Backup found: {_BACKUP_NAME}")
            else:
                self._set_backup_status("No backup present.")
            self._set_buttons(
                apply=(state == "patchable"),
                restore=info["backup_exists"],
            )

        threading.Thread(target=_worker, daemon=True).start()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_apply(self):
        if self._busy or self._game_root is None:
            return
        self._busy = True
        self._set_buttons(apply=False, restore=False)
        self._set_exe_status("Patching FalloutNV.exe…")
        game_root = self._game_root

        def _worker():
            try:
                variant = apply_4gb_patch(game_root)
                self._log(f"4GB patch wizard: patched {_EXE_NAME} ({variant} version), "
                          f"original saved as {_BACKUP_NAME}.")
            except Exception as exc:
                self._log(f"4GB patch wizard: patch failed: {exc}")
                self._set_exe_status(f"Patch failed: {exc}", color="#e06c6c")
            finally:
                self._busy = False
                try:
                    self.after(0, self._refresh)
                except Exception:
                    pass

        threading.Thread(target=_worker, daemon=True).start()

    def _on_restore(self):
        if self._busy or self._game_root is None:
            return
        self._busy = True
        self._set_buttons(apply=False, restore=False)
        self._set_exe_status("Restoring original FalloutNV.exe…")
        game_root = self._game_root

        def _worker():
            try:
                restore_backup(game_root)
                self._log(f"4GB patch wizard: restored {_EXE_NAME} from {_BACKUP_NAME}.")
            except Exception as exc:
                self._log(f"4GB patch wizard: restore failed: {exc}")
                self._set_exe_status(f"Restore failed: {exc}", color="#e06c6c")
            finally:
                self._busy = False
                try:
                    self.after(0, self._refresh)
                except Exception:
                    pass

        threading.Thread(target=_worker, daemon=True).start()

    # ------------------------------------------------------------------
    # Thread-safe UI helpers
    # ------------------------------------------------------------------

    def _set_exe_status(self, text: str, color: str = TEXT_DIM):
        try:
            self.after(0, lambda: self._exe_status.configure(text=text, text_color=color))
        except Exception:
            pass

    def _set_backup_status(self, text: str, color: str = TEXT_DIM):
        try:
            self.after(0, lambda: self._backup_status.configure(text=text, text_color=color))
        except Exception:
            pass

    def _set_buttons(self, *, apply: bool, restore: bool):
        def _do():
            self._apply_btn.configure(state="normal" if apply else "disabled")
            self._restore_btn.configure(state="normal" if restore else "disabled")
        try:
            self.after(0, _do)
        except Exception:
            pass
