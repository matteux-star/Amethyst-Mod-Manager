"""Panel-scoped image preview widget for the Mod Files tab.

Loads via Pillow (so .dds/.tga/.tiff decode — QPixmap can't) and shows the image
fit-to-panel over a checkerboard backdrop (transparency visible). Click toggles
fit ↔ 100%. Used as a modlist-panel-scoped tab: the Mod Files tree stays live in
the plugins panel while the preview occupies the modlist region.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QScrollArea, QSizePolicy,
)

PREVIEW_EXTS = {
    ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp",
    ".tga", ".tif", ".tiff", ".ico", ".dds",
}


def _load_qimage(path: Path) -> QImage | None:
    """Load *path* to a QImage. Tries QImage first (fast for common formats),
    falls back to Pillow for .dds/.tga/etc."""
    img = QImage(str(path))
    if not img.isNull():
        return img
    try:
        from PIL import Image as PilImage
        with PilImage.open(path) as im:
            im = im.convert("RGBA")
            data = im.tobytes("raw", "RGBA")
            qi = QImage(data, im.width, im.height, QImage.Format_RGBA8888)
            return qi.copy()   # detach from the freed buffer
    except Exception:
        return None


class _ImageCanvas(QLabel):
    """Paints the image centred over a checkerboard, scaled to fit (or 100%)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(1, 1)
        self._pm: QPixmap | None = None
        self._fit = True
        self.setCursor(Qt.PointingHandCursor)

    def set_image(self, pm: QPixmap | None):
        self._pm = pm
        self.update()

    def toggle_fit(self):
        self._fit = not self._fit
        if self._fit:
            self.setMinimumSize(1, 1)
        elif self._pm is not None:
            self.setMinimumSize(self._pm.size())
        self.update()

    def mousePressEvent(self, e):
        self.toggle_fit()

    def paintEvent(self, _e):
        p = QPainter(self)
        self._paint_checker(p)
        if self._pm is None or self._pm.isNull():
            p.setPen(QColor("#aaa"))
            p.drawText(self.rect(), Qt.AlignCenter, "Image could not be loaded")
            p.end()
            return
        pm = self._pm
        if self._fit:
            scaled = pm.scaled(self.size(), Qt.KeepAspectRatio,
                               Qt.SmoothTransformation)
        else:
            scaled = pm
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        p.drawPixmap(x, y, scaled)
        p.end()

    def _paint_checker(self, p: QPainter):
        tile = 12
        c1, c2 = QColor("#353535"), QColor("#454545")
        p.fillRect(self.rect(), QBrush(c1))
        for y in range(0, self.height(), tile):
            for x in range(0, self.width(), tile):
                if ((x // tile) + (y // tile)) % 2:
                    p.fillRect(x, y, tile, tile, c2)


class ImagePreview(QWidget):
    """A panel-scoped image preview: header (file name) + canvas. Fit by default;
    click the image to toggle 100%, scroll when zoomed."""

    def __init__(self, path: Path, display_name: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("ImagePreview")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        header = QLabel(display_name or path.name)
        header.setObjectName("ImagePreviewHeader")
        header.setStyleSheet(
            "background:#252525; color:#ddd; padding:6px 10px; font-weight:600;")
        header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        v.addWidget(header)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setAlignment(Qt.AlignCenter)
        self._scroll.setStyleSheet("background:#2a2a2a; border:none;")
        self._canvas = _ImageCanvas()
        self._scroll.setWidget(self._canvas)
        v.addWidget(self._scroll, 1)

        qi = _load_qimage(path)
        self._canvas.set_image(QPixmap.fromImage(qi) if qi is not None else None)

    def set_image(self, path: Path, display_name: str = ""):
        """Swap the previewed image in place (browsing between files)."""
        qi = _load_qimage(path)
        self._canvas.set_image(QPixmap.fromImage(qi) if qi is not None else None)
