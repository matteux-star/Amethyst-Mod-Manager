"""
Fallout New Vegas 4GB Patch wizard.

Pure-Python port of the FNV 4GB Patcher (FalloutNVpatch.cpp): identifies
FalloutNV.exe by SHA-1, applies the large-address-aware + NVSE-loader byte
patches in place, and keeps FalloutNV_backup.exe for restoring the original.
"""

from __future__ import annotations

import hashlib
import os
import shutil
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

_EXE_NAME = "FalloutNV.exe"
_BACKUP_NAME = "FalloutNV_backup.exe"

# SHA-1 (uppercase hex) of known unpatched exes → (version index, variant label)
_KNOWN_EXES = {
    "D068F394521A67C6E74FE572F59BD1BE71E855F3": (0, "US"),
    "3980940522F0264ED9AF14AEA1773BB19F5160AB": (1, "DE"),
    "5394B94A18FFA6FA846E1D6033AD7F81919F13AC": (2, "RU"),
    "07AFFDA66C89F09B0876A50C77759640BC416673": (0, "US"),
    "F65049B0957D83E61ECCCACC730015AE77FB4C8B": (1, "DE"),
    "ACA83D5A12A64AF8854E381752FE989692D46E04": (2, "RU"),
    "946D2EABA04A75FF361B8617C7632B49F1EDE9D3": (3, "GOG"),
}

_PATCHED_HASHES = {
    "0021023E37B1AF143305A61B7B29A1811CC7C5FB",
    "37CAE4E713B6B182311F66E31668D5005D1B9F5B",
    "600CD576CDE7746FB2CD152FDD24DB97453ED135",
    "34B65096CAEF9374DD6AA39AF855E43308B417F2",
}

# ---------------------------------------------------------------------------
# Patch byte tables (verbatim from FalloutNVpatch.cpp)
# ---------------------------------------------------------------------------

_PATCH1 = bytes([0x22])
_PATCH2 = bytes.fromhex("20 A6 07")
_PATCH3 = [  # per-version (US / DE / RU)
    bytes.fromhex("3E F9 FC"),
    bytes.fromhex("88 C4 FC"),
    bytes.fromhex("15 43 FD"),
]
_PATCH4 = bytes.fromhex("E8 04 FD 06 00 90")
_PATCH5 = bytes.fromhex("E9 56 FC 06 00")
_PATCH6 = bytes.fromhex(
    "90 50 50 8B C4 50 B8 40"
    "00 00 00 50 B8 04 00 00"
    "00 50 8B 85 0C FC FF FF"
    "05 0C 02 00 00 50 FF 55"
    "9C 8B 85 0C FC FF FF 05"
    "0C 02 00 00 C6 00 74 8B"
    "C4 50 8B 44 24 04 50 B8"
    "04 00 00 00 50 8B 85 0C"
    "FC FF FF 05 0C 02 00 00"
    "50 FF 55 9C 58 58 FF A5"
    "0C FC FF FF 00 00 00 00"
    "00 00 00 00 00 00 00 00"
    "50 68 00 A6 47 01 FF 15"
    "B0 F0 FD 00 58 5D 5F 5E"
    "5A 59 5B FF E0 00 00 00"
    "00 00 00 00 00 00 00 00"
) + b"nvse_steam_loader.dll"
_PATCH7 = bytes.fromhex(
    "60 68 C8 A6 47 01 68 E0"
    "A6 47 01 FF 15 F4 F1 FD"
    "00 68 C8 A6 47 01 68 D0"
    "A6 47 01 FF 15 F4 F1 FD"
    "00 61 E9 A7 EC F8 FF"
)
_PATCH8 = [  # per-version Steam AppId string
    b"2238", b"2238", b"2249",
]
_PATCH9 = b"0\x00\x00\x00SteamAppId\x00\x00\x00\x00\x00\x00SteamGameId"

_PATCH_G1 = bytes.fromhex("90 E5 BD")
_PATCH_G2 = bytes.fromhex("D0 4B F6")
_PATCH_G3 = bytes.fromhex(
    "68 A0 E5 FD 00 FF 15 B0"
    "F0 FD 00 E9 3B DF EE FF"
) + b"nvse_steam_loader.dll"


def _patch_list(version: int) -> list[tuple[int, bytes]]:
    """Return (offset, bytes) pairs for the given exe version index."""
    if version == 3:  # GOG
        return [
            (0x00000148, _PATCH_G1),
            (0x00000178, _PATCH_G2),
            (0x00BDD990, _PATCH_G3),
        ]
    return [
        (0x00000136, _PATCH1),
        (0x00000148, _PATCH2),
        (0x00000178, _PATCH3[version]),
        (0x00F57277, _PATCH4),
        (0x00F57385, _PATCH5),
        (0x00FC6F80, _PATCH6),
        (0x00FC7020, _PATCH7),
        (0x00FC70C8, _PATCH8[version]),
        (0x00FC70CC, _PATCH9),
    ]


def inspect_exe(game_root: Path) -> dict:
    """Hash FalloutNV.exe and report its patch state."""
    exe = game_root / _EXE_NAME
    backup = game_root / _BACKUP_NAME
    info = {
        "exe": exe,
        "backup": backup,
        "backup_exists": backup.is_file(),
        "state": "missing",
        "variant": None,
        "hash": None,
    }
    if not exe.is_file():
        return info
    digest = hashlib.sha1(exe.read_bytes()).hexdigest().upper()
    info["hash"] = digest
    if digest in _PATCHED_HASHES:
        info["state"] = "patched"
    elif digest in _KNOWN_EXES:
        info["state"] = "patchable"
        info["variant"] = _KNOWN_EXES[digest][1]
    else:
        info["state"] = "unknown"
    return info


def apply_4gb_patch(game_root: Path) -> str:
    """Patch FalloutNV.exe in place, keeping FalloutNV_backup.exe. Returns the variant label."""
    exe = game_root / _EXE_NAME
    if not exe.is_file():
        raise RuntimeError(f"{_EXE_NAME} not found in {game_root}")

    data = bytearray(exe.read_bytes())
    digest = hashlib.sha1(data).hexdigest().upper()
    if digest in _PATCHED_HASHES:
        raise RuntimeError(f"{_EXE_NAME} is already patched.")
    known = _KNOWN_EXES.get(digest)
    if known is None:
        raise RuntimeError(
            f"Unrecognised {_EXE_NAME} version (SHA-1 {digest}). "
            "The exe may already be modified — verify game files and try again."
        )
    version, variant = known

    for offset, blob in _patch_list(version):
        data[offset:offset + len(blob)] = blob

    backup = game_root / _BACKUP_NAME
    tmp = game_root / (_EXE_NAME + ".mm_tmp")
    tmp.write_bytes(data)
    try:
        shutil.copystat(exe, tmp)
    except OSError:
        pass
    if not backup.exists():
        os.replace(exe, backup)
    os.replace(tmp, exe)
    return variant


def restore_backup(game_root: Path) -> None:
    """Replace FalloutNV.exe with FalloutNV_backup.exe."""
    backup = game_root / _BACKUP_NAME
    if not backup.is_file():
        raise RuntimeError(f"{_BACKUP_NAME} not found in {game_root}")
    os.replace(backup, game_root / _EXE_NAME)


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
