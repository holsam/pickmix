'''
pickmix: 'Project' tab for creating/opening projects and setting tomogram sources & estimator parameters
'''

# Import external dependencies
from pathlib import Path
from pydantic import BaseModel, ValidationError
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QPushButton, QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

# Import internal pickmix objects
from pickmix.config import RingParams
from pickmix.gui.collapsible import Collapsible
from pickmix.gui.new_project_dialog import NewProjectDialog
from pickmix.gui.style import form_label, heading, tidy
from pickmix.gui.workers import run_in_background
from pickmix.project import Project, create_project, open_project
from pickmix.utils.star import MergeResult

# _COLUMNS: tomogram table headings
_COLUMNS: list[str] = ['Name', 'Shape (zyx)', 'Pixel size (A)', 'Denoised', 'Status']

# _ParamsForm: a form for a flat pydantic model of numbers and number pairs, labelled from the field titles
class _ParamsForm(QWidget):
    # __init__: one row per field, "Title (units) (?): [a] - [b]"
    def __init__(self, params: BaseModel) -> None:
        super().__init__()
        self._cls = type(params)
        self._boxes: dict[str, list[QSpinBox | QDoubleSpinBox]] = {}
        self.labels: dict[str, QLabel] = {}
        layout = QFormLayout(self)
        for name, value in params:
            info = type(params).model_fields[name]
            values = value if isinstance(value, tuple) else (value,)
            boxes = [_spin(v) for v in values]
            self._boxes[name] = boxes
            row = QHBoxLayout()
            for i, box in enumerate(boxes):
                if i:
                    row.addWidget(QLabel('-'))
                row.addWidget(box)
            row.addStretch()
            # "Title (units) (?):" in the label column, then the values
            head = form_label(info.title or name, info.description or '')
            self.labels[name] = head.findChild(QLabel)
            layout.addRow(head, row)

    # set: show the values of a model
    def set(self, params: BaseModel) -> None:
        for name, value in params:
            for box, v in zip(self._boxes[name], value if isinstance(value, tuple) else (value,), strict=True):
                box.setValue(v)

    # get: a model of the shown values, validated by pydantic
    def get(self) -> BaseModel:
        return self._cls(**{n: tuple(b.value() for b in boxes) if len(boxes) > 1 else boxes[0].value() for n, boxes in self._boxes.items()})

# ProjectTab: project open/create, tomogram table and settings
class ProjectTab(QWidget):
    # project_changed: a project was opened or created
    project_changed = Signal(object)
    # config_saved: settings of the open project were written to config.toml
    config_saved = Signal()
    # project_closed: the open project was closed
    project_closed = Signal()

    # __init__: build the layout
    def __init__(self) -> None:
        super().__init__()
        self.project: Project | None = None
        self.path_label = QLabel()
        self.open_button = QPushButton('Open project...')
        self.new_button = QPushButton('New project...')
        self.reload_button = QPushButton('Reload config')
        self.close_button = QPushButton('Close project')
        self.status = QLabel()
        self.summary = QLabel()
        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.source_box = QComboBox()
        self.source_box.addItems(['denoised', 'raw'])
        self.ring_form = _ParamsForm(RingParams())
        self.save_button = QPushButton('Save settings')
        general = QGroupBox('General')
        source = QFormLayout(general)
        source.addRow('Volume source', self.source_box)
        estimators = QGroupBox('Estimators')
        estimator_box = QVBoxLayout(estimators)
        self.ring_section = Collapsible('Ring', self.ring_form)
        estimator_box.addWidget(self.ring_section)
        self.settings = QWidget()
        self.settings.setMinimumWidth(self.ring_form.sizeHint().width() + 48)
        form = QVBoxLayout(self.settings)
        form.setContentsMargins(0, 0, 0, 0)
        form.addWidget(heading('Settings'))
        form.addWidget(general)
        form.addWidget(estimators)
        form.addWidget(self.save_button)
        form.addStretch()
        start = QWidget()
        start_layout = QVBoxLayout(start)
        start_layout.addStretch()
        start_layout.addWidget(heading('No project open'), alignment=Qt.AlignmentFlag.AlignHCenter)
        for button in (self.new_button, self.open_button):
            button.setMinimumWidth(220)
            start_layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignHCenter)
        start_layout.addStretch()
        # page 1: the open project
        top = QHBoxLayout()
        top.addWidget(self.path_label, 1)
        top.addWidget(self.reload_button)
        top.addWidget(self.close_button)
        left = QVBoxLayout()
        left.addWidget(self.summary)
        left.addWidget(self.table)
        body = QHBoxLayout()
        body.addLayout(left, 3)
        body.addWidget(self.settings, 1)
        opened = QWidget()
        opened_layout = QVBoxLayout(opened)
        opened_layout.setContentsMargins(0, 0, 0, 0)
        opened_layout.addLayout(top)
        opened_layout.addLayout(body)
        self.stack = QStackedWidget()
        self.stack.addWidget(start)
        self.stack.addWidget(opened)
        layout = QVBoxLayout(self)
        tidy(layout)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.status)
        self.open_button.clicked.connect(self._open_dialog)
        self.new_button.clicked.connect(self._new_dialog)
        self.reload_button.clicked.connect(self._reload)
        self.close_button.clicked.connect(self.close_project)
        self.save_button.clicked.connect(self.save_settings)

    # open_config: open a config.toml in the background
    def open_config(self, path: Path) -> None:
        self._busy(f'Scanning tomograms for {str(path)!r}...')
        run_in_background(lambda: open_project(path), self.set_project, self._failed)

    # set_project: show a project and announce it
    def set_project(self, project: Project) -> None:
        self.project = project
        self.path_label.setText(str(project.path))
        self._fill_table(project)
        self.source_box.setCurrentText(project.config.source)
        self.ring_form.set(project.config.ring)
        self.stack.setCurrentIndex(1)
        self._idle('')
        self.project_changed.emit(project)

    # close_project: close the open project and go back to the start page
    def close_project(self) -> None:
        self.project = None
        self.stack.setCurrentIndex(0)
        self.status.setText('')
        self.project_closed.emit()

    # save_settings: write source and ring parameters to config.toml
    def save_settings(self) -> None:
        if self.project is None:
            return
        try:
            self.project.update(source=self.source_box.currentText(), ring=self.ring_form.get())
        except ValidationError as e:
            self.status.setText(f'Not saved: {e.errors()[0]["msg"]}')
            return
        self.status.setText('Saved')
        self.config_saved.emit()

    # _fill_table: one row per star row, rejected ones shaded with the reason
    def _fill_table(self, project: Project) -> None:
        self.table.setRowCount(len(project.names))
        for r, name in enumerate(project.names):
            if name in project.tomos:
                t = project.tomos[name]
                cells = [name, str(t.shape), f'{t.pixel_size:.2f}', 'yes' if t.denoised_path else 'no', 'ok']
                tip = ''
            else:
                e = project.issues[name]
                cells = [
                    name, '-' if e.shape is None else str(e.shape), '-' if e.pixel_size is None else f'{e.pixel_size:.2f}',
                    '-' if e.denoised is None else 'yes' if e.denoised else 'no', f'rejected: {e.reason}',
                ]
                tip = str(e)
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(tip)
                if tip:
                    item.setBackground(QColor(255, 220, 220))
                self.table.setItem(r, c, item)
        with_denoised = sum(t.denoised_path is not None for t in project.tomos.values())
        self.summary.setText(f'{len(project.tomos)} usable ({with_denoised} with denoised), {len(project.issues)} rejected')

    # _open_dialog: choose a config.toml
    def _open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, 'Open config', '', 'TOML (*.toml)')
        if path:
            self.open_config(Path(path))

    # _reload: reopen the current config.toml, picking up hand edits and rescanning tomograms
    def _reload(self) -> None:
        if self.project is not None:
            self.open_config(self.project.path)

    # _new_dialog: collect runs, merge them, write the config and open it
    def _new_dialog(self) -> None:
        dialog = NewProjectDialog(self)
        if not dialog.exec():
            return
        values = dialog.values()
        self._busy('Merging runs and scanning tomograms...')
        run_in_background(lambda: _create_and_open(values), self._created, self._failed)

    # _created: show the new project and say what the merge did
    def _created(self, made: tuple[Project, MergeResult]) -> None:
        project, result = made
        self.set_project(project)
        self.status.setText(f'Created with {result.count} tomograms, {len(result.skipped)} duplicates skipped')

    # _busy: block the open, create, reload and close buttons while work runs
    def _busy(self, message: str) -> None:
        for button in (self.open_button, self.new_button, self.reload_button, self.close_button):
            button.setEnabled(False)
        self.status.setText(message)

    # _idle: unblock the buttons
    def _idle(self, message: str) -> None:
        for button in (self.open_button, self.new_button, self.reload_button, self.close_button):
            button.setEnabled(True)
        self.status.setText(message)

    # _failed: show an error from background work
    def _failed(self, message: str) -> None:
        self._idle(message)

# _spin: an integer or float spin box for a value
def _spin(value: float) -> QSpinBox | QDoubleSpinBox:
    if isinstance(value, int):
        box: QSpinBox | QDoubleSpinBox = QSpinBox()
        box.setRange(0, 1_000_000)
    else:
        box = QDoubleSpinBox()
        box.setRange(0, 1_000_000)
        box.setDecimals(2)
    box.setValue(value)
    return box

# _create_and_open: create the project on disk, then open it
def _create_and_open(values: dict[str, object]) -> tuple[Project, MergeResult]:
    path, result = create_project(**values)
    return open_project(path), result
