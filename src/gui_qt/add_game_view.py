"""Add-Game view — a reflowing card grid for selecting/adding games.

Qt port of gui/game_picker_dialog.py (v1 scope). Each card shows the game's
square logo, its name, and a button: "Select" (green) if the game is already
configured, else "Add" (blue accent) to configure it. A search box filters by
name. Custom-game / remote-handler / installed-only filters are deferred.

The view embeds as a detachable tab. It calls back:
    on_select(game_name)  — a configured game was picked (switch to it)
    on_add(game_name)     — an unconfigured game was picked (start configure)
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap, QPainter, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QScrollArea, QPushButton, QFrame, QSizePolicy,
)

from gui_qt.theme_qt import active_palette, _c

_ICONS_DIR = Path(__file__).resolve().parent.parent / "icons" / "games"

CARD_W = 180
CARD_H = 210
IMG_SQ = 140


def _game_logo(game_id: str, size: int) -> QPixmap | None:
    """Load <game_id>.png (or lowercase / custom-images variant), center-crop to
    a square and scale to *size*. Returns None if no logo file exists."""
    candidates = [_ICONS_DIR / f"{game_id}.png", _ICONS_DIR / f"{game_id.lower()}.png"]
    try:
        from Utils.config_paths import get_custom_game_images_dir
        candidates.append(get_custom_game_images_dir() / f"{game_id}.png")
    except Exception:
        pass
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        return None
    pm = QPixmap(str(path))
    if pm.isNull():
        return None
    # Center-crop to square (cover), then scale.
    side = min(pm.width(), pm.height())
    x = (pm.width() - side) // 2
    y = (pm.height() - side) // 2
    pm = pm.copy(x, y, side, side)
    return pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


class _GameCard(QFrame):
    def __init__(self, name: str, game, on_select, on_add, parent=None):
        super().__init__(parent)
        self.setObjectName("GameCard")
        self.setFixedSize(CARD_W, CARD_H)
        self._name = name
        configured = bool(game and game.is_configured())
        game_id = (getattr(game, "game_id", None)
                   or name.lower().replace(" ", "_"))

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        # Logo (or a "?" placeholder).
        logo = QLabel()
        logo.setAlignment(Qt.AlignCenter)
        logo.setFixedHeight(IMG_SQ)
        pm = _game_logo(game_id, IMG_SQ)
        if pm is not None:
            logo.setPixmap(pm)
        else:
            logo.setText("?")
            logo.setStyleSheet(
                f"color:{_c(active_palette(),'TEXT_DIM')}; font-size:36px;"
                " font-weight:bold;")
        v.addWidget(logo)

        # Name (wraps, centered).
        title = QLabel(name)
        title.setAlignment(Qt.AlignCenter)
        title.setWordWrap(True)
        title.setObjectName("GameCardName")
        v.addWidget(title, 1)

        # Select (configured) / Add (not configured).
        btn = QPushButton("Select" if configured else "Add")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setObjectName("GameSelectBtn" if configured else "GameAddBtn")
        btn.clicked.connect(
            (lambda: on_select(name)) if configured else (lambda: on_add(name)))
        v.addWidget(btn)


class AddGameView(QWidget):
    """The reflowing card grid. *on_select(name)* / *on_add(name)* are required."""

    def __init__(self, games: dict, on_select, on_add, parent=None):
        super().__init__(parent)
        self._games = games
        self._on_select = on_select
        self._on_add = on_add
        self._cards: list[tuple[str, _GameCard]] = []   # (search_text, card)
        self._cols = 0
        self._build()
        self._populate()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header: title + search.
        header = QWidget()
        header.setObjectName("HeaderBar")
        hb = QHBoxLayout(header)
        hb.setContentsMargins(12, 8, 12, 8)
        title = QLabel("Select a game to add")
        title.setStyleSheet("font-size:15px; font-weight:600;")
        hb.addWidget(title)
        hb.addStretch(1)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search by name…")
        self._search.setClearButtonEnabled(True)
        self._search.setFixedWidth(260)
        self._search.textChanged.connect(self._apply_search)
        hb.addWidget(self._search)
        outer.addWidget(header)

        # Scroll area holding the grid.
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(16, 12, 16, 12)
        self._grid.setSpacing(12)
        self._grid.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self._scroll.setWidget(self._grid_host)
        outer.addWidget(self._scroll, 1)

    def _populate(self):
        for name in sorted(self._games, key=str.lower):
            game = self._games[name]
            card = _GameCard(name, game, self._on_select, self._on_add)
            search = self._search_text(name, game)
            self._cards.append((search, card))
        self._relayout()

    @staticmethod
    def _search_text(name: str, game) -> str:
        parts = [name]
        if game is not None:
            for attr in ("game_id", "steam_id"):
                val = getattr(game, attr, None)
                if val:
                    parts.append(str(val))
        return " ".join(parts).lower()

    def _visible_cards(self) -> list[_GameCard]:
        q = self._search.text().strip().lower() if hasattr(self, "_search") else ""
        return [c for s, c in self._cards if not q or q in s]

    def _relayout(self):
        # Reflow into as many columns as fit the viewport width.
        vp_w = self._scroll.viewport().width()
        slot = CARD_W + self._grid.spacing()
        cols = max(1, (vp_w - 32) // slot)
        # Clear the grid (without deleting the cards).
        while self._grid.count():
            self._grid.takeAt(0)
        for c in self._cards:
            c[1].hide()
        visible = self._visible_cards()
        for i, card in enumerate(visible):
            self._grid.addWidget(card, i // cols, i % cols, Qt.AlignTop)
            card.show()
        self._cols = cols

    def _apply_search(self, _text=None):
        self._relayout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Re-flow when the column count would change.
        slot = CARD_W + self._grid.spacing()
        cols = max(1, (self._scroll.viewport().width() - 32) // slot)
        if cols != self._cols:
            self._relayout()
