'''
pickmix: Review tab, every pick with filters and a preview of the selected pick
'''

# Import external dependencies
import math, numpy as np
from dataclasses import dataclass
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

# Import internal pickmix objects
from pickmix.estimate.registry import Fit
from pickmix.estimates import EstimateService, effective_box_a
from pickmix.export import Item
from pickmix.geometry import Parent
from pickmix.gui.components.images import draw_box, label_image, to_pixmap
from pickmix.gui.components.patch import Patch, PatchCanvas
from pickmix.gui.components.status import fit_status, status_item
from pickmix.gui.style import image_well, quiet_table, tidy, white
from pickmix.gui.workers import post, run_in_background
from pickmix.items import flagged, items, matched
from pickmix.loader import Loader
from pickmix.model import Pick, Session

# _COLUMNS: pick table headings
_COLUMNS: list[str] = ['Tomogram', 'Kind', 'x', 'y', 'z', 'SNR', 'Flag', 'Estimate', 'Box (Å)']

# _CROP: half-width in voxels of the preview crops
_CROP: int = 64

# _PREVIEW: edge in pixels of the preview images
_PREVIEW: int = 220

# _PATCH_SCALE: edge of the editable patch as a multiple of the box edge
_PATCH_SCALE: float = 1.5

# _Rect: left, top, right and bottom of a rectangle in the pixels of an array
type _Rect = tuple[float, float, float, float]

# Preview: what the four panels show for one pick
@dataclass(frozen=True)
class Preview:
    xy: np.ndarray
    xz: np.ndarray
    yz: np.ndarray
    patch: Patch
    outlines: tuple[_Rect, _Rect, _Rect]
    slabs: tuple[_Rect, _Rect] | None
    colour: str

# _COLUMN_GAP: pixels between the filters, the buttons and the count
_COLUMN_GAP: int = 40

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
        reload_icon = white('cached')
        if reload_icon is not None:
            self.reestimate_button.setIcon(reload_icon)
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
        self.yz_label = QLabel()
        self.xy_label.setToolTip('The slice through the pick')
        self.xz_label.setToolTip('The plane through the pick along z, at its y position')
        self.yz_label.setToolTip('The plane through the pick along z, at its x position')
        self.patch_canvas = PatchCanvas(_PREVIEW)
        self.patch_canvas.setToolTip('The slice through the pick, close up. Drag the dot or the box to move the pick')
        self._previewed: tuple | None = None
        for label in (self.xy_label, self.xz_label, self.yz_label):
            image_well(label, _PREVIEW)
        # controls: filters over two rows, then buttons, then the shown count, all centred on the same line
        filters = QGridLayout()
        for row, col, text, widget in (
            (0, 0, 'Kind', self.kind_filter), (0, 3, 'Tomogram', self.tomo_filter),
            (1, 0, 'Min SNR', self.snr_spin), (1, 3, 'Flags', self.flag_filter),
        ):
            filters.addWidget(QLabel(text), row, col)
            filters.addWidget(widget, row, col + 1)
        filters.setColumnMinimumWidth(2, 24)
        buttons = QGridLayout()
        buttons.addWidget(self.delete_selected_button, 0, 0)
        buttons.addWidget(self.delete_shown_button, 0, 1)
        buttons.addWidget(self.reestimate_button, 1, 0, 1, 2)
        controls = QHBoxLayout()
        controls.addLayout(filters)
        controls.addSpacing(_COLUMN_GAP)
        controls.addLayout(buttons)
        controls.addSpacing(_COLUMN_GAP)
        controls.addWidget(self.count_label, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        controls.setAlignment(filters, Qt.AlignmentFlag.AlignVCenter)
        controls.setAlignment(buttons, Qt.AlignmentFlag.AlignVCenter)
        # XY and the editable patch above, XZ and YZ below
        self.previews = QGridLayout()
        self.previews.addWidget(self.xy_label, 0, 0)
        self.previews.addWidget(self.patch_canvas, 0, 1)
        self.previews.addWidget(self.xz_label, 1, 0)
        self.previews.addWidget(self.yz_label, 1, 1)
        preview_column = QVBoxLayout()
        preview_column.addLayout(self.previews)
        preview_column.addStretch()
        body = QHBoxLayout()
        body.addWidget(self.table, 1)
        body.addLayout(preview_column)
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
        self.patch_canvas.move_requested.connect(self._move)
        self.delete_selected_button.clicked.connect(self.delete_selected)
        self.delete_shown_button.clicked.connect(self._ask_delete_shown)
        self.reestimate_button.clicked.connect(self._reestimate)

    # set_session: show a session and follow its picks and estimates
    def set_session(self, session: Session, loader: Loader, service: EstimateService) -> None:
        self.session, self.loader, self.service = session, loader, service
        session.store.listeners.append(self._schedule)
        service.store.listeners.append(self._schedule)
        service.validation.listeners.append(self._schedule)
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
            self.table.setItem(r, 8, QTableWidgetItem('' if pick.box_a is None else f'{pick.box_a:.0f}'))
        # the box column is only worth its room once a pick has a box of its own
        self.table.setColumnHidden(8, all(p.box_a is None for p in self._shown))
        if selected in [p.id for p in self._shown]:
            self.table.selectRow([p.id for p in self._shown].index(selected))
        self.table.blockSignals(False)
        # a moved pick or a new fit changes what the previews show, but the blocked signal will not say so
        self._preview(changed_only=True)
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
        assert self.service is not None
        return flagged(self.session, kind, pick, fit, parents, self.service.validation)

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

    # _move: the patch was dragged
    def _move(self, pick_id: int, x: float, y: float) -> None:
        if self.session is not None:
            self.session.store.move(pick_id, x, y)

    # _preview: four panels for selected pick, read off GUI thread
    def _preview(self, *, changed_only: bool = False) -> None:
        row = self.table.currentRow()
        if self.loader is None or self.service is None or not 0 <= row < len(self._shown):
            return
        pick = self._shown[row]
        fit = self.service.store.get(pick)
        key = (pick.id, pick.x, pick.y, pick.z, None if fit is None else fit.model_dump_json())
        if changed_only and key == self._previewed:
            return
        self._previewed = key
        self._token += 1
        token = self._token
        run_in_background(
            lambda: self.preview(pick, fit),
            lambda result: self._show_preview(token, result),
            lambda message: self.xy_label.setText(message),
        )

    # preview: crops, patch and outlines for a pick around its fit centre, or around pick when it has no fit
    def preview(self, pick: Pick, fit: Fit | None) -> Preview:
        assert self.loader is not None and self.session is not None
        project = self.session.project
        kind, px = project.config.kinds[pick.kind], project.tomos[pick.tomogram].pixel_size
        centre = (fit.x, fit.y, fit.z) if fit else (pick.x, pick.y, pick.z)
        xy, xz, yz = self.crops(pick.tomogram, centre)
        vol = self.loader.open(pick.tomogram).result().vol
        x0, y0, z0 = _starts(centre, vol.shape)
        half = effective_box_a(pick, kind, fit) / px / 2
        # voxel centres sit half a pixel in; box is a cube, so z extent is same as width
        cx, cy, cz = centre[0] - x0 + 0.5, centre[1] - y0 + 0.5, centre[2] - z0 + 0.5
        outlines = ((cx - half, cy - half, cx + half, cy + half), (cx - half, cz - half, cx + half, cz + half), (cy - half, cz - half, cy + half, cz + half))
        slabs = None if fit is None else ((cx - half, fit.z_lo - z0, cx + half, fit.z_hi + 1 - z0), (cy - half, fit.z_lo - z0, cy + half, fit.z_hi + 1 - z0))
        edge = max(math.ceil(_PATCH_SCALE * 2 * half), 4)
        sl = self.loader.slice(pick.tomogram, min(max(round(centre[2]), 0), vol.shape[0] - 1))
        left, top = round(centre[0]) - edge // 2, round(centre[1]) - edge // 2
        patch = Patch(_padded(sl, left, top, edge), (left, top), pick.id, (pick.x, pick.y), (centre[0], centre[1]), 2 * half, kind.colour, (vol.shape[2], vol.shape[1]), None if fit is None else fit.psi_deg)
        return Preview(xy, xz, yz, patch, outlines, slabs, kind.colour)

    # crops: (xy, xz, yz) arrays around a centre: the slice through it, and the planes through it along z at its y and at its x
    def crops(self, tomogram: str, centre: tuple[float, float, float]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        assert self.loader is not None
        vol = self.loader.open(tomogram).result().vol
        x, y, z = (round(v) for v in centre)
        z = min(max(z, 0), vol.shape[0] - 1)
        xs, ys, zs = (slice(max(c - _CROP, 0), c + _CROP) for c in (x, y, z))
        xy = self.loader.slice(tomogram, z)[ys, xs]
        xz = np.asarray(vol[zs, min(max(y, 0), vol.shape[1] - 1), xs], dtype=np.float32)
        yz = np.asarray(vol[zs, ys, min(max(x, 0), vol.shape[2] - 1)], dtype=np.float32)
        return xy, xz, yz

    # _show_preview: draw panels unless a newer selection has been made
    def _show_preview(self, token: int, preview: Preview) -> None:
        if token != self._token:
            return
        crops = (preview.xy, preview.xz, preview.yz)
        for i, (label, crop, name) in enumerate(zip((self.xy_label, self.xz_label, self.yz_label), crops, ('XY', 'XZ', 'YZ'), strict=True)):
            pixmap = to_pixmap(crop, _PREVIEW)
            scale = pixmap.width() / crop.shape[1]
            # the z range the fit used goes under the box so the box is still the outermost line
            if preview.slabs is not None and i:
                pixmap = draw_box(pixmap, preview.slabs[i - 1], scale, preview.colour, dotted=True)
            label.setPixmap(label_image(draw_box(pixmap, preview.outlines[i], scale, preview.colour), name))
        self.patch_canvas.set_patch(preview.patch)

# _starts: first x, y and z voxel of the crops around a centre, as `crops` cuts them
def _starts(centre: tuple[float, float, float], shape: tuple[int, ...]) -> tuple[int, int, int]:
    x, y, z = (round(v) for v in centre)
    z = min(max(z, 0), shape[0] - 1)
    return max(x - _CROP, 0), max(y - _CROP, 0), max(z - _CROP, 0)

# _padded: an edge x edge crop of a slice with its top-left at voxel (left, top), padded with slice mean where it leaves slice
def _padded(img: np.ndarray, left: int, top: int, edge: int) -> np.ndarray:
    out = np.full((edge, edge), img.mean(), dtype=np.float32)
    ys, xs = slice(max(top, 0), min(top + edge, img.shape[0])), slice(max(left, 0), min(left + edge, img.shape[1]))
    if ys.stop > ys.start and xs.stop > xs.start:
        out[ys.start - top : ys.stop - top, xs.start - left : xs.stop - left] = img[ys, xs]
    return out
