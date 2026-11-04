'''
pickmix: Pick tab
'''

# Import external dependencies
import numpy as np
from concurrent.futures import Future
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QScrollBar, QSlider, QSplitter, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

# Import internal pickmix objects
from pickmix.estimates import EstimateService
from pickmix.geometry import Parent, match_parents
from pickmix.gui.components.canvas import FitView, Marker, SliceCanvas
from pickmix.gui.components.icons import icon
from pickmix.gui.components.range_slider import RangeSlider
from pickmix.gui.components.status import StatusBadge, fit_status
from pickmix.gui.panes.tomo_pane import TomoPane
from pickmix.gui.workers import post
from pickmix.gui.style import bold_safe, eye_toggle, heading, hint, tidy, title, view_toggle
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
        self.title = title()
        self.help = hint('Enter: next tomogram. Shift+Enter: previous tomogram.')
        self.status = QLabel()
        self.tomo = TomoPane()
        self.tomo.setMinimumWidth(200)
        self.tomo_toggle = QToolButton()
        self.tomo_toggle.setAutoRaise(True)
        self.tomo_toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tomo_toggle.clicked.connect(lambda: self.set_tomo_visible(self.tomo.isHidden()))
        self.kind_box = QVBoxLayout()
        self.kind_buttons: dict[str, QPushButton] = {}
        self.kind_toggles: dict[str, QPushButton] = {}
        self.group = QButtonGroup(self)
        self.z_slider = QScrollBar(Qt.Orientation.Vertical)
        self.z_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.z_label = QLabel()
        self.contrast = RangeSlider(0, _STEPS)
        self.brightness = QSlider(Qt.Orientation.Horizontal)
        self.brightness.setRange(-100, 100)
        self.auto_box = QCheckBox('Auto')
        self.auto_box.setChecked(True)
        self.rings_box = view_toggle('Rings')
        self.boxes_box = view_toggle('Boxes')
        self.normals_box = view_toggle('Normals')
        for box in (self.rings_box, self.boxes_box, self.normals_box):
            box.setChecked(True)
            box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.invert_box = QCheckBox('Invert')
        self.fit_button = QPushButton('Fit')
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(['', 'Kind', 'x', 'y', 'z', 'SNR', 'Flag'])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setMaximumHeight(170)
        # status marker first and fixed so kinds always line up; Kind fits its names, the number columns share the rest
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(0, 28)
        self.delete_button = QPushButton()
        trash = icon('delete')
        if trash is None:
            self.delete_button.setText('Delete')
        else:
            self.delete_button.setIcon(trash)
        self.delete_button.setToolTip('Delete the selected pick (Delete)')
        for button in (self.fit_button, self.delete_button):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._row_ids: list[int] = []
        # settings pane on the right: image controls, what to show, then the kinds
        image = QGroupBox('Image')
        image_form = QFormLayout(image)
        image_form.addRow('Contrast', self.contrast)
        image_form.addRow('Brightness', self.brightness)
        checks = QHBoxLayout()
        checks.addWidget(self.auto_box)
        checks.addWidget(self.invert_box)
        image_form.addRow(checks)
        image_form.addRow(self.fit_button)
        view = QGroupBox('View')
        view_grid = QGridLayout(view)
        for i, box in enumerate((self.rings_box, self.boxes_box, self.normals_box)):
            view_grid.addWidget(box, i // 2, i % 2)
        kinds = QGroupBox('Kinds')
        kinds.setLayout(self.kind_box)
        self.settings = QWidget()
        self.settings.setFixedWidth(220)
        settings_layout = QVBoxLayout(self.settings)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.addWidget(image)
        settings_layout.addWidget(view)
        settings_layout.addWidget(kinds)
        settings_layout.addStretch()
        # vertical Z scrollbar between the canvas and the settings
        z_column = QVBoxLayout()
        z_column.addWidget(QLabel('Z'))
        z_column.addWidget(self.z_slider, 1)
        z_column.addWidget(self.z_label)
        middle = QHBoxLayout()
        middle.addWidget(self.canvas, 1)
        middle.addLayout(z_column)
        middle.addWidget(self.settings)
        # pick table under the canvas, with a Picks heading and the delete button level with it on the right
        picks_head = QHBoxLayout()
        picks_head.addWidget(heading('Picks'))
        picks_head.addStretch()
        picks_head.addWidget(self.delete_button)
        bottom = QVBoxLayout()
        bottom.addLayout(picks_head)
        bottom.addWidget(self.table)
        # picking area: kinds, canvas and settings, picks table
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addLayout(middle, 1)
        content_layout.addLayout(bottom)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.tomo)
        self.splitter.addWidget(content)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([260, 1000])
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(self.title)
        names.addWidget(self.help)
        head = QHBoxLayout()
        head.addWidget(self.tomo_toggle, alignment=Qt.AlignmentFlag.AlignTop)
        head.addLayout(names, 1)
        layout = QVBoxLayout(self)
        tidy(layout)
        layout.addLayout(head)
        layout.addWidget(self.splitter, 1)
        layout.addWidget(self.status)
        self.set_tomo_visible(True)
        self.z_slider.valueChanged.connect(self._show_z)
        self.contrast.valueChanged.connect(self._edited)
        self.brightness.valueChanged.connect(self._edited)
        self.invert_box.toggled.connect(self._on_window)
        self.auto_box.toggled.connect(self._auto_toggled)
        self.rings_box.toggled.connect(self._on_overlay)
        self.boxes_box.toggled.connect(self._on_overlay)
        self.normals_box.toggled.connect(self._on_overlay)
        self.fit_button.clicked.connect(self.canvas.fit)
        self.delete_button.clicked.connect(self.delete_selected)
        self.canvas.add_requested.connect(self._add)
        self.canvas.move_requested.connect(self._move)
        self.canvas.marker_clicked.connect(self._clicked)
        self.canvas.z_scrolled.connect(lambda steps: self.z_slider.setValue(self.z_slider.value() + steps))
        self.table.cellClicked.connect(self._row_clicked)

    # set_session: show a session and follow its picks and navigation
    def set_session(self, session: Session, loader: Loader, service: EstimateService) -> None:
        self.session, self.loader, self.service = session, loader, service
        session.store.listeners.append(self._on_picks)
        # estimates arrive on the service's thread
        service.store.listeners.append(lambda: post(self._on_picks))
        session.goto_listeners.append(self._on_goto)
        self.tomo.set_session(session)
        self.refresh_kinds()
        self._on_goto()

    # refresh_kinds: rebuild the hotkeys row from the config, keeping the active kind if it still exists
    def refresh_kinds(self) -> None:
        if self.session is None:
            return
        for button in self.kind_buttons.values():
            self.group.removeButton(button)
        while self.kind_box.count():
            widget = self.kind_box.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        self.kind_buttons, self.kind_toggles = {}, {}
        kinds = self.session.project.config.kinds
        self.hidden &= set(kinds)
        # key number of each kind that has a hotkey
        keys = {name: i + 1 for i, name in enumerate(self.session.project.config.hotkeys) if name}
        for name, kind in kinds.items():
            # first button selects kind
            key = QPushButton(f'({keys[name]}) {name}' if name in keys else name)
            key.setCheckable(True)
            key.setFlat(True)
            key.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            key.setCursor(Qt.CursorShape.PointingHandCursor)
            bold_safe(key)
            key.clicked.connect(lambda _checked=False, n=name: self._set_active(n))
            # second button shows/hides markers
            toggle = QToolButton()
            toggle.setCheckable(True)
            toggle.setChecked(name not in self.hidden)
            toggle.setAutoRaise(True)
            toggle.setStyleSheet('QToolButton { border: none; background: transparent; }')
            toggle.setCursor(Qt.CursorShape.PointingHandCursor)
            toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            toggle.setToolTip(f'Show or hide {name}')
            eye_toggle(toggle, toggle.isChecked())
            toggle.toggled.connect(lambda shown, n=name, t=toggle: (eye_toggle(t, shown), self._toggle_kind(n, shown)))
            self.group.addButton(key)
            self.kind_buttons[name], self.kind_toggles[name] = key, toggle
            # add rounded border in kind's colour around both buttons
            pair = QFrame()
            pair.setObjectName('pair')
            pair.setStyleSheet(f'QFrame#pair {{ border: 2px solid {kind.colour}; border-radius: 8px; }}')
            pair_row = QHBoxLayout(pair)
            pair_row.setContentsMargins(4, 2, 4, 2)
            pair_row.setSpacing(0)
            pair_row.addWidget(key)
            pair_row.addWidget(toggle)
            self.kind_box.addWidget(pair)
        # no kinds leaves nothing to pick as
        if kinds:
            self._set_active(self.active if self.active in kinds else next(iter(kinds)))
        else:
            self.active = None
        self._on_picks()
        self.tomo.refresh()

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

    # set_tomo_visible: show or hide the tomogram pane; the icon is the action the button takes
    def set_tomo_visible(self, shown: bool) -> None:
        self.tomo.setVisible(shown)
        panel = icon('left_panel_close' if shown else 'left_panel_open')
        if panel is None:
            self.tomo_toggle.setText('<' if shown else '>')
        else:
            self.tomo_toggle.setIcon(panel)
        self.tomo_toggle.setToolTip('Hide the tomogram list' if shown else 'Show the tomogram list')

    # delete_selected: remove the selected pick
    def delete_selected(self) -> None:
        if self.session is not None and self.canvas.selected_id is not None:
            self.session.store.remove(self.canvas.selected_id)

    # _set_active: kind new picks are made as
    def _set_active(self, name: str) -> None:
        self.active = name
        self.kind_buttons[name].setChecked(True)

    # pick_kind: choose the kind on the i-th hotkey
    def pick_kind(self, i: int) -> None:
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
        self.title.setText(name)
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
        # Auto takes the tomogram's own limits; with Auto off the window you set is kept in pixel values
        keep = None if self.auto_box.isChecked() else self._raw_window()
        lo, hi = self.opened.limits
        span = (hi - lo) or 1.0
        self._range = (lo - 2 * span, hi + 2 * span)
        depth = self.opened.vol.shape[0]
        low, high = self.opened.limits if keep is None else keep
        self.contrast.set_values(self._slider_pos(low), self._slider_pos(high))
        if keep is None:
            self._quiet(self.brightness, 0)
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
        total = self.opened.vol.shape[0]
        # as wide as the longest text it will show, so scrolling never changes the layout
        self.z_label.setFixedWidth(self.z_label.fontMetrics().horizontalAdvance(f'{total} / {total}') + 8)
        self.z_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.z_label.setText(f'{z + 1} / {total}')
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

    # _raw_window: contrast limits from the range slider, before brightness
    def _raw_window(self) -> tuple[float, float]:
        low, high = self.contrast.values()
        return self._slider_value(low), self._slider_value(high)

    # _window: the window the canvas uses: the contrast limits moved down by the brightness, a percentage of their width
    def _window(self) -> tuple[float, float]:
        lo, hi = self._raw_window()
        shift = self.brightness.value() / 100 * (hi - lo)
        lo, hi = lo - shift, hi - shift
        return (lo, hi) if hi > lo else (lo, lo + 1e-6)

    # _on_overlay: fit rings or boxes switched
    def _on_overlay(self) -> None:
        self.canvas.set_overlay(rings=self.rings_box.isChecked(), boxes=self.boxes_box.isChecked(), normals=self.normals_box.isChecked())

    # _on_window: contrast, brightness or invert changed
    def _on_window(self, *_args: object) -> None:
        lo, hi = self._window()
        self.canvas.set_window(lo, hi, invert=self.invert_box.isChecked())

    # _edited: contrast or brightness changed by hand, so Auto goes off
    def _edited(self, *_args: object) -> None:
        if self.auto_box.isChecked():
            self.auto_box.blockSignals(True)
            self.auto_box.setChecked(False)
            self.auto_box.blockSignals(False)
        self._on_window()

    # _auto_toggled: ticking Auto goes back to the limits found when the tomogram opened
    def _auto_toggled(self, on: bool) -> None:
        if on:
            self._auto()

    # _auto: contrast back to the limits found when the tomogram opened, brightness back to zero
    def _auto(self) -> None:
        if self.opened is not None:
            self.contrast.set_values(self._slider_pos(self.opened.limits[0]), self._slider_pos(self.opened.limits[1]))
            self._quiet(self.brightness, 0)
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

    # _fill_table: the current tomogram's picks of known kinds, each with its estimate status, and the selected one highlighted
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
            status = fit_status(self.service.store.state(p) if self.service else 'ok', flag)
            tip = {'running': 'Estimating...', 'ok': 'Estimate is fine'}.get(status, flag)
            self.table.setCellWidget(r, 0, StatusBadge(status, tip))
            for c, text in enumerate((p.kind, f'{p.x:.1f}', f'{p.y:.1f}', f'{p.z:.1f}', snr, flag), start=1):
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
