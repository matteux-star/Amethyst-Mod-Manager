"""Framework-status banner shown above the Plugins-tab columns.

A thin vertical stack of colored rows, one per framework the active game declares
(SKSE, BepInEx, RED4ext, …), each saying whether it's installed / staged / present
but disabled / missing. Display-only, mirroring the Tk plugin-panel banner. Data
comes from `Utils.framework_detect.detect_frameworks` (toolkit-neutral); this
widget only maps each state to the matching theme colors.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from gui_qt.theme_qt import active_palette, _c


def _soft(hex_color: str, toward: str, t: float = 0.62) -> str:
    """Blend *hex_color* toward *toward* by *t* — used to calm the banner's
    saturated status fills into a subtle tint that keeps a colour cue without
    reading as a full-width alarm band."""
    a, b = QColor(hex_color), QColor(toward)
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    ).name()
from Utils.framework_detect import (
    STATE_INSTALLED, STATE_NOT_DEPLOYED, STATE_NOT_ENABLED, STATE_MISSING,
)

ROW_H = 22

# state → (bg palette key, fg palette key). Dedicated FRAMEWORK_* keys (their own
# "Framework detection" section in the theme editor); seeded from the same colours
# the shared tinted rows used, but independently editable.
_STATE_COLORS = {
    STATE_INSTALLED:    ("FRAMEWORK_INSTALLED_BG", "FRAMEWORK_INSTALLED_FG"),
    STATE_NOT_DEPLOYED: ("FRAMEWORK_STAGED_BG",    "FRAMEWORK_STAGED_FG"),
    STATE_NOT_ENABLED:  ("FRAMEWORK_DISABLED_BG",  "FRAMEWORK_DISABLED_FG"),
    STATE_MISSING:      ("FRAMEWORK_MISSING_BG",   "FRAMEWORK_MISSING_FG"),
}


class FrameworkBanner(QWidget):
    """Call `set_statuses(list[FrameworkStatus])` to (re)build the rows. Hides
    itself when the list is empty so the columns sit flush."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._v = QVBoxLayout(self)
        self._v.setContentsMargins(0, 0, 0, 0)
        self._v.setSpacing(1)
        self.hide()

    def set_statuses(self, statuses) -> None:
        # Clear existing rows.
        while self._v.count():
            it = self._v.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        if not statuses:
            self.hide()
            return
        p = active_palette()
        panel = _c(p, "BG_PANEL")
        for st in statuses:
            bg_key, fg_key = _STATE_COLORS.get(st.state, _STATE_COLORS[STATE_MISSING])
            # Calm treatment: a subtle tint (fill mixed toward the panel bg) with
            # a 3px accent stripe on the left, mirroring the modlist rows — the
            # status still reads at a glance without a loud saturated band.
            fill = _soft(_c(p, bg_key), panel, 0.62)
            fg = _c(p, fg_key)
            stripe = fg   # the vivid status colour reads as the left edge cue
            lbl = QLabel(st.message)
            lbl.setFixedHeight(ROW_H)
            lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            lbl.setStyleSheet(
                f"background:{fill}; color:{fg};"
                f" border-left:3px solid {stripe}; padding-left:10px;")
            self._v.addWidget(lbl)
        self.show()
