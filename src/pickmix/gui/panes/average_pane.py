'''
pickmix: Average pane of the Export tab
'''

# Import external dependencies
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

# Import internal pickmix objects
from pickmix.average import AverageResult, average_kind, save_average
from pickmix.estimates import EstimateService
from pickmix.export import Item
from pickmix.gui.components.images import FitLabel, label_cells, tile_cells, to_image, to_pixmap
from pickmix.gui.components.status import StatusBadge
from pickmix.gui.components.toast import notify
from pickmix.gui.style import WELL_BG, WELL_TEXT, heading, help_marker, image_well, quiet_table, tidy
from pickmix.gui.workers import run_in_background
from pickmix.model import Session

# _MEAN, _MONTAGE: edge in pixels of the mean, and the smallest edge of the montage, which grows to fill its space
_MEAN: int = 340
_MONTAGE: int = 340

# _LEFT: width in pixels of the controls column
_LEFT: int = 280

# AveragePane: controls and the tomogram list on the left, the mean in the middle and the labelled montage on the right
class AveragePane(QGroupBox):
    # __init__: build the layout
    def __init__(self) -> None:
        super().__init__('Average')
        self.session: Session | None = None
        self.service: EstimateService | None = None
        self.result: AverageResult | None = None
        self._names: list[str] = []
        self.kind_box = QComboBox()
        self.summary = QLabel()
        self.run_button = QPushButton('Run')
        self.spinner = StatusBadge()
        self.save_button = QPushButton('Save')
        self.save_button.setToolTip("Write the mean and the montage (plain and labelled) to the kind's average folder")
        self.save_button.setEnabled(False)
        self.per_tomogram_box = QCheckBox('Include per-tomogram means')
        self.per_tomogram_box.setToolTip('Also write a mean image for every tomogram in the list')
        self.worst_box = QCheckBox('Montage lowest scoring first')
        self.worst_box.setToolTip('Show the lowest-scoring picks from kind validation with their scores.')
        self.results_table = QTableWidget(0, 2)
        self.results_table.setHorizontalHeaderLabels(['Tomogram', 'Picks'])
        quiet_table(self.results_table)
        self.results_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.results_table.setToolTip('Show the mean of every pick, or of one tomogram')
        self.mean_label = QLabel('mean')
        self.montage_label = FitLabel('montage', _MONTAGE)
        self.montage_label.setStyleSheet(f'background: {WELL_BG}; color: {WELL_TEXT}')
        image_well(self.mean_label, _MEAN)
        # left: kind, run and summary, the tomogram list, then save
        kind_row = QHBoxLayout()
        kind_row.addWidget(QLabel('Kind'))
        kind_row.addWidget(self.kind_box, 1)
        run_row = QHBoxLayout()
        run_row.addWidget(self.run_button)
        run_row.addWidget(self.spinner)
        run_row.addStretch()
        tick_row = QHBoxLayout()
        tick_row.addWidget(self.per_tomogram_box)
        tick_row.addWidget(help_marker('Without this, only the overall mean and the montage are written'))
        tick_row.addStretch()
        left = QWidget()
        left.setFixedWidth(_LEFT)
        left_box = QVBoxLayout(left)
        left_box.setContentsMargins(0, 0, 0, 0)
        left_box.addLayout(kind_row)
        left_box.addLayout(run_row)
        left_box.addWidget(self.summary)
        left_box.addWidget(self.results_table, 1)
        left_box.addWidget(self.worst_box)
        left_box.addLayout(tick_row)
        left_box.addWidget(self.save_button)
        mean = QVBoxLayout()
        mean.addWidget(heading('Mean'))
        mean.addWidget(self.mean_label)
        mean.addStretch()
        montage = QVBoxLayout()
        montage.addWidget(heading('Montage'))
        montage.addWidget(self.montage_label, 1)
        columns = QHBoxLayout()
        columns.addWidget(left)
        columns.addSpacing(16)
        columns.addLayout(mean)
        columns.addSpacing(16)
        columns.addLayout(montage, 1)
        body = QVBoxLayout(self)
        tidy(body)
        body.addLayout(columns)
        self.kind_box.currentTextChanged.connect(self._update_summary)
        self.kind_box.currentTextChanged.connect(self._clear)
        self.run_button.clicked.connect(self.run)
        self.save_button.clicked.connect(self.save)
        self.results_table.currentCellChanged.connect(lambda row, *_: self._show_row(row))

    # set_session: use a session's picks and the service's fits, or none
    def set_session(self, session: Session | None, service: EstimateService | None) -> None:
        self.session, self.service = session, service
        self._clear()
        self.refresh_kinds()

    # refresh_kinds: list the kinds of the config
    def refresh_kinds(self) -> None:
        current = self.kind_box.currentText()
        self.kind_box.blockSignals(True)
        self.kind_box.clear()
        if self.session is not None:
            self.kind_box.addItems(list(self.session.project.config.kinds))
            self.kind_box.setCurrentText(current)
        self.kind_box.blockSignals(False)
        self._update_summary()

    # items: current fits of the chosen kind in every tomogram
    def items(self) -> list[Item]:
        if self.session is None or self.service is None:
            return []
        out = []
        for pick in self.session.store.all(self.kind_box.currentText()):
            fit = self.service.store.get(pick)
            if fit is not None:
                out.append((pick, fit))
        return out

    # run: average the chosen kind in the background
    def run(self) -> None:
        if self.session is None:
            return
        self._update_summary()
        items, name = self.items(), self.kind_box.currentText()
        if not items:
            notify('No picks with a current estimate in the selected tomograms')
            return
        config, tomos = self.session.project.config, self.session.project.tomos
        self.run_button.setEnabled(False)
        self.spinner.set_status('running', f'Averaging {len(items)} picks...')
        notify(f'Averaging {len(items)} picks of {name}...')
        scores = None
        if self.worst_box.isChecked() and self.service is not None:
            scores = {p.id: s for p, _ in items if (s := self.service.validation.score(p)) is not None}
            if not scores:
                notify('No validation scores for this kind yet so montage is spread evenly, validate kind in Review tab.')
        run_in_background(lambda: average_kind(name, config.kinds[name], items, tomos, config, scores=scores or None), self._done, self._failed)

    # save: write the averages of the shown result, and the labelled montage beside them; returns the paths
    def save(self) -> list[str]:
        if self.result is None:
            return []
        r = self.result
        paths = save_average(r, per_tomogram=self.per_tomogram_box.isChecked())
        labelled = r.folder / 'overall_montage_labelled.png'
        label_cells(to_image(r.montage), r.labels, r.grid, r.pad).save(str(labelled))
        paths.append(labelled)
        notify(f'Saved {len(paths)} images in {str(r.folder)!r}', saved=True)
        return [str(p) for p in paths]

    # _clear: forget the shown result, so Save never writes under a kind the box no longer shows
    def _clear(self) -> None:
        self.result = None
        self._names = []
        self.results_table.setRowCount(0)
        self.mean_label.clear()
        self.mean_label.setText('mean')
        self.montage_label.set_render(None)
        self.montage_label.clear()
        self.montage_label.setText('montage')
        self.save_button.setEnabled(False)

    # _update_summary: total picks, tomograms with picks and picks per tomogram for the chosen kind
    def _update_summary(self) -> None:
        picks = self.session.store.all(self.kind_box.currentText()) if self.session is not None else []
        tomograms = len({p.tomogram for p in picks})
        if not tomograms:
            self.summary.setText('No picks of this kind')
            return
        self.summary.setText(f'{len(picks)} picks in {tomograms} tomograms ({len(picks) / tomograms:.1f} per tomogram)')

    # showEvent: picks change on other tabs, so refresh the summary whenever this pane appears
    def showEvent(self, event: QShowEvent) -> None:
        self._update_summary()
        super().showEvent(event)

    # _done: show the overall mean and the labelled montage, and list what can be looked at with its picks
    def _done(self, result: AverageResult) -> None:
        self.result = result
        self._names = list(result.per_tomogram)
        self.run_button.setEnabled(True)
        self.save_button.setEnabled(True)
        self.spinner.set_status(None)
        turned = '. Filaments are oriented along x, ends are not told apart' if result.aligned else ''
        notify(f'Averaged {result.count} boxes of {result.box_px} px (Save to write them){turned}')
        self.montage_label.set_render(lambda width, height: self._tiled(result, width, height))
        rows = [('overall', result.count), *((t, result.counts[t]) for t in self._names)]
        self.results_table.setRowCount(len(rows))
        for r, (name, picks) in enumerate(rows):
            self.results_table.setItem(r, 0, QTableWidgetItem(name))
            self.results_table.setItem(r, 1, QTableWidgetItem(str(picks)))
        self.results_table.selectRow(0)

    # _failed: report an error from the background run
    def _failed(self, message: str) -> None:
        self.run_button.setEnabled(True)
        self.spinner.set_status('error', message)
        notify(message)

    # _tiled: the montage's cells laid out again to fill a pane of this size, labelled (what is saved stays the square montage)
    def _tiled(self, result: AverageResult, width: int, height: int) -> QPixmap:
        return QPixmap.fromImage(tile_cells(to_image(result.montage), result.labels, result.grid, result.pad, width, height))

    # _show_row: show the overall mean (row 0) or one tomogram's mean
    def _show_row(self, row: int) -> None:
        if self.result is None or row < 0:
            return
        mean = self.result.overall if row == 0 else self.result.per_tomogram[self._names[row - 1]]
        self.mean_label.setPixmap(to_pixmap(mean, _MEAN))
