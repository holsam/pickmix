'''
pickmix: Review tab, every pick with filters and a preview of the selected pick
'''

# Import external dependencies
import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

# Import internal pickmix objects
from pickmix.estimate.registry import Fit
from pickmix.estimates import EstimateService
from pickmix.export import Item
from pickmix.geometry import Parent
from pickmix.gui.components.icons import icon
from pickmix.gui.components.images import to_pixmap
from pickmix.gui.components.status import fit_status, status_item
from pickmix.gui.style import heading, image_well, quiet_table, tidy
from pickmix.gui.workers import post, run_in_background
from pickmix.items import flagged, items, matched
from pickmix.loader import Loader
from pickmix.model import Pick, Session

# _COLUMNS: pick table headings
_COLUMNS: list[str] = ['Tomogram', 'Kind', 'x', 'y', 'z', 'SNR', 'Flag', 'Estimate']

# _CROP: half-width in voxels of the preview crops
_CROP: int = 64

# _PREVIEW: edge in pixels of the preview images
_PREVIEW: int = 256

# _FLAG_CHOICES: the flags filter, in drop-down order
_FLAG_CHOICES: list[str] = ['(all)', 'Flagged only', 'Non-flagged only']

# _ANY_SNR: minimum of the SNR filter, shown as "any"
_ANY_SNR: float = -1000.0

# ReviewTab: pick table and filters above, preview beside
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
        self.flag_filter = QComboBox()
        self.flag_filter.addItems(_FLAG_CHOICES)
        self.snr_spin = QDoubleSpinBox()
        self.snr_spin.setRange(_ANY_SNR, 1000.0)
        self.snr_spin.setValue(_ANY_SNR)
        self.snr_spin.setSpecialValueText('any')
        self.count_label = QLabel()
        self.delete_selected_button = QPushButton('Delete selected')
        self.delete_selected_button.setToolTip('Delete the selected pick')
        self.delete_shown_button = QPushButton('Delete shown')
        self.delete_shown_button.setToolTip('Delete every pick the filters show')
        self.reestimate_button = QPushButton('Re-estimate all')
        self.reestimate_button.setToolTip('Fit every pick again')
        refresh = icon('refresh')
        if refresh is not None:
            self.reestimate_button.setIcon(refresh)
        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        quiet_table(self.table)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        # tomogram and kind take what they need, the other columns share the rest
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.xy_label = QLabel()
        self.xz_label = QLabel()
        for label in (self.xy_label, self.xz_label):
            image_well(label, _PREVIEW)
        # controls: filters over two rows, then buttons, then the shown count, all centred on the same line
        filters = QGridLayout()
        for row, col, text, widget in (
            (0, 0, 'Kind', self.kind_filter), (0, 2, 'Tomogram', self.tomo_filter),
            (1, 0, 'Min SNR', self.snr_spin), (1, 2, 'Flags', self.flag_filter),
        ):
            filters.addWidget(QLabel(text), row, col)
            filters.addWidget(widget, row, col + 1)
        buttons = QGridLayout()
        buttons.addWidget(self.delete_selected_button, 0, 0)
        buttons.addWidget(self.delete_shown_button, 0, 1)
        buttons.addWidget(self.reestimate_button, 1, 0, 1, 2)
        controls = QHBoxLayout()
        controls.addLayout(filters)
        controls.addSpacing(16)
        controls.addLayout(buttons)
        controls.addSpacing(16)
        controls.addWidget(self.count_label, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        controls.setAlignment(filters, Qt.AlignmentFlag.AlignVCenter)
        controls.setAlignment(buttons, Qt.AlignmentFlag.AlignVCenter)
        previews = QVBoxLayout()
        self.xy_heading = heading('XY')
        self.xz_heading = heading('XZ')
        self.xy_heading.setToolTip('The slice through the pick')
        self.xz_heading.setToolTip('The plane through the pick along z, at its y position')
        previews.addWidget(self.xy_heading)
        previews.addWidget(self.xy_label)
        previews.addWidget(self.xz_heading)
        previews.addWidget(self.xz_label)
        previews.addStretch()
        body = QHBoxLayout()
        body.addWidget(self.table, 1)
        body.addLayout(previews)
        layout = QVBoxLayout(self)
        tidy(layout)
        layout.addLayout(controls)
        layout.addLayout(body, 1)
        for combo in (self.kind_filter, self.tomo_filter):
            combo.currentIndexChanged.connect(self.refresh)
        self.flag_filter.currentIndexChanged.connect(self.refresh)
        self.snr_spin.valueChanged.connect(self.refresh)
        self.table.itemSelectionChanged.connect(self._preview)
        self.table.cellDoubleClicked.connect(self._double_clicked)
        self.delete_selected_button.clicked.connect(self.delete_selected)
        self.delete_shown_button.clicked.connect(self._ask_delete_shown)
        self.reestimate_button.clicked.connect(self._reestimate)

    # set_session: show a session and follow its picks and estimates
    def set_session(self, session: Session, loader: Loader, service: EstimateService) -> None:
        self.session, self.loader, self.service = session, loader, service
        session.store.listeners.append(self._schedule)
        service.store.listeners.append(self._schedule)
        self.refresh_kinds()

    # refresh_kinds: rebuild the kind and tomogram filters from the config
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
        self.refresh()

    # refresh: rebuild the pick table with the filters applied
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
            flag = '' if fit is None else fit.flag
            cells = [pick.tomogram, pick.kind, f'{pick.x:.1f}', f'{pick.y:.1f}', f'{pick.z:.1f}', '' if fit is None else f'{fit.snr:.2f}', flag]
            for c, text in enumerate(cells):
                self.table.setItem(r, c, QTableWidgetItem(text))
            status = fit_status(state, flag)
            tip = {'running': f'Estimate {state}', 'ok': 'Estimate is fine'}.get(status, flag)
            self.table.setItem(r, 7, status_item(status, tip))
        if selected in [p.id for p in self._shown]:
            self.table.selectRow([p.id for p in self._shown].index(selected))
        self.table.blockSignals(False)
        self.count_label.setText(f'{len(rows)} shown of {self.session.store.total()}')

    # delete_selected: remove the selected pick; returns how many went
    def delete_selected(self) -> int:
        row = self.table.currentRow()
        if self.session is None or not 0 <= row < len(self._shown):
            return 0
        self.session.store.remove(self._shown[row].id)
        return 1

    # delete_shown: remove every pick the filters currently show; returns how many went
    def delete_shown(self) -> int:
        assert self.session is not None and self.service is not None
        doomed = [p.id for p, _ in self._filtered()]
        if doomed:
            self.session.store.remove(*doomed)
        return len(doomed)

    # _schedule: coalesce bursts of changes, from any thread, into one refresh
    def _schedule(self) -> None:
        post(lambda: self._timer.start())

    # _items: picks of a kind that have a current fit
    def _items(self, kind: str) -> list[Item]:
        assert self.session is not None and self.service is not None
        return items(self.session, self.service, kind)

    # _matched: parent geometry for every pick of a kind, empty for a kind with no parent
    def _matched(self, kind: str) -> dict[int, Parent]:
        assert self.session is not None and self.service is not None
        return matched(self.session, self.service, kind)

    # _flagged: the fit with noparent added to its flags when the pick's kind has a parent and the pick found none
    def _flagged(self, kind: str, pick: Pick, fit: Fit, parents: dict[int, Parent]) -> Fit:
        assert self.session is not None
        return flagged(self.session, kind, pick, fit, parents)

    # _filtered: picks of known kinds passing the filters, in tomogram then kind order, with their current fit
    def _filtered(self) -> list[tuple[Pick, Fit | None]]:
        assert self.session is not None and self.service is not None
        kind = self.kind_filter.currentText()
        tomo = self.tomo_filter.currentText()
        min_snr = self.snr_spin.value()
        order = {n: i for i, n in enumerate(self.session.names)}
        kinds = {k: i for i, k in enumerate(self.session.project.config.kinds)}
        parents = {k: self._matched(k) for k in kinds}
        out = []
        for pick in self.session.store.all():
            if pick.kind not in kinds or (kind != '(all)' and pick.kind != kind) or (tomo != '(all)' and pick.tomogram != tomo):
                continue
            fit = self.service.store.get(pick)
            if fit is not None:
                fit = self._flagged(pick.kind, pick, fit, parents[pick.kind])
            is_flagged = fit is not None and bool(fit.flag)
            mode = self.flag_filter.currentIndex()
            if (mode == 1 and not is_flagged) or (mode == 2 and is_flagged) or (min_snr > _ANY_SNR and (fit is None or fit.snr < min_snr)):
                continue
            out.append((pick, fit))
        out.sort(key=lambda pf: (order.get(pf[0].tomogram, len(order)), kinds[pf[0].kind]))
        return out

    # _ask_delete_shown: confirm, then delete every pick shown
    def _ask_delete_shown(self) -> None:
        if self.session is None or self.service is None:
            return
        n = len(self._filtered())
        if n and QMessageBox.question(self, 'Delete picks', f'Delete the {n} picks shown?') == QMessageBox.StandardButton.Yes:
            self.delete_shown()

    # _reestimate: queue estimates for everything that needs one
    def _reestimate(self) -> None:
        if self.service is not None:
            self.service.request_all()

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
        self.xy_label.setPixmap(to_pixmap(crops[0], _PREVIEW))
        self.xz_label.setPixmap(to_pixmap(crops[1], _PREVIEW))
