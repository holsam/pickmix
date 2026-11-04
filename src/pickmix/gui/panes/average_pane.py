'''
pickmix: Average pane of the Export tab
'''

# Import external dependencies
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QShowEvent
from PySide6.QtWidgets import QComboBox, QGroupBox, QHBoxLayout, QLabel, QListWidget, QPushButton, QVBoxLayout

# Import internal pickmix objects
from pickmix.average import AverageResult, average_kind
from pickmix.estimates import EstimateService
from pickmix.export import Item
from pickmix.gui.components.images import label_cells, to_image, to_pixmap
from pickmix.gui.components.status import StatusBadge
from pickmix.gui.components.toast import notify
from pickmix.gui.style import heading, image_well, tidy
from pickmix.gui.workers import run_in_background
from pickmix.model import Session

# _SIZE: edge in pixels of each image shown
_SIZE: int = 300

# AveragePane: choose a kind, run, and look at the overall or per-tomogram mean beside the labelled montage
class AveragePane(QGroupBox):
    # __init__: build the layout
    def __init__(self) -> None:
        super().__init__('Average')
        self.session: Session | None = None
        self.service: EstimateService | None = None
        self.result: AverageResult | None = None
        self.kind_box = QComboBox()
        self.summary = QLabel()
        self.run_button = QPushButton('Run')
        self.spinner = StatusBadge()
        self.save_button = QPushButton('Save montage')
        self.save_button.setToolTip('Write the montage twice: as it is, and with the cell labels')
        self.save_button.setEnabled(False)
        self.mean_label = QLabel('mean')
        self.montage_label = QLabel('montage')
        for label in (self.mean_label, self.montage_label):
            image_well(label, _SIZE)
        self.results_list = QListWidget()
        self.results_list.setMaximumWidth(220)
        self.results_list.setToolTip('Show the mean of every pick, or of one tomogram')
        # kind, run, spinner and summary above the images
        controls = QHBoxLayout()
        controls.addWidget(QLabel('Kind'))
        controls.addWidget(self.kind_box)
        controls.addWidget(self.run_button)
        controls.addWidget(self.spinner)
        controls.addWidget(self.summary, 1)
        # Mean: the image with the overall and per-tomogram list next to it, since that is what changes
        mean_row = QHBoxLayout()
        mean_row.addWidget(self.mean_label)
        mean_row.addWidget(self.results_list)
        mean = QVBoxLayout()
        mean.addWidget(heading('Mean'))
        mean.addLayout(mean_row)
        montage_head = QHBoxLayout()
        montage_head.addWidget(heading('Montage'))
        montage_head.addStretch()
        montage_head.addWidget(self.save_button)
        montage = QVBoxLayout()
        montage.addLayout(montage_head)
        montage.addWidget(self.montage_label)
        montage.addStretch()
        images = QHBoxLayout()
        images.addLayout(mean)
        images.addSpacing(16)
        images.addLayout(montage)
        images.addStretch()
        body = QVBoxLayout(self)
        tidy(body)
        body.addLayout(controls)
        body.addLayout(images)
        self.kind_box.currentTextChanged.connect(self._update_summary)
        self.run_button.clicked.connect(self.run)
        self.save_button.clicked.connect(self.save_montage)
        self.results_list.currentRowChanged.connect(self._show_row)

    # set_session: use a session's picks and the service's fits, or none
    def set_session(self, session: Session | None, service: EstimateService | None) -> None:
        self.session, self.service, self.result = session, service, None
        self.save_button.setEnabled(False)
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
        run_in_background(lambda: average_kind(name, config.kinds[name], items, tomos, config), self._done, self._failed)

    # save_montage: write the montage twice into the kind's average folder, plain and with its cell labels; returns the two paths
    def save_montage(self) -> list[str]:
        if self.result is None:
            return []
        r = self.result
        plain, labelled = r.folder / 'overall_montage.png', r.folder / 'overall_montage_labelled.png'
        image = to_image(r.montage)
        image.save(str(plain))
        label_cells(image, r.labels, r.grid, r.pad).save(str(labelled))
        notify(f'Saved {str(plain)!r} and {str(labelled)!r}')
        return [str(plain), str(labelled)]

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

    # _done: show the overall mean and the labelled montage, and list what can be looked at
    def _done(self, result: AverageResult) -> None:
        self.result = result
        self.run_button.setEnabled(True)
        self.save_button.setEnabled(True)
        self.spinner.set_status(None)
        notify(f'{result.count} boxes of {result.box_px} px, PNGs in {str(result.folder)!r}')
        self.montage_label.setPixmap(self._labelled(result))
        self.results_list.clear()
        self.results_list.addItems(['overall', *result.per_tomogram])
        self.results_list.setCurrentRow(0)

    # _failed: report an error from the background run
    def _failed(self, message: str) -> None:
        self.run_button.setEnabled(True)
        self.spinner.set_status('error', message)
        notify(message)

    # _labelled: the montage shown at display size with its cell labels drawn at that size
    def _labelled(self, result: AverageResult) -> QPixmap:
        shown = to_image(result.montage).scaled(_SIZE, _SIZE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        return QPixmap.fromImage(label_cells(shown, result.labels, result.grid, result.pad, scale=shown.width() / result.montage.shape[1]))

    # _show_row: show the overall mean or one tomogram's mean
    def _show_row(self, row: int) -> None:
        if self.result is None or row < 0:
            return
        name = self.results_list.item(row).text()
        self.mean_label.setPixmap(to_pixmap(self.result.overall if name == 'overall' else self.result.per_tomogram[name], _SIZE))
