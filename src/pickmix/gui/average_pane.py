'''
pickmix: Average pane of the Kinds tab
'''

# Import external dependencies
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QGroupBox, QHBoxLayout, QLabel, QListWidget, QPushButton, QVBoxLayout

# Import internal pickmix objects
from pickmix.average import AverageResult, average_kind
from pickmix.estimates import EstimateService
from pickmix.export import Item
from pickmix.gui.images import to_pixmap
from pickmix.gui.workers import run_in_background
from pickmix.model import Session

# _SIZE: edge in pixels of each image shown
_SIZE: int = 300

# AveragePane: choose a kind and tomograms, run, and look at the overall mean, the montage and each tomogram's mean
class AveragePane(QGroupBox):
    # __init__: build the layout
    def __init__(self) -> None:
        super().__init__('Average')
        self.session: Session | None = None
        self.service: EstimateService | None = None
        self.result: AverageResult | None = None
        self.kind_box = QComboBox()
        self.tomo_list = QListWidget()
        self.tomo_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.tomo_list.setMaximumHeight(110)
        self.run_button = QPushButton('Run')
        self.status = QLabel()
        self.mean_label = QLabel('mean')
        self.montage_label = QLabel('montage')
        for label in (self.mean_label, self.montage_label):
            label.setFixedSize(_SIZE, _SIZE)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet('background: #141414; color: #888')
        self.results_list = QListWidget()
        self.results_list.setMaximumWidth(220)
        left = QVBoxLayout()
        left.addWidget(QLabel('Kind'))
        left.addWidget(self.kind_box)
        left.addWidget(QLabel('Tomograms with picks'))
        left.addWidget(self.tomo_list)
        left.addWidget(self.run_button)
        left.addWidget(self.status)
        left.addStretch()
        body = QHBoxLayout(self)
        body.addLayout(left)
        body.addWidget(self.mean_label)
        body.addWidget(self.montage_label)
        body.addWidget(self.results_list)
        self.kind_box.currentTextChanged.connect(self._fill_tomograms)
        self.run_button.clicked.connect(self.run)
        self.results_list.currentRowChanged.connect(self._show_row)

    # set_session: use a session's picks and the service's fits, or none
    def set_session(self, session: Session | None, service: EstimateService | None) -> None:
        self.session, self.service, self.result = session, service, None
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
        self._fill_tomograms()

    # items: current fits of the chosen kind in the selected tomograms
    def items(self) -> list[Item]:
        if self.session is None or self.service is None:
            return []
        chosen = {i.text() for i in self.tomo_list.selectedItems()}
        out = []
        for pick in self.session.store.all(self.kind_box.currentText()):
            fit = self.service.store.get(pick)
            if fit is not None and pick.tomogram in chosen:
                out.append((pick, fit))
        return out

    # run: average the chosen kind in the background
    def run(self) -> None:
        if self.session is None:
            return
        items, name = self.items(), self.kind_box.currentText()
        if not items:
            self.status.setText('No picks with a current estimate in the selected tomograms')
            return
        config, tomos = self.session.project.config, self.session.project.tomos
        self.run_button.setEnabled(False)
        self.status.setText(f'Averaging {len(items)} picks...')
        run_in_background(lambda: average_kind(name, config.kinds[name], items, tomos, config), self._done, self._failed)

    # _fill_tomograms: tomograms that have picks of the chosen kind, all selected
    def _fill_tomograms(self) -> None:
        self.tomo_list.clear()
        if self.session is None:
            return
        kind = self.kind_box.currentText()
        for name in self.session.names:
            if self.session.store.count(name, kind):
                self.tomo_list.addItem(name)
        self.tomo_list.selectAll()

    # _done: show the overall mean and list what can be looked at
    def _done(self, result: AverageResult) -> None:
        self.result = result
        self.run_button.setEnabled(True)
        self.status.setText(f'{result.count} boxes of {result.box_px} px, PNGs in {str(result.folder)!r}')
        self.montage_label.setPixmap(to_pixmap(result.montage, _SIZE))
        self.results_list.clear()
        self.results_list.addItems(['overall', *result.per_tomogram])
        self.results_list.setCurrentRow(0)

    # _failed: show an error from the background run
    def _failed(self, message: str) -> None:
        self.run_button.setEnabled(True)
        self.status.setText(message)

    # _show_row: show the overall mean or one tomogram's mean
    def _show_row(self, row: int) -> None:
        if self.result is None or row < 0:
            return
        name = self.results_list.item(row).text()
        self.mean_label.setPixmap(to_pixmap(self.result.overall if name == 'overall' else self.result.per_tomogram[name], _SIZE))
