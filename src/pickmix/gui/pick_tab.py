'''
pickmix: Pick tab
'''

# Import external dependencies
import numpy as np
from concurrent.futures import Future
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QHBoxLayout, QLabel, QPushButton,
    QSlider, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

# Import internal pickmix objects
from pickmix.estimates import EstimateService
from pickmix.gui.canvas import FitView, Marker, SliceCanvas
from pickmix.geometry import Parent, match_parents
from pickmix.gui.workers import post
from pickmix.loader import Loader, Opened
from pickmix.model import Session
from pickmix.timing import Timer

# _STEPS: positions on the contrast sliders
_STEPS: int = 1000

# PickTab: canvas, kind buttons, z and contrast sliders, and the pick list of the current tomogram
class PickTab(QWidget):
    # __init__: build the layout
    def __init__(self) -> None:
        super().__init__()
        self.session: Session | None = None
        self.loader: Loader | None = None
        self.service: EstimateService | None = None
        self._want_select: int | None = None
        self._matched: dict[str, dict[int, Parent]] = {}
        self.opened: Opened | None = None
        self.active: str | None = None
        self.hidden: set[str] = set()
        self.z = 0
        self._timer: Timer | None = None
        self._first_slice = False
        self._range = (0.0, 1.0)
        self.canvas = SliceCanvas()
        self.title = QLabel()
        self.status = QLabel()
        self.kind_row = QHBoxLayout()
        self.kind_buttons: dict[str, QPushButton] = {}
        self.kind_boxes: dict[str, QCheckBox] = {}
        self.group = QButtonGroup(self)
        self.z_slider = QSlider(Qt.Orientation.Horizontal)
        self.z_label = QLabel()
        self.lo_slider = QSlider(Qt.Orientation.Horizontal)
        self.hi_slider = QSlider(Qt.Orientation.Horizontal)
        for slider in (self.lo_slider, self.hi_slider):
            slider.setRange(0, _STEPS)
        self.rings_box = QCheckBox('Rings')
        self.boxes_box = QCheckBox('Boxes')
        self.normals_box = QCheckBox('Normals')
        for box in (self.rings_box, self.boxes_box, self.normals_box):
            box.setChecked(True)
            box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.invert_box = QCheckBox('Invert')
        self.auto_button = QPushButton('Auto')
        self.fit_button = QPushButton('Fit')
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['Kind', 'x', 'y', 'z', 'SNR', 'Flag'])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setMaximumWidth(380)
        self.delete_button = QPushButton('Delete selected')
        for button in (self.auto_button, self.fit_button, self.delete_button):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._row_ids: list[int] = []
        z_row = QHBoxLayout()
        z_row.addWidget(QLabel('Slice'))
        z_row.addWidget(self.z_slider, 1)
        z_row.addWidget(self.z_label)
        contrast_row = QHBoxLayout()
        contrast_row.addWidget(QLabel('Contrast'))
        contrast_row.addWidget(self.lo_slider, 1)
        contrast_row.addWidget(self.hi_slider, 1)
        contrast_row.addWidget(self.rings_box)
        contrast_row.addWidget(self.boxes_box)
        contrast_row.addWidget(self.normals_box)
        contrast_row.addWidget(self.invert_box)
        contrast_row.addWidget(self.auto_button)
        contrast_row.addWidget(self.fit_button)
        side = QVBoxLayout()
        side.addWidget(self.table, 1)
        side.addWidget(self.delete_button)
        middle = QHBoxLayout()
        middle.addWidget(self.canvas, 1)
        middle.addLayout(side)
        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addLayout(self.kind_row)
        layout.addLayout(middle, 1)
        layout.addLayout(z_row)
        layout.addLayout(contrast_row)
        layout.addWidget(self.status)
        self.z_slider.valueChanged.connect(self._show_z)
        self.lo_slider.valueChanged.connect(self._on_window)
        self.hi_slider.valueChanged.connect(self._on_window)
        self.invert_box.toggled.connect(self._on_window)
        self.rings_box.toggled.connect(self._on_overlay)
        self.boxes_box.toggled.connect(self._on_overlay)
        self.normals_box.toggled.connect(self._on_overlay)
        self.auto_button.clicked.connect(self._auto)
        self.fit_button.clicked.connect(self.canvas.fit)
        self.delete_button.clicked.connect(self.delete_selected)
        self.canvas.add_requested.connect(self._add)
        self.canvas.move_requested.connect(self._move)
        self.canvas.marker_clicked.connect(self._clicked)
        self.canvas.z_scrolled.connect(lambda steps: self.z_slider.setValue(self.z_slider.value() + steps))
        self.table.cellClicked.connect(self._row_clicked)
        for i in range(1, 10):
            QShortcut(QKeySequence(str(i)), self, context=Qt.ShortcutContext.WidgetWithChildrenShortcut).activated.connect(
                lambda i=i: self._pick_kind(i - 1)
            )
        for key in ('Delete', 'Backspace'):
            QShortcut(QKeySequence(key), self, context=Qt.ShortcutContext.WidgetWithChildrenShortcut).activated.connect(self.delete_selected)

    # set_session: show a session and follow its picks and navigation
    def set_session(self, session: Session, loader: Loader, service: EstimateService) -> None:
        self.session, self.loader, self.service = session, loader, service
        session.store.listeners.append(self._on_picks)
        # estimates arrive on the service's thread
        service.store.listeners.append(lambda: post(self._on_picks))
        session.goto_listeners.append(self._on_goto)
        self.refresh_kinds()
        self._on_goto()

    # refresh_kinds: rebuild the kind buttons from the config, keeping the active kind if it still exists
    def refresh_kinds(self) -> None:
        if self.session is None:
            return
        for button in self.kind_buttons.values():
            self.group.removeButton(button)
        while self.kind_row.count():
            widget = self.kind_row.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        self.kind_buttons, self.kind_boxes = {}, {}
        kinds = self.session.project.config.kinds
        self.hidden &= set(kinds)
        # key number of each kind that has a hotkey
        keys = {name: i + 1 for i, name in enumerate(self.session.project.config.hotkeys) if name}
        for name, kind in kinds.items():
            button = QPushButton(f'{keys[name]} {name}' if name in keys else name)
            button.setCheckable(True)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setStyleSheet(f'QPushButton {{ border-bottom: 4px solid {kind.colour}; padding: 4px 10px; }}')
            button.clicked.connect(lambda _checked=False, n=name: self._set_active(n))
            box = QCheckBox('show')
            box.setChecked(name not in self.hidden)
            box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            box.toggled.connect(lambda shown, n=name: self._toggle_kind(n, shown))
            self.group.addButton(button)
            self.kind_buttons[name], self.kind_boxes[name] = button, box
            self.kind_row.addWidget(button)
            self.kind_row.addWidget(box)
        self.kind_row.addStretch()
        self._set_active(self.active if self.active in kinds else next(iter(kinds)))
        self._on_picks()

    # show_pick: go to a pick, in whichever tomogram it is, and select it
    def show_pick(self, pick_id: int) -> None:
        assert self.session is not None
        pick = self.session.store.get(pick_id)
        if pick.tomogram == self.session.current and self.opened is not None:
            self._clicked(pick_id)
            return
        self._want_select = pick_id
        if pick.tomogram != self.session.current:
            self.session.go(self.session.names.index(pick.tomogram))

    # delete_selected: remove the selected pick
    def delete_selected(self) -> None:
        if self.session is not None and self.canvas.selected_id is not None:
            self.session.store.remove(self.canvas.selected_id)

    # _set_active: kind new picks are made as
    def _set_active(self, name: str) -> None:
        self.active = name
        self.kind_buttons[name].setChecked(True)

    # _pick_kind: choose the kind on the i-th hotkey
    def _pick_kind(self, i: int) -> None:
        name = self.session.project.config.hotkeys[i] if self.session is not None else ''
        if name in self.kind_buttons:
            self._set_active(name)

    # _toggle_kind: show or hide a kind's markers
    def _toggle_kind(self, name: str, shown: bool) -> None:
        self.hidden.discard(name) if shown else self.hidden.add(name)
        self._on_picks()

    # _on_goto: a different tomogram is wanted; clear the view and start loading
    def _on_goto(self) -> None:
        assert self.session is not None and self.loader is not None
        name = self.session.current
        self.opened = None
        self.canvas.clear()
        self.title.setText(f'{name}  ({self.session.index + 1}/{len(self.session.names)})   Enter next, Shift+Enter back')
        self.status.setText(f'Loading {name}...')
        self._fill_table()
        self._timer = Timer(f'switch to {name}')
        # the dispatcher must exist before worker threads post to it
        post(lambda: None)
        future = self.loader.open(name)
        future.add_done_callback(lambda f: post(lambda: self._open_done(name, f)))

    # _open_done: the tomogram is mapped; set the sliders, show the middle slice and start prefetching the next one
    def _open_done(self, name: str, future: Future[Opened]) -> None:
        assert self.session is not None and self.loader is not None
        if name != self.session.current:
            return
        try:
            self.opened = future.result()
        except Exception as e:
            self.status.setText(f'Could not open {name}: {type(e).__name__}: {e}')
            return
        if self._timer:
            self._timer.lap('opened and contrast')
        lo, hi = self.opened.limits
        span = (hi - lo) or 1.0
        self._range = (lo - 2 * span, hi + 2 * span)
        depth = self.opened.vol.shape[0]
        self._quiet(self.lo_slider, self._slider_pos(lo))
        self._quiet(self.hi_slider, self._slider_pos(hi))
        self.z_slider.blockSignals(True)
        self.z_slider.setRange(0, depth - 1)
        self.z_slider.setValue(depth // 2)
        self.z_slider.blockSignals(False)
        self.status.setText('')
        self._first_slice = True
        self._matched = self._match()
        self.canvas.set_markers(self._markers())
        self._on_overlay()
        self._show_z(depth // 2)
        if self._want_select is not None:
            wanted, self._want_select = self._want_select, None
            self._clicked(wanted)
        if self.session.index + 1 < len(self.session.names):
            self.loader.prefetch(self.session.names[self.session.index + 1])

    # _show_z: show slice z, from the cache or after reading it in the background
    def _show_z(self, z: int) -> None:
        if self.opened is None or self.loader is None:
            return
        name = self.opened.name
        self.z = z
        self.z_label.setText(f'{z + 1} / {self.opened.vol.shape[0]}')
        self.canvas.set_z(z)
        cached = self.loader.cached(name, z)
        if cached is not None:
            self._render(cached)
            return
        future = self.loader.fetch(name, z)
        future.add_done_callback(lambda f: post(lambda: self._slice_done(name, z, f)))

    # _slice_done: a slice read finished; show it if it is still the one wanted
    def _slice_done(self, name: str, z: int, future: Future[np.ndarray]) -> None:
        if self.opened is None or self.opened.name != name or self.z != z:
            return
        try:
            self._render(future.result())
        except Exception as e:
            self.status.setText(f'Could not read slice {z + 1}: {type(e).__name__}: {e}')

    # _render: draw a slice with the current window; the first one of a tomogram also fits the view
    def _render(self, arr: np.ndarray) -> None:
        assert self.opened is not None and self.loader is not None
        lo, hi = self._window()
        self.canvas.set_image(arr, lo, hi, invert=self.invert_box.isChecked())
        if self._first_slice:
            self._first_slice = False
            self.canvas.fit()
            if self._timer:
                self._timer.lap('first slice shown')
        self.loader.warm_around(self.opened.name, self.z)

    # _window: contrast limits from the sliders
    def _window(self) -> tuple[float, float]:
        lo, hi = (self._slider_value(s.value()) for s in (self.lo_slider, self.hi_slider))
        return (lo, hi) if hi > lo else (lo, lo + 1e-6)

    # _on_overlay: fit rings or boxes switched
    def _on_overlay(self) -> None:
        self.canvas.set_overlay(rings=self.rings_box.isChecked(), boxes=self.boxes_box.isChecked(), normals=self.normals_box.isChecked())

    # _on_window: contrast or invert changed
    def _on_window(self) -> None:
        lo, hi = self._window()
        self.canvas.set_window(lo, hi, invert=self.invert_box.isChecked())

    # _auto: contrast back to the limits found when the tomogram opened
    def _auto(self) -> None:
        if self.opened is not None:
            self._quiet(self.lo_slider, self._slider_pos(self.opened.limits[0]))
            self._quiet(self.hi_slider, self._slider_pos(self.opened.limits[1]))
            self._on_window()

    # _slider_pos: slider position for a pixel value
    def _slider_pos(self, value: float) -> int:
        lo, hi = self._range
        return round((value - lo) / (hi - lo) * _STEPS)

    # _slider_value: pixel value for a slider position
    def _slider_value(self, pos: int) -> float:
        lo, hi = self._range
        return lo + pos / _STEPS * (hi - lo)

    # _quiet: set a slider without triggering its handlers
    def _quiet(self, slider: QSlider, value: int) -> None:
        slider.blockSignals(True)
        slider.setValue(value)
        slider.blockSignals(False)

    # _on_picks: picks changed; redraw markers and the list
    def _on_picks(self) -> None:
        if self.session is None:
            return
        self._fill_table()
        if self.opened is not None:
            self.canvas.set_markers(self._markers())
            self.status.setText(f'Estimating {self.service.pending}...' if self.service and self.service.pending else '')

    # _match: parent geometry for the picks of the current tomogram, per kind that has a parent
    def _match(self) -> dict[str, dict[int, Parent]]:
        assert self.session is not None
        if self.service is None:
            return {}
        config, project = self.session.project.config, self.session.project
        return {
            name: match_parents(name, config, self.session.store, self.service.store, project.tomos, tomogram=self.session.current)
            for name, kind in config.kinds.items() if kind.parent is not None
        }

    # _markers: markers for the visible kinds of the current tomogram
    def _markers(self) -> list[Marker]:
        assert self.session is not None
        name = self.session.current
        px = self.session.project.tomos[name].pixel_size
        out = []
        for kind_name, kind in self.session.project.config.kinds.items():
            if kind_name in self.hidden:
                continue
            for p in self.session.store.picks(name, kind_name):
                fit = self.service.store.get(p) if self.service else None
                view = None if fit is None else FitView(
                    fit.x, fit.y, fit.z, fit.radius_a / px if kind.estimator != 'none' else None,
                    fit.box_a / px if fit.box_a > 0 else None, fit.z_lo, fit.z_hi,
                )
                parent = self._matched.get(kind_name, {}).get(p.id)
                unmatched = kind.parent is not None and fit is not None and parent is None
                normal = None if parent is None else (parent.normal[0], parent.normal[1])
                out.append(Marker(p.id, p.x, p.y, p.z, kind.marker_a / 2 / px, kind.colour, bool(fit and fit.flag) or unmatched, view, normal))
        return out

    # _fill_table: the current tomogram's picks of known kinds, with the selected one highlighted
    def _fill_table(self) -> None:
        assert self.session is not None
        name = self.session.current
        kinds = self.session.project.config.kinds
        picks = [p for k in kinds for p in self.session.store.picks(name, k)]
        self._matched = self._match()
        self._row_ids = [p.id for p in picks]
        self.table.setRowCount(len(picks))
        for r, p in enumerate(picks):
            fit = self.service.store.get(p) if self.service else None
            snr, flag = ('', '') if fit is None else (f'{fit.snr:.2f}', fit.flag)
            if fit is not None and kinds[p.kind].parent is not None and p.id not in self._matched.get(p.kind, {}):
                flag = ','.join(filter(None, [flag, 'noparent']))
            for c, text in enumerate((p.kind, f'{p.x:.1f}', f'{p.y:.1f}', f'{p.z:.1f}', snr, flag)):
                self.table.setItem(r, c, QTableWidgetItem(text))
        self._select(self.canvas.selected_id)

    # _select: highlight a pick in the canvas and the list
    def _select(self, pick_id: int | None) -> None:
        self.canvas.select(pick_id)
        if pick_id in self._row_ids:
            self.table.selectRow(self._row_ids.index(pick_id))
        else:
            self.table.clearSelection()

    # _add: new pick of the active kind on the current slice
    def _add(self, x: float, y: float) -> None:
        if self.session is None or self.opened is None or self.active is None:
            return
        pick = self.session.store.add(self.opened.name, self.active, x, y, float(self.z))
        self._select(pick.id)

    # _move: pick dragged to a new position, on the same slice it was picked on
    def _move(self, pick_id: int, x: float, y: float) -> None:
        if self.session is not None:
            self.session.store.move(pick_id, x, y)
            self._select(pick_id)

    # _clicked: pick selected on the canvas; show the slice it was picked on
    def _clicked(self, pick_id: int) -> None:
        assert self.session is not None
        self._select(pick_id)
        self.z_slider.setValue(round(self.session.store.get(pick_id).z))

    # _row_clicked: pick chosen in the list
    def _row_clicked(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._row_ids):
            self._clicked(self._row_ids[row])
