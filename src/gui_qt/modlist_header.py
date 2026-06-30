"""Tk-style column header: a boundary drag grows one column and shrinks the
other side (cascading past minimums), total width constant, no overflow. We own
the drag because QHeaderView's native resize maps a boundary to the wrong column
and allows overflow.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHeaderView
from PySide6.QtCore import Qt


_GRAB_PX = 8   # pixels either side of a boundary that count as "on the line"


class TkStyleHeader(QHeaderView):
    def __init__(self, view, col_mins: dict, col_defaults: dict | None = None,
                 parent=None):
        super().__init__(Qt.Horizontal, parent)
        self._view = view
        self._col_mins = col_mins
        self._col_defaults = col_defaults or {}
        # Section-move OFF: it conflicts with boundary-drag resizing and isn't
        # needed for the Tk feel. (Column reordering can return later via a
        # dedicated affordance.)
        self.setSectionsMovable(False)
        self.setSectionsClickable(True)
        # We own resizing; Qt must not auto-resize or interactively resize.
        self.setSectionResizeMode(QHeaderView.Fixed)
        self.setMouseTracking(True)
        self._drag_boundary = None   # (left_logical, right_logical)
        self._drag_x = 0
        self._cursor_on = False      # whether SplitHCursor is currently set

    # -- boundary detection -------------------------------------------------
    def _boundary_at(self, x: int):
        """Return (left_logical, right_logical) if x is on a boundary between
        two visible sections, else None. Uses visual order."""
        count = self.count()
        # Build visible sections in visual order with their right-edge x.
        edges = []
        for vis in range(count):
            logical = self.logicalIndex(vis)
            if self.isSectionHidden(logical):
                continue
            pos = self.sectionViewportPosition(logical)
            size = self.sectionSize(logical)
            edges.append((logical, pos, pos + size))
        for i in range(len(edges) - 1):   # skip the very last right edge
            left_logical, _, right_edge = edges[i]
            right_logical = edges[i + 1][0]
            if abs(x - right_edge) <= _GRAB_PX:
                return (left_logical, right_logical)
        return None

    # -- mouse handling -----------------------------------------------------
    def mouseMoveEvent(self, event):
        x = event.position().toPoint().x()
        if self._drag_boundary is not None:
            self._do_drag(x)
            return   # don't let the base class interfere mid-drag
        # Cursor feedback. Only toggle when it actually changes, and DON'T call
        # super() while on a boundary — the base QHeaderView resets the cursor
        # every move, which caused the flicker.
        # Toggle cursor only on change; skip super() while on a boundary (it
        # resets the cursor every move → flicker).
        on = self._boundary_at(x) is not None
        if on != self._cursor_on:
            self.setCursor(Qt.SplitHCursor) if on else self.unsetCursor()
            self._cursor_on = on
        if not on:
            super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            b = self._boundary_at(event.position().toPoint().x())
            if b is not None:
                self._drag_boundary = b
                self._drag_x = event.position().toPoint().x()
                # Snapshot widths at press; each move recomputes from snapshot +
                # cumulative delta so back-and-forth drags return exactly to
                # start (per-event mutation drifts over many 1px moves).
                self._drag_order = self._visible_order()
                self._drag_start_w = {c: self.sectionSize(c)
                                      for c in self._drag_order}
                return   # consume — don't start a section move/sort
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_boundary is not None:
            self._drag_boundary = None
            # The modlist/plugins views persist column widths; the Mod Files tree
            # doesn't need to, so only call the hook when the view provides it.
            save = getattr(self._view, "_schedule_save", None)
            if callable(save):
                save()
            return
        super().mouseReleaseEvent(event)

    def _visible_order(self):
        order = []
        for vis in range(self.count()):
            lg = self.logicalIndex(vis)
            if not self.isSectionHidden(lg):
                order.append(lg)
        return order

    def _do_drag(self, x: int):
        """Recompute widths from the press snapshot + cumulative delta. Cursor
        right of start grows LEFT and shrinks the RIGHT chain (cascade past
        mins); cursor left does the inverse. Growth is capped to what the shrink
        side frees, so the table never overflows."""
        left, right = self._drag_boundary
        order = self._drag_order
        start = self._drag_start_w
        try:
            li = order.index(left)
        except ValueError:
            return
        total = x - self._drag_x        # cumulative delta from press point

        # Start from the snapshot; we'll overwrite the affected columns.
        widths = dict(start)
        right_chain = order[li + 1:]                 # nearest-first
        left_chain = list(reversed(order[:li + 1]))  # nearest-first (incl. left)

        if total > 0:
            moved = self._take(widths, right_chain, total)  # shrink right side
            widths[left] = start[left] + moved              # grow left by freed
        elif total < 0:
            moved = self._take(widths, left_chain, -total)  # shrink left side
            widths[right] = start[right] + moved            # grow right by freed
        # total == 0 → widths == snapshot (restores start exactly)

        for c, w in widths.items():
            if w != self.sectionSize(c):
                self.resizeSection(c, w)

    def _take(self, widths, donors, amount):
        """Reduce donor columns in *widths* (in order, toward their mins) to
        free up to *amount* px. Mutates *widths*; returns total actually freed."""
        freed = 0
        for d in donors:
            if amount <= 0:
                break
            room = widths[d] - self._col_mins.get(d, 60)
            if room <= 0:
                continue
            take = min(room, amount)
            widths[d] -= take
            amount -= take
            freed += take
        return freed
