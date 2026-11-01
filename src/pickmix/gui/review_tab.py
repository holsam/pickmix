'''
pickmix: Review tab, every pick with filters, a preview of the selected pick, and export and extraction per kind
'''

# Import external dependencies
import numpy as np
from collections.abc import Callable
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QGroupBox, QHBoxLayout, QLabel, QMessageBox,
    QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

# Import internal pickmix objects
from pickmix.estimate.registry import Fit
from pickmix.estimates import EstimateService
from pickmix.export import Item, export_kind, recommend_box
from pickmix.extract import extract_kind
from pickmix.geometry import Parent, match_parents
from pickmix.gui.workers import post, run_in_background
from pickmix.loader import Loader
from pickmix.model import Pick, Session

# _COLUMNS: pick table headings
_COLUMNS: list[str] = ['Tomogram', 'Kind', 'x', 'y', 'z', 'SNR', 'Flag', 'Estimate']

# _KIND_COLUMNS: per-kind export table headings
_KIND_COLUMNS: list[str] = ['Kind', 'Picks', 'Estimated', 'Flagged', 'Box (A)', 'Box (px)', 'Extract A/px', 'Min SNR', 'Drop flagged']

# _CROP: half-width in voxels of the preview crops
_CROP: int = 64

# _PREVIEW: edge in pixels of the preview images
_PREVIEW: int = 256

# _ANY_SNR: minimum of the SNR filter, shown as "any"
_ANY_SNR: float = -1000.0

# ReviewTab: pick table and filters above, preview beside, export and extraction below
class ReviewTab(QWidget):
    # open_pick: a row was double-clicked, tomogram name and pick id
    open_pick = Signal(str, int)

    # __init__: build the layout
    def __init__(self) -> None:
        super().__init__()
        self.session: Session | None = None
        self.loader: Loader | None = None
        self.service: EstimateService | None = None
        self._shown: list[Pick] = []
        self._token = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.refresh)
        self.kind_filter = QComboBox()
        self.tomo_filter = QComboBox()
        self.flagged_box = QCheckBox('Flagged only')
        self.snr_spin = QDoubleSpinBox()
        self.snr_spin.setRange(_ANY_SNR, 1000.0)
        self.snr_spin.setValue(_ANY_SNR)
        self.snr_spin.setSpecialValueText('any')
        self.count_label = QLabel()
        self.delete_button = QPushButton('Delete shown flagged')
        self.reestimate_button = QPushButton('Re-estimate all')
        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.xy_label = QLabel('xy')
        self.xz_label = QLabel('xz')
        for label in (self.xy_label, self.xz_label):
            label.setFixedSize(_PREVIEW, _PREVIEW)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet('background: #141414; color: #888')
        self.kinds_table = QTableWidget(0, len(_KIND_COLUMNS))
        self.kinds_table.setHorizontalHeaderLabels(_KIND_COLUMNS)
        self.kinds_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.kinds_table.setMaximumHeight(160)
        self._spins: dict[str, QDoubleSpinBox] = {}
        self._drops: dict[str, QCheckBox] = {}
        self.export_button = QPushButton('Export star files')
        self.extract_button = QPushButton('Extract boxes')
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(110)
        filters = QHBoxLayout()
        for text, widget in (('Kind', self.kind_filter), ('Tomogram', self.tomo_filter), ('Min SNR', self.snr_spin)):
            filters.addWidget(QLabel(text))
            filters.addWidget(widget)
        filters.addWidget(self.flagged_box)
        filters.addWidget(self.count_label, 1)
        filters.addWidget(self.delete_button)
        filters.addWidget(self.reestimate_button)
        previews = QVBoxLayout()
        previews.addWidget(self.xy_label)
        previews.addWidget(self.xz_label)
        previews.addStretch()
        body = QHBoxLayout()
        body.addWidget(self.table, 1)
        body.addLayout(previews)
        buttons = QHBoxLayout()
        buttons.addWidget(self.export_button)
        buttons.addWidget(self.extract_button)
        buttons.addStretch()
        export = QGroupBox('Export and extract')
        box = QVBoxLayout(export)
        box.addWidget(self.kinds_table)
        box.addLayout(buttons)
        box.addWidget(self.log)
        layout = QVBoxLayout(self)
        layout.addLayout(filters)
        layout.addLayout(body, 1)
        layout.addWidget(export)
        for combo in (self.kind_filter, self.tomo_filter):
            combo.currentIndexChanged.connect(self.refresh)
        self.flagged_box.toggled.connect(self.refresh)
        self.snr_spin.valueChanged.connect(self.refresh)
        self.table.itemSelectionChanged.connect(self._preview)
        self.table.cellDoubleClicked.connect(self._double_clicked)
        self.delete_button.clicked.connect(self._ask_delete_flagged)
        self.reestimate_button.clicked.connect(self._reestimate)
        self.export_button.clicked.connect(lambda: self._run(self.export_all))
        self.extract_button.clicked.connect(lambda: self._run(self.extract_all))

    # set_session: show a session and follow its picks and estimates
    def set_session(self, session: Session, loader: Loader, service: EstimateService) -> None:
        self.session, self.loader, self.service = session, loader, service
        session.store.listeners.append(self._schedule)
        service.store.listeners.append(self._schedule)
        self.refresh_kinds()

    # refresh_kinds: rebuild the kind filter and the export table from the config
    def refresh_kinds(self) -> None:
        if self.session is None:
            return
        kinds = self.session.project.config.kinds
        for combo, names in ((self.kind_filter, list(kinds)), (self.tomo_filter, self.session.names)):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(['(all)', *names])
            combo.setCurrentText(current if current in names else '(all)')
            combo.blockSignals(False)
        self._spins, self._drops = {}, {}
        self.kinds_table.setRowCount(len(kinds))
        for r, (name, kind) in enumerate(kinds.items()):
            for c in range(len(_KIND_COLUMNS)):
                self.kinds_table.setItem(r, c, QTableWidgetItem())
            self.kinds_table.item(r, 0).setText(name)
            self.kinds_table.item(r, 6).setText(f'{kind.extract_angpix:g}')
            spin = QDoubleSpinBox()
            spin.setRange(_ANY_SNR, 1000.0)
            spin.setValue(_ANY_SNR)
            spin.setSpecialValueText('any')
            drop = QCheckBox()
            self.kinds_table.setCellWidget(r, 7, spin)
            self.kinds_table.setCellWidget(r, 8, drop)
            self._spins[name], self._drops[name] = spin, drop
        self.refresh()

    # refresh: rebuild the pick table with the filters applied, and the per-kind numbers
    def refresh(self) -> None:
        if self.session is None or self.service is None:
            return
        selected = self._shown[self.table.currentRow()].id if 0 <= self.table.currentRow() < len(self._shown) else None
        rows = self._filtered()
        self._shown = [p for p, _ in rows]
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for r, (pick, fit) in enumerate(rows):
            state = self.service.store.state(pick)
            cells = [
                pick.tomogram, pick.kind, f'{pick.x:.1f}', f'{pick.y:.1f}', f'{pick.z:.1f}',
                '' if fit is None else f'{fit.snr:.2f}', '' if fit is None else fit.flag, state,
            ]
            for c, text in enumerate(cells):
                self.table.setItem(r, c, QTableWidgetItem(text))
        if selected in [p.id for p in self._shown]:
            self.table.selectRow([p.id for p in self._shown].index(selected))
        self.table.blockSignals(False)
        self.count_label.setText(f'{len(rows)} shown of {self.session.store.total()}')
        for r, (name, kind) in enumerate(self.session.project.config.kinds.items()):
            items = self._items(name)
            box_a, box_px = recommend_box(kind, items)
            for c, text in ((1, str(self.session.store.total(name))), (2, str(len(items))), (3, str(sum(bool(f.flag) for _, f in items))),
                            (4, f'{box_a:.0f}'), (5, str(box_px))):
                self.kinds_table.item(r, c).setText(text)

    # delete_flagged: remove the flagged picks currently shown
    def delete_flagged(self) -> int:
        assert self.session is not None and self.service is not None
        doomed = [p.id for p, f in self._filtered() if f is not None and f.flag]
        if doomed:
            self.session.store.remove(*doomed)
        return len(doomed)

    # export_all: write star files for every kind with current estimates; returns log lines. Runs on a worker thread, so the widget settings are passed in
    def export_all(self, settings: dict[str, tuple[float, bool]] | None = None) -> list[str]:
        assert self.session is not None
        settings = settings or self._settings()
        lines = self._preflight()
        config = self.session.project.config
        for name, kind in config.kinds.items():
            items = self._selected(name, settings)
            if not items:
                lines.append(f'{name}: nothing to export')
                continue
            try:
                s = export_kind(name, kind, items, self.session.project.tomos, config.out_dir, min_snr=settings[name][0], drop_flagged=settings[name][1], parents=self._matched(name))
            except ValueError as e:
                lines.append(str(e))
                continue
            lines.append(
                f'{name}: wrote {s.written} particles ({s.below_snr} below min SNR, {s.dropped_flagged} flagged dropped), '
                f'box {s.box_a:.0f} A = {s.box_px} px at {kind.extract_angpix:g} A/px, in {str(s.folder)!r}'
            )
        return lines

    # extract_all: cut boxes for every kind with current estimates; returns log lines. Runs on a worker thread
    def extract_all(self, settings: dict[str, tuple[float, bool]] | None = None) -> list[str]:
        assert self.session is not None
        settings = settings or self._settings()
        lines = self._preflight()
        config = self.session.project.config
        for name, kind in config.kinds.items():
            items = self._selected(name, settings)
            if not items:
                lines.append(f'{name}: nothing to extract')
                continue
            try:
                s = extract_kind(name, kind, items, self.session.project.tomos, config, log=lines.append)
            except ValueError as e:
                lines.append(str(e))
                continue
            lines.append(f'{name}: wrote {s.written} boxes of {s.box_px} px at {s.pixel_size:.2f} A/px, in {str(s.folder)!r}')
        return lines

    # _schedule: coalesce bursts of changes, from any thread, into one refresh
    def _schedule(self) -> None:
        post(lambda: self._timer.start())

    # _items: picks of a kind that have a current fit
    def _items(self, kind: str) -> list[Item]:
        assert self.session is not None and self.service is not None
        matched = self._matched(kind)
        out = []
        for pick in self.session.store.all(kind):
            fit = self.service.store.get(pick)
            if fit is not None:
                out.append((pick, self._flagged(kind, pick, fit, matched)))
        return out

    # _matched: parent geometry for every pick of a kind, empty for a kind with no parent
    def _matched(self, kind: str) -> dict[int, Parent]:
        assert self.session is not None and self.service is not None
        return match_parents(kind, self.session.project.config, self.session.store, self.service.store, self.session.project.tomos)

    # _flagged: the fit with noparent added to its flags when the pick's kind has a parent and the pick found none
    def _flagged(self, kind: str, pick: Pick, fit: Fit, matched: dict[int, Parent]) -> Fit:
        if self.session.project.config.kinds[kind].parent is None or pick.id in matched:
            return fit
        return fit.model_copy(update={'flag': ','.join(filter(None, [fit.flag, 'noparent']))})

    # _settings: minimum SNR and drop-flagged choice per kind from the export table; read on the GUI thread
    def _settings(self) -> dict[str, tuple[float, bool]]:
        return {n: (-np.inf if s.value() <= _ANY_SNR else s.value(), self._drops[n].isChecked()) for n, s in self._spins.items()}

    # _selected: current fits of a kind that pass its SNR and flag settings
    def _selected(self, kind: str, settings: dict[str, tuple[float, bool]]) -> list[Item]:
        min_snr, drop = settings[kind]
        return [(p, f) for p, f in self._items(kind) if f.snr >= min_snr and not (drop and f.flag)]

    # _preflight: warnings about picks the export will skip
    def _preflight(self) -> list[str]:
        assert self.session is not None
        lines = []
        for name, kind in self.session.project.config.kinds.items():
            items = self._items(name)
            missing = self.session.store.total(name) - len(items)
            if missing:
                lines.append(f'{name}: {missing} picks have no current estimate and are skipped (wait for estimating, or Re-estimate all)')
            orphans = sum('noparent' in f.flag for _, f in items)
            if orphans:
                lines.append(f'{name}: {orphans} picks have no {kind.parent} within {kind.parent_tolerance_a:g} A and are skipped')
        return lines

    # _filtered: picks of known kinds passing the filters, in tomogram then kind order, with their current fit
    def _filtered(self) -> list[tuple[Pick, Fit | None]]:
        assert self.session is not None and self.service is not None
        kind = self.kind_filter.currentText()
        tomo = self.tomo_filter.currentText()
        min_snr = self.snr_spin.value()
        order = {n: i for i, n in enumerate(self.session.names)}
        kinds = {k: i for i, k in enumerate(self.session.project.config.kinds)}
        matched = {k: self._matched(k) for k in kinds}
        out = []
        for pick in self.session.store.all():
            if pick.kind not in kinds or (kind != '(all)' and pick.kind != kind) or (tomo != '(all)' and pick.tomogram != tomo):
                continue
            fit = self.service.store.get(pick)
            if fit is not None:
                fit = self._flagged(pick.kind, pick, fit, matched[pick.kind])
            flagged = fit is not None and bool(fit.flag)
            if (self.flagged_box.isChecked() and not flagged) or (min_snr > _ANY_SNR and (fit is None or fit.snr < min_snr)):
                continue
            out.append((pick, fit))
        out.sort(key=lambda pf: (order.get(pf[0].tomogram, len(order)), kinds[pf[0].kind]))
        return out

    # _ask_delete_flagged: confirm, then delete the flagged picks shown
    def _ask_delete_flagged(self) -> None:
        n = sum(1 for _, f in self._filtered() if f is not None and f.flag)
        if n and QMessageBox.question(self, 'Delete picks', f'Delete {n} flagged picks?') == QMessageBox.StandardButton.Yes:
            self.delete_flagged()

    # _reestimate: queue estimates for everything that needs one
    def _reestimate(self) -> None:
        if self.service is not None:
            self.service.request_all()

    # _run: run an export or extraction job in the background, logging its lines
    def _run(self, job: Callable[[dict[str, tuple[float, bool]]], list[str]]) -> None:
        self.export_button.setEnabled(False)
        self.extract_button.setEnabled(False)
        settings = self._settings()
        run_in_background(lambda: job(settings), self._logged, lambda message: self._logged([message]))

    # _logged: show job output and unblock the buttons
    def _logged(self, lines: list[str]) -> None:
        self.log.appendPlainText('\n'.join(lines))
        self.export_button.setEnabled(True)
        self.extract_button.setEnabled(True)

    # _double_clicked: open the pick in the Pick tab
    def _double_clicked(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._shown):
            self.open_pick.emit(self._shown[row].tomogram, self._shown[row].id)

    # _preview: crops of the selected pick, read off the GUI thread
    def _preview(self) -> None:
        row = self.table.currentRow()
        if self.loader is None or self.service is None or not 0 <= row < len(self._shown):
            return
        pick = self._shown[row]
        fit = self.service.store.get(pick)
        centre = (fit.x, fit.y, fit.z) if fit else (pick.x, pick.y, pick.z)
        self._token += 1
        token = self._token
        run_in_background(
            lambda: self.crops(pick.tomogram, centre),
            lambda crops: self._show_preview(token, crops),
            lambda message: self.xy_label.setText(message),
        )

    # crops: (xy, xz) arrays around a centre: the slice through it, and the plane through it along z
    def crops(self, tomogram: str, centre: tuple[float, float, float]) -> tuple[np.ndarray, np.ndarray]:
        assert self.loader is not None
        vol = self.loader.open(tomogram).result().vol
        x, y, z = (round(v) for v in centre)
        z = min(max(z, 0), vol.shape[0] - 1)
        xs = slice(max(x - _CROP, 0), x + _CROP)
        ys = slice(max(y - _CROP, 0), y + _CROP)
        zs = slice(max(z - _CROP, 0), z + _CROP)
        xy = self.loader.slice(tomogram, z)[ys, xs]
        xz = np.asarray(vol[zs, min(max(y, 0), vol.shape[1] - 1), xs], dtype=np.float32)
        return xy, xz

    # _show_preview: draw the crops unless a newer selection has been made
    def _show_preview(self, token: int, crops: tuple[np.ndarray, np.ndarray]) -> None:
        if token != self._token:
            return
        self.xy_label.setPixmap(_pixmap(crops[0]))
        self.xz_label.setPixmap(_pixmap(crops[1]))

# _pixmap: a crop stretched between its 1st and 99th percentiles and scaled to fit the preview
def _pixmap(arr: np.ndarray) -> QPixmap:
    lo, hi = np.percentile(arr, (1, 99))
    img = np.ascontiguousarray(np.clip((arr - lo) * (255.0 / max(hi - lo, 1e-6)), 0, 255).astype(np.uint8))
    h, w = img.shape
    pixmap = QPixmap.fromImage(QImage(img.data, w, h, w, QImage.Format.Format_Grayscale8))
    return pixmap.scaled(_PREVIEW, _PREVIEW, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
