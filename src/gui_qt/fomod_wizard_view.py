"""FOMOD installer wizard — Qt port of gui/fomod_dialog.py.

Opens as a (detachable) tab when an archive with a FOMOD ModuleConfig is being
installed. Walks the visible install steps; each step's groups render as radio
buttons (SelectExactlyOne/SelectAtMostOne) or checkboxes (SelectAtLeastOne/
SelectAny/SelectAll). A left panel shows the hovered/selected option's image +
description. Back/Next/Finish drive the step flow; flag state + step visibility
re-evaluate on each transition via the neutral Utils.fomod_installer backend.

On Finish it calls on_finish(selections) with {step_idx_str: {group: [plugins]}}
which finish_install() feeds to resolve_files(). on_cancel() aborts the install.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QFrame, QRadioButton, QCheckBox, QButtonGroup, QSplitter, QSizePolicy,
)

from gui_qt.theme_qt import active_palette, _c
from Utils.fomod_installer import (
    get_visible_steps, get_default_selections, update_flags,
    validate_selections,
)


class FomodWizardView(QWidget):
    def __init__(self, config, mod_base: Path, mod_name: str,
                 on_finish, on_cancel, parent=None):
        super().__init__(parent)
        self._config = config
        self._base = Path(mod_base)
        self._mod_name = mod_name
        self._on_finish = on_finish
        self._on_cancel = on_cancel
        self._p = active_palette()

        # Per-config-step selections: {step_idx_str: {group_name: [plugin_name]}}.
        self._all_selections: dict[str, dict] = {}
        self._flag_state: dict = {}
        self._installed: set = set()
        self._visible_steps = []
        self._cur = 0
        # Live widget state for the current step: group_name → controls info.
        self._group_state: dict = {}

        self._build()
        self._refresh_visible_steps()
        self._load_step(0)

    # ---- build ------------------------------------------------------------
    def _c(self, k):
        return _c(self._p, k)

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget(); header.setObjectName("HeaderBar")
        hb = QHBoxLayout(header); hb.setContentsMargins(12, 8, 12, 8)
        title = QLabel(self._config.name or self._mod_name)
        title.setStyleSheet("font-size:15px; font-weight:600;")
        hb.addWidget(title)
        hb.addStretch(1)
        self._step_lbl = QLabel("")
        self._step_lbl.setStyleSheet(f"color:{self._c('TEXT_DIM')};")
        hb.addWidget(self._step_lbl)
        outer.addWidget(header)

        # Body: a resizable splitter — left = image+description, right = option
        # groups. Image side is larger by default; the user can drag the divider.
        body = QSplitter(Qt.Horizontal)
        body.setObjectName("FomodSplit")
        body.setChildrenCollapsible(False)
        body.setHandleWidth(6)

        left = QWidget(); left.setObjectName("FormBody")
        lv = QVBoxLayout(left); lv.setContentsMargins(14, 14, 14, 14); lv.setSpacing(10)
        self._image = QLabel()
        self._image.setAlignment(Qt.AlignCenter)
        self._image.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self._image.setStyleSheet(f"background:{self._c('BG_DEEP')}; border-radius:6px;")
        # Click the image → open it full-size in a new tab.
        self._image.mousePressEvent = lambda _e: self._open_lightbox()
        # Image takes ~60% of the left panel's height, description ~40%.
        lv.addWidget(self._image, 6)
        self._desc = QLabel("")
        self._desc.setWordWrap(True)
        self._desc.setAlignment(Qt.AlignTop)
        self._desc.setStyleSheet(f"color:{self._c('TEXT_MAIN')};")
        desc_scroll = QScrollArea(); desc_scroll.setWidgetResizable(True)
        desc_scroll.setFrameShape(QFrame.NoFrame); desc_scroll.setWidget(self._desc)
        lv.addWidget(desc_scroll, 4)
        body.addWidget(left)

        self._opts_scroll = QScrollArea(); self._opts_scroll.setWidgetResizable(True)
        self._opts_scroll.setFrameShape(QFrame.NoFrame)
        self._opts_host = QWidget()
        self._opts_layout = QVBoxLayout(self._opts_host)
        self._opts_layout.setContentsMargins(18, 14, 18, 14)
        self._opts_layout.setSpacing(14)
        self._opts_layout.setAlignment(Qt.AlignTop)
        self._opts_scroll.setWidget(self._opts_host)
        body.addWidget(self._opts_scroll)
        # Selections side bigger by default (~40/60); both panes resizable.
        body.setStretchFactor(0, 4)
        body.setStretchFactor(1, 6)
        body.setSizes([440, 680])
        outer.addWidget(body, 1)

        # Button bar.
        bar = QWidget(); bar.setObjectName("BottomBar")
        bb = QHBoxLayout(bar); bb.setContentsMargins(12, 8, 12, 8)
        self._err = QLabel("")
        self._err.setStyleSheet(f"color:{self._c('TEXT_ERR')};")
        bb.addWidget(self._err)
        bb.addStretch(1)
        self._back_btn = QPushButton("Back"); self._back_btn.setObjectName("FormButton")
        self._back_btn.setCursor(Qt.PointingHandCursor)
        self._back_btn.clicked.connect(self._on_back)
        bb.addWidget(self._back_btn)
        self._next_btn = QPushButton("Next"); self._next_btn.setObjectName("PrimaryButton")
        self._next_btn.setCursor(Qt.PointingHandCursor)
        self._next_btn.clicked.connect(self._on_next)
        bb.addWidget(self._next_btn)
        cancel = QPushButton("Cancel"); cancel.setObjectName("FormButton")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(lambda: self._on_cancel())
        bb.addWidget(cancel)
        outer.addWidget(bar)

    # ---- step flow --------------------------------------------------------
    def _config_step_idx(self, step) -> int:
        for i, s in enumerate(self._config.steps):
            if s is step:
                return i
        return 0

    def _refresh_visible_steps(self):
        try:
            self._visible_steps = get_visible_steps(
                self._config, self._flag_state, self._installed)
        except Exception:
            self._visible_steps = list(self._config.steps)
        if not self._visible_steps:
            self._visible_steps = list(self._config.steps)

    def _load_step(self, idx: int):
        self._cur = max(0, min(idx, len(self._visible_steps) - 1))
        step = self._visible_steps[self._cur]
        step_key = str(self._config_step_idx(step))
        # Clear option widgets.
        while self._opts_layout.count():
            item = self._opts_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._group_state = {}

        # Default selections for this step if not already chosen.
        saved = self._all_selections.get(step_key)
        if saved is None:
            try:
                saved = get_default_selections(step, self._flag_state, self._installed)
            except Exception:
                saved = {}

        # Show the description/image of the first SELECTED option (so a restored
        # choice is reflected on the left), falling back to the first plugin.
        selected_plugin = None
        first_plugin = None
        for group in step.groups:
            sel_names = saved.get(group.name, [])
            self._build_group(group, sel_names)
            if first_plugin is None and group.plugins:
                first_plugin = group.plugins[0]
            if selected_plugin is None:
                for p in group.plugins:
                    if p.name in sel_names:
                        selected_plugin = p
                        break
        self._show_plugin(selected_plugin or first_plugin)

        total = len(self._visible_steps)
        self._step_lbl.setText(f"Step {self._cur + 1} of {total}")
        self._back_btn.setEnabled(self._cur > 0)
        self._next_btn.setText("Finish" if self._cur >= total - 1 else "Next")
        self._err.setText("")

    def _build_group(self, group, selected_names):
        gtype = group.group_type
        box = QFrame(); box.setObjectName("FomodGroup")
        box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bl = QVBoxLayout(box); bl.setContentsMargins(16, 14, 16, 14); bl.setSpacing(10)
        gl = QLabel(group.name)
        gl.setObjectName("FomodGroupTitle")
        bl.addWidget(gl)

        controls = []
        if gtype in ("SelectExactlyOne", "SelectAtMostOne"):
            bg = QButtonGroup(box)
            bg.setExclusive(gtype == "SelectExactlyOne")
            for plugin in group.plugins:
                rb = QRadioButton(plugin.name)
                rb.setChecked(plugin.name in selected_names)
                self._hook_hover(rb, plugin)
                bg.addButton(rb)
                bl.addWidget(rb)
                controls.append((plugin, rb))
            self._group_state[group.name] = ("radio", gtype, controls)
        else:   # SelectAtLeastOne / SelectAny / SelectAll
            for plugin in group.plugins:
                cb = QCheckBox(plugin.name)
                checked = plugin.name in selected_names or gtype == "SelectAll"
                cb.setChecked(checked)
                if gtype == "SelectAll":
                    cb.setEnabled(False)
                self._hook_hover(cb, plugin)
                bl.addWidget(cb)
                controls.append((plugin, cb))
            self._group_state[group.name] = ("check", gtype, controls)
        self._opts_layout.addWidget(box)

    def _hook_hover(self, control, plugin):
        """Show the option's image+description when the cursor HOVERS the control
        (Tk parity). Tracked via an event filter catching QEvent.Enter."""
        control._fomod_plugin = plugin
        control.installEventFilter(self)

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Enter and getattr(obj, "_fomod_plugin", None) is not None:
            self._show_plugin(obj._fomod_plugin)
        return super().eventFilter(obj, event)

    # ---- left panel -------------------------------------------------------
    def _show_plugin(self, plugin):
        self._desc.setText(plugin.description or "")
        img_rel = getattr(plugin, "image_path", "") or ""
        self._cur_pixmap = None
        self._cur_image_path = None
        if img_rel:
            img = self._base / img_rel.replace("\\", "/")
            if img.is_file():
                pm = QPixmap(str(img))
                if not pm.isNull():
                    self._cur_pixmap = pm
                    self._cur_image_path = img
        self._rescale_image()

    def _rescale_image(self):
        """Stretch the current image to fill the image label (keeping aspect)."""
        if getattr(self, "_cur_pixmap", None) is not None and not self._cur_pixmap.isNull():
            size = self._image.size()
            self._image.setStyleSheet(
                f"background:{self._c('BG_DEEP')}; border-radius:6px;")
            self._image.setCursor(Qt.PointingHandCursor)
            self._image.setToolTip("Click to view full size")
            self._image.setPixmap(self._cur_pixmap.scaled(
                size.width() - 4, size.height() - 4,
                Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self._image.clear()
            self._image.setText("No image")
            self._image.setCursor(Qt.ArrowCursor)
            self._image.setToolTip("")
            self._image.setStyleSheet(
                f"background:{self._c('BG_DEEP')}; border-radius:6px; "
                f"color:{self._c('TEXT_FAINT')};")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale_image()

    def _open_lightbox(self):
        """Open the current image full-size in a new tab (via the host window)."""
        if getattr(self, "_cur_image_path", None) is None:
            return
        # Walk up to the MainWindow that owns the tab widget.
        win = self.window()
        tabs = getattr(win, "_tabs", None)
        if tabs is None:
            return
        from gui_qt.image_view import ImageView
        view = ImageView(self._cur_image_path)
        tabs.open_tab(view, "Image", key=f"img:{self._cur_image_path}")

    # ---- selection read ---------------------------------------------------
    def _read_current_selections(self) -> dict:
        result = {}
        for group_name, (_kind, gtype, controls) in self._group_state.items():
            if gtype in ("SelectExactlyOne", "SelectAtMostOne"):
                chosen = [p.name for p, w in controls if w.isChecked()]
                result[group_name] = chosen[:1]
            elif gtype == "SelectAll":
                result[group_name] = [p.name for p, _w in controls]
            else:
                result[group_name] = [p.name for p, w in controls if w.isChecked()]
        return result

    def _save_current(self):
        step = self._visible_steps[self._cur]
        self._all_selections[str(self._config_step_idx(step))] = \
            self._read_current_selections()

    def _rebuild_flags(self):
        flag_state = {}
        for i, step in enumerate(self._config.steps):
            sels = self._all_selections.get(str(i))
            if sels is None:
                continue
            try:
                flag_state = update_flags(step, sels, flag_state)
            except Exception:
                pass
        self._flag_state = flag_state

    # ---- buttons ----------------------------------------------------------
    def _on_back(self):
        if self._cur <= 0:
            return
        self._save_current()
        self._cur -= 1
        self._load_step(self._cur)

    def _on_next(self):
        self._save_current()
        step = self._visible_steps[self._cur]
        sels = self._all_selections.get(str(self._config_step_idx(step)), {})
        try:
            errors = validate_selections(step, sels, self._flag_state, self._installed)
        except Exception:
            errors = []
        if errors:
            self._err.setText(errors[0])
            return
        self._err.setText("")
        self._rebuild_flags()
        self._refresh_visible_steps()

        # Find where the current step now sits in the (possibly changed) list.
        try:
            new_idx = self._visible_steps.index(step)
        except ValueError:
            new_idx = self._cur
        if new_idx >= len(self._visible_steps) - 1:
            # Last visible step → finish.
            self._on_finish(self._all_selections)
            return
        self._load_step(new_idx + 1)
