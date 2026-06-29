"""Detachable tab widget — the Qt replacement for the Tk overlays.

Views that the Tk app showed as overlays (Add Game, Nexus browser, settings,
wizards, …) open here as TABS instead of new windows. A tab can be:
  * switched between (multiple "overlays" open at once),
  * closed,
  * dragged out of the tab bar → becomes a floating window,
  * closed/redocked → reparented back as a tab.

State is preserved across detach/reattach because the page widget is reparented,
never recreated.

Usage:
    tabs = DetachableTabWidget()
    tabs.add_permanent(mods_widget, "Mods")      # tab 0, not closable
    tabs.open_tab(add_game_widget, "Add game", key="add_game")  # focus if exists
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtWidgets import (
    QTabWidget, QTabBar, QWidget, QVBoxLayout, QMainWindow,
)


class _DetachTabBar(QTabBar):
    """Tab bar that emits detach_requested when a tab is dragged far enough
    outside the bar (the gesture people get subtly wrong — so it's centralised
    here with a clear vertical-distance threshold)."""

    detach_requested = Signal(int, QPoint)   # (tab index, global drop pos)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMovable(True)               # reorder within the bar
        self._press_index = -1

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_index = self.tabAt(event.position().toPoint())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # Detach when the pointer leaves the bar vertically by a clear margin
        # (so ordinary horizontal reordering still works).
        if self._press_index != -1:
            off = event.position().toPoint()
            if off.y() < -24 or off.y() > self.height() + 24:
                idx = self._press_index
                self._press_index = -1
                self.detach_requested.emit(idx, event.globalPosition().toPoint())
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._press_index = -1
        super().mouseReleaseEvent(event)


class _FloatingTab(QMainWindow):
    """A detached tab living in its own window. Closing the window closes the
    view entirely (it does NOT redock — close means close)."""

    closed = Signal(QWidget)   # (page) — for the tab widget to forget its key

    def __init__(self, page: QWidget, title: str, parent=None):
        super().__init__(parent)
        self._page = page
        self._title = title
        self.setWindowTitle(title)
        self.setCentralWidget(page)
        self.resize(max(900, page.sizeHint().width()),
                    max(600, page.sizeHint().height()))

    def closeEvent(self, event):
        page = self.takeCentralWidget()
        if page is not None:
            self.closed.emit(page)
            page.deleteLater()
        super().closeEvent(event)


class DetachableTabWidget(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._bar = _DetachTabBar(self)
        self.setTabBar(self._bar)
        self.setTabsClosable(True)
        self.setMovable(True)
        self.setDocumentMode(True)
        self._bar.setDrawBase(False)        # no baseline frame under the tabs
        self._bar.setExpanding(False)       # tabs hug their text (left-aligned)
        self._permanent: set[int] = set()      # indices that can't be closed
        self._keys: dict[str, QWidget] = {}     # key → page (focus-if-open)
        self._floats: list[_FloatingTab] = []

        self.tabCloseRequested.connect(self._on_close_requested)
        self._bar.detach_requested.connect(self._detach)
        # Hide the tab bar when only the permanent tab remains (looks like the
        # plain single-window app until a second view is opened).
        self.currentChanged.connect(lambda *_: self._update_bar_visibility())

    def _update_bar_visibility(self):
        self.tabBar().setVisible(self.count() > 1)

    # -- adding tabs --------------------------------------------------------
    def add_permanent(self, widget: QWidget, title: str) -> int:
        """Add a tab that can't be closed or detached (e.g. the Mods view)."""
        idx = self.addTab(widget, title)
        self._permanent.add(id(widget))
        self._refresh_close_buttons()
        self._update_bar_visibility()
        return idx

    def open_tab(self, widget: QWidget, title: str, key: str | None = None):
        """Open *widget* as a tab and focus it. If *key* is already open
        (tab or float), focus that instead of adding a duplicate."""
        if key is not None and key in self._keys:
            existing = self._keys[key]
            self._focus(existing)
            return existing
        idx = self.addTab(widget, title)
        if key is not None:
            self._keys[key] = widget
            widget.setProperty("_tab_key", key)
        self.setCurrentIndex(idx)
        self._update_bar_visibility()
        return widget

    def close_tab(self, key: str):
        """Close the tab/float registered under *key* (no-op if not open)."""
        widget = self._keys.get(key)
        if widget is None:
            return
        # Docked tab?
        idx = self.indexOf(widget)
        if idx != -1:
            self.removeTab(idx)
            self._forget(widget)
            widget.deleteLater()
            self._update_bar_visibility()
            return
        # Otherwise a floating window — close it (its `closed` drops the key).
        for flt in list(self._floats):
            if flt.centralWidget() is widget:
                flt.close()
                return

    # -- close / detach -----------------------------------------------------
    def _on_close_requested(self, index: int):
        w = self.widget(index)
        if id(w) in self._permanent:
            return
        self.removeTab(index)
        self._forget(w)
        w.deleteLater()
        self._update_bar_visibility()

    def _detach(self, index: int, drop_pos: QPoint):
        w = self.widget(index)
        if w is None or id(w) in self._permanent:
            return
        title = self.tabText(index)
        self.removeTab(index)
        flt = _FloatingTab(w, title, self.window())
        flt.closed.connect(self._on_float_closed)
        flt.move(drop_pos)
        flt.show()
        self._floats.append(flt)
        self._update_bar_visibility()

    def _on_float_closed(self, page: QWidget):
        # Closing a detached window closes the view: drop its dedup key and
        # forget the float (the page is deleteLater'd by the float).
        self._forget(page)
        self._floats = [f for f in self._floats if f._page is not page]

    # -- helpers ------------------------------------------------------------
    def _focus(self, widget: QWidget):
        idx = self.indexOf(widget)
        if idx != -1:
            self.setCurrentIndex(idx)
        else:
            # It's floating — raise its window.
            for f in self._floats:
                if f._page is widget:
                    f.raise_(); f.activateWindow()
                    break

    def _forget(self, widget: QWidget):
        key = widget.property("_tab_key")
        if key and key in self._keys:
            del self._keys[key]

    def _refresh_close_buttons(self):
        """Permanent tabs show no close button."""
        for i in range(self.count()):
            if id(self.widget(i)) in self._permanent:
                self.tabBar().setTabButton(i, QTabBar.RightSide, None)
