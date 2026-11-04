'''
pickmix: dialog collecting what is needed to create a project from RELION runs
'''

# Import external dependencies
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

# Import internal pickmix objects
from pickmix.gui.components.path_field import PathField
from pickmix.gui.style import tidy

# NewProjectDialog: runs table plus directories; values() is the argument set for create_project
class NewProjectDialog(QDialog):
    # __init__: build the form
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle('New project')
        self.project_dir = PathField()
        self.raw_dir = PathField()
        self.denoised_dir = PathField()
        self.denoised_suffix = QLineEdit('.denoised')
        self.tomo_job = QLineEdit('Tomograms/job006')
        self.runs = QTableWidget(0, 2)
        self.runs.setHorizontalHeaderLabels(['Run', 'RELION project root'])
        self.runs.horizontalHeader().setStretchLastSection(True)
        self.error = QLabel()
        self.error.setStyleSheet('color: #b00020')
        add = QPushButton('Add run...')
        add.clicked.connect(self._add_dialog)
        remove = QPushButton('Remove selected')
        remove.clicked.connect(self._remove)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout()
        form.addRow('Project directory', self.project_dir)
        form.addRow('Tomogram job (in each root)', self.tomo_job)
        form.addRow('Raw tomograms', self.raw_dir)
        form.addRow('Denoised tomograms (optional)', self.denoised_dir)
        form.addRow('Denoised suffix', self.denoised_suffix)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch()
        layout = QVBoxLayout(self)
        tidy(layout)
        layout.addLayout(form)
        layout.addWidget(self.runs)
        layout.addLayout(row)
        layout.addWidget(self.error)
        layout.addWidget(buttons)
        self.resize(640, 480)

    # add_run: append a row
    def add_run(self, run: str, root: str) -> None:
        r = self.runs.rowCount()
        self.runs.insertRow(r)
        self.runs.setItem(r, 0, QTableWidgetItem(run))
        self.runs.setItem(r, 1, QTableWidgetItem(root))

    # values: arguments for create_project, raising ValueError with a readable message
    def values(self) -> dict[str, object]:
        runs = []
        for r in range(self.runs.rowCount()):
            run, root = self._cell(r, 0), self._cell(r, 1)
            if not run or not root:
                raise ValueError(f'run row {r + 1} needs a name and a project root')
            runs.append((run, Path(root)))
        if not runs:
            raise ValueError('add at least one run')
        for label, field in (('project directory', self.project_dir), ('raw tomograms directory', self.raw_dir)):
            if not field.text():
                raise ValueError(f'{label} is required')
        denoised = self.denoised_dir.text()
        return {
            'project_dir': Path(self.project_dir.text()),
            'runs': runs,
            'tomo_job': self.tomo_job.text().strip(),
            'raw_dir': Path(self.raw_dir.text()),
            'denoised_dir': Path(denoised) if denoised else None,
            'denoised_suffix': self.denoised_suffix.text().strip(),
        }

    # accept: close only when the values are usable
    def accept(self) -> None:
        try:
            self.values()
        except ValueError as e:
            self.error.setText(str(e))
            return
        super().accept()

    # _cell: stripped text of a table cell, empty if unset
    def _cell(self, row: int, col: int) -> str:
        item = self.runs.item(row, col)
        return item.text().strip() if item else ''

    # _add_dialog: choose a project root, name the run after its directory
    def _add_dialog(self) -> None:
        root = QFileDialog.getExistingDirectory(self, 'RELION project root')
        if root:
            self.add_run(Path(root).name, root)

    # _remove: drop the selected rows
    def _remove(self) -> None:
        for r in sorted({i.row() for i in self.runs.selectedIndexes()}, reverse=True):
            self.runs.removeRow(r)
