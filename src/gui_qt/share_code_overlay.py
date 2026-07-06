"""Borderless in-window overlays for the profile share-code feature.

``ShareCodeExportOverlay`` — shows a generated share code in a read-only, word-
wrapped text box with a "Copy to clipboard" button (the code is copied to the
clipboard automatically on open too).

``ShareCodeImportOverlay`` — a multi-line paste box; ``on_done(code)`` on Import
or ``on_done(None)`` on Cancel / Esc / backdrop click.

Both are child overlays (NOT top-level windows — gaming-mode opens top-levels
behind the app), modeled on ``gui_qt/text_input_overlay.py``.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QPlainTextEdit,
)

from gui_qt.theme_qt import active_palette, _c


class _CodeOverlayBase(QWidget):
    CARD_W = 560
    CARD_H = 320

    def __init__(self, host: QWidget):
        super().__init__(host)
        self._host = host
        self._done = False
        p = active_palette()
        self.setObjectName("OverlayBackdrop")
        self.setStyleSheet("#OverlayBackdrop { background: rgba(0,0,0,150); }")
        self.setGeometry(host.rect())

        self._card = QFrame(self)
        self._card.setObjectName("ShareCodeCard")
        self._card.setStyleSheet(
            f"#ShareCodeCard {{ background:{_c(p,'BG_PANEL')};"
            f" border:1px solid {_c(p,'BORDER')}; border-radius:8px; }}")
        self._v = QVBoxLayout(self._card)
        self._v.setContentsMargins(18, 16, 18, 16)
        self._v.setSpacing(8)

    def _p(self):
        return active_palette()

    def _title(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color:{_c(self._p(),'TEXT_MAIN')}; font-weight:600; font-size:16px;")
        return lbl

    def _sub(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{_c(self._p(),'TEXT_DIM')}; font-size:13px;")
        lbl.setWordWrap(True)
        return lbl

    def _text_area(self, read_only: bool) -> QPlainTextEdit:
        p = self._p()
        area = QPlainTextEdit()
        area.setReadOnly(read_only)
        area.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        area.setStyleSheet(
            f"QPlainTextEdit {{ background:{_c(p,'BG_DEEP')};"
            f" color:{_c(p,'TEXT_MAIN')}; border:1px solid {_c(p,'BORDER')};"
            f" border-radius:5px; padding:6px; font-family:monospace; }}")
        return area

    def _show(self):
        self._host.installEventFilter(self)
        self._reposition()
        self.show()
        self.raise_()

    def _reposition(self):
        self.setGeometry(self._host.rect())
        w = min(self.CARD_W, self._host.width() - 40)
        h = min(self.CARD_H, self._host.height() - 40)
        self._card.setFixedSize(max(380, w), max(200, h))
        self._card.move((self.width() - self._card.width()) // 2,
                        (self.height() - self._card.height()) // 2)

    def _finish(self, result):
        if self._done:
            return
        self._done = True
        self._host.removeEventFilter(self)
        cb = getattr(self, "_on_done", None)
        self.hide()
        self.deleteLater()
        if cb is not None:
            cb(result)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._finish(None)
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if not self._card.geometry().contains(event.position().toPoint()):
            self._finish(None)

    def eventFilter(self, obj, event):
        if obj is self._host and event.type() == QEvent.Resize:
            self._reposition()
        return super().eventFilter(obj, event)


class ShareCodeExportOverlay(_CodeOverlayBase):
    """Show a generated share code with a Copy-to-clipboard button. The code is
    also copied to the clipboard automatically on open."""

    def __init__(self, host: QWidget, code: str, mod_count: int, on_copy=None):
        super().__init__(host)
        self._on_done = None
        self._code = code
        self._on_copy = on_copy

        self._v.addWidget(self._title(self.tr("Export code")))
        noun = "mod" if mod_count == 1 else "mods"
        self._v.addWidget(self._sub(self.tr(
            "Share this code with someone to send them your load order "
            "({0} {1}). They can add it with Import code.").format(mod_count, noun)))

        self._area = self._text_area(read_only=True)
        self._area.setPlainText(code)
        self._v.addWidget(self._area, 1)

        bar = QHBoxLayout()
        bar.addStretch(1)
        close = QPushButton(self.tr("Close"))
        close.setObjectName("FormButton")
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(lambda: self._finish(None))
        bar.addWidget(close)
        self._copy_btn = QPushButton(self.tr("Copy to clipboard"))
        self._copy_btn.setObjectName("PrimaryButton")
        self._copy_btn.setCursor(Qt.PointingHandCursor)
        self._copy_btn.clicked.connect(self._copy)
        bar.addWidget(self._copy_btn)
        self._v.addLayout(bar)

        self._show()
        self._copy()   # auto-copy on open

    def _copy(self):
        cb = QGuiApplication.clipboard()
        if cb is not None:
            cb.setText(self._code)
        self._copy_btn.setText(self.tr("Copied ✓"))
        if callable(self._on_copy):
            self._on_copy()


class ShareCodeImportOverlay(_CodeOverlayBase):
    """A multi-line paste box for importing a share code. ``on_done(code)`` on
    Import, ``on_done(None)`` on Cancel / Esc / backdrop click."""

    def __init__(self, host: QWidget, on_done):
        super().__init__(host)
        self._on_done = on_done

        self._v.addWidget(self._title(self.tr("Import code")))
        self._v.addWidget(self._sub(self.tr(
            "Paste a share code below to build a new profile from someone "
            "else's load order.")))

        self._area = self._text_area(read_only=False)
        self._area.setPlaceholderText("AMMCODE1:…")
        self._v.addWidget(self._area, 1)

        # Offer to paste the clipboard contents in one tap.
        cb = QGuiApplication.clipboard()
        clip = cb.text() if cb is not None else ""
        bar = QHBoxLayout()
        if clip and clip.strip().startswith("AMMCODE"):
            paste = QPushButton(self.tr("Paste from clipboard"))
            paste.setObjectName("FormButton")
            paste.setCursor(Qt.PointingHandCursor)
            paste.clicked.connect(lambda: self._area.setPlainText(clip))
            bar.addWidget(paste)
        bar.addStretch(1)
        cancel = QPushButton(self.tr("Cancel"))
        cancel.setObjectName("FormButton")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(lambda: self._finish(None))
        bar.addWidget(cancel)
        ok = QPushButton(self.tr("Import"))
        ok.setObjectName("PrimaryButton")
        ok.setCursor(Qt.PointingHandCursor)
        ok.clicked.connect(self._confirm)
        bar.addWidget(ok)
        self._v.addLayout(bar)

        self._show()
        self._area.setFocus()

    def _confirm(self):
        text = self._area.toPlainText().strip()
        if text:
            self._finish(text)
