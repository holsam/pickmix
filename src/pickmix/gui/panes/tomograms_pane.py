'''
pickmix: tomograms pane, every tomogram of the project with warnings and rejections marked
'''

# Import external dependencies
from collections import Counter
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

# Import internal pickmix objects
from pickmix.gui.components.icons import tinted
from pickmix.gui.components.status import Status, status_item
from pickmix.gui.style import ERROR, MUTED, OK, heading, hint, pad_cells
from pickmix.project import Project

# _COLUMNS: table headings; the first column is the status marker and has none
_COLUMNS: list[str] = ['', 'Name', 'Shape (zyx)', 'Pixel size (Å)', 'Denoised']

# _MARKER_WIDTH: fixed width in pixels of the status marker column, so names always line up
_MARKER_WIDTH: int = 28

# TomogramsPane: title, summary and table
class TomogramsPane(QWidget):
    # __init__: build the table
    def __init__(self) -> None:
        super().__init__()
        self.title = heading('Tomograms')
        self.summary = hint()
        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        pad_cells(self.table)
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setStretchLastSection(True)
        self.table.setColumnWidth(0, _MARKER_WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.title)
        layout.addWidget(self.summary)
        layout.addWidget(self.table, 1)

    # set_project: one row per star row; rejected ones are greyed with an error marker
    def set_project(self, project: Project) -> None:
        self.table.setRowCount(len(project.names))
        for r, name in enumerate(project.names):
            status, tip = tomogram_status(project, name)
            if name in project.tomos:
                t = project.tomos[name]
                cells = [name, str(t.shape), f'{t.pixel_size:.2f}']
                denoised: bool | None = t.denoised_path is not None
            else:
                e = project.issues[name]
                cells = [name, '-' if e.shape is None else str(e.shape), '-' if e.pixel_size is None else f'{e.pixel_size:.2f}']
                denoised = e.denoised
            self.table.setItem(r, 0, status_item(status, tip))
            for c, text in enumerate(cells, start=1):
                item = QTableWidgetItem(text)
                item.setToolTip(tip)
                if status == 'error':
                    item.setForeground(QColor(MUTED))
                self.table.setItem(r, c, item)
            self.table.setItem(r, 4, _flag_item(denoised))
        with_denoised = sum(t.denoised_path is not None for t in project.tomos.values())
        self.summary.setText(f'{len(project.names)} total ({with_denoised} denoised), {len(project.issues)} rejected')

# tomogram_status: the marker and tooltip for one tomogram: error when rejected, warn when usable but off, None when fine
def tomogram_status(project: Project, name: str) -> tuple[Status | None, str]:
    if name in project.issues:
        e = project.issues[name]
        return 'error', f'Rejected: {e.reason}. {e}'
    tomo = project.tomos[name]
    problems = []
    if project.config.denoised_dir is not None and tomo.denoised_path is None:
        problems.append('no denoised volume found')
    usual = Counter(round(t.pixel_size, 2) for t in project.tomos.values()).most_common(1)[0][0]
    if round(tomo.pixel_size, 2) != usual:
        problems.append(f'pixel size {tomo.pixel_size:.2f} Å differs from the usual {usual:.2f} Å')
    return ('warn', '; '.join(problems)) if problems else (None, '')

# _flag_item: a green tick for yes, a red cross for no, a dash when unknown
def _flag_item(value: bool | None) -> QTableWidgetItem:
    item = QTableWidgetItem()
    if value is None:
        item.setText('-')
        return item
    found = tinted('check' if value else 'close', OK if value else ERROR)
    if found is None:
        item.setText('✓' if value else '✗')
    else:
        item.setIcon(found)
    item.setToolTip('Denoised volume found' if value else 'No denoised volume')
    return item
