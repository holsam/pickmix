'''
pickmix: Kinds tab, editing the kinds table and saving it to config.toml
'''

# Import external dependencies
from pydantic import ValidationError
from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QGroupBox, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

# Import internal pickmix objects
from pickmix.config import Kind
from pickmix.estimate.registry import ESTIMATORS
from pickmix.project import Project

# _COLUMNS: kinds table headings; the first is the kind name, the rest are Kind fields in order
_COLUMNS: list[str] = [
    'Name', 'Marker (A)', 'Box (A, 0 = estimator)', 'Estimator', 'Colour', 'Parent',
    'Parent tolerance (A)', 'Tilt prior (deg)', 'Extract A/px',
]

# _ESTIMATOR_COL, _COLOUR_COL: columns needing more than plain text
_ESTIMATOR_COL: int = 3
_COLOUR_COL: int = 4

# KindsTab: one row per kind, row order is hotkey order
class KindsTab(QWidget):
    # config_saved: the kinds were written to config.toml
    config_saved = Signal()

    # __init__: build the layout
    def __init__(self) -> None:
        super().__init__()
        self.project: Project | None = None
        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemChanged.connect(self._paint)
        self.status = QLabel()
        buttons = QHBoxLayout()
        for text, slot in (
            ('Add', self.add_kind), ('Remove', self.remove_selected), ('Up', lambda: self._move(-1)),
            ('Down', lambda: self._move(1)), ('Save', self.save),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch()
        average = QGroupBox('Average')
        QVBoxLayout(average).addWidget(QLabel('Mean projection and montage per kind: available from phase 8.'))
        average.setEnabled(False)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Row order sets the 1 to 9 hotkeys in the Pick tab.'))
        layout.addWidget(self.table)
        layout.addLayout(buttons)
        layout.addWidget(self.status)
        layout.addWidget(average)

    # set_project: show the kinds of a project
    def set_project(self, project: Project) -> None:
        self.project = project
        self.table.setRowCount(0)
        for name, kind in project.config.kinds.items():
            self._write_row(self.table.rowCount(), _to_cells(name, kind))
        self.status.setText('')

    # add_kind: append a passthrough kind with placeholder values for the user to edit
    def add_kind(self) -> None:
        taken = {self._read_row(r)[0] for r in range(self.table.rowCount())}
        name = next(f'kind{i}' for i in range(1, 1000) if f'kind{i}' not in taken)
        self._write_row(self.table.rowCount(), _to_cells(name, Kind(marker_a=100.0, box_a=100.0)))

    # remove_selected: drop the selected rows
    def remove_selected(self) -> None:
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)

    # collect: the kinds in the table, in order; raises ValueError naming the problem
    def collect(self) -> dict[str, Kind]:
        kinds: dict[str, Kind] = {}
        for r in range(self.table.rowCount()):
            try:
                name, kind = _from_cells(self._read_row(r))
            except ValueError as e:
                raise ValueError(f'row {r + 1}: {e}') from e
            if name in kinds:
                raise ValueError(f'row {r + 1}: duplicate kind name {name!r}')
            if not QColor(kind.colour).isValid():
                raise ValueError(f'row {r + 1}: {kind.colour!r} is not a colour')
            kinds[name] = kind
        return kinds

    # save: validate the whole config with these kinds and write it, or show why not
    def save(self) -> None:
        if self.project is None:
            return
        try:
            self.project.update(kinds=self.collect())
        except ValidationError as e:
            self.status.setText(f'Not saved: {e.errors()[0]["msg"]}')
            return
        except ValueError as e:
            self.status.setText(f'Not saved: {e}')
            return
        self.status.setText('Saved')
        self.config_saved.emit()

    # _read_row: the cell strings of a row
    def _read_row(self, r: int) -> list[str]:
        out = []
        for c in range(len(_COLUMNS)):
            if c == _ESTIMATOR_COL:
                out.append(self.table.cellWidget(r, c).currentText())
            else:
                item = self.table.item(r, c)
                out.append(item.text().strip() if item else '')
        return out

    # _write_row: set the cell strings of a row, creating it if needed
    def _write_row(self, r: int, cells: list[str]) -> None:
        if r >= self.table.rowCount():
            self.table.insertRow(r)
        for c, text in enumerate(cells):
            if c == _ESTIMATOR_COL:
                # keep a name the registry does not know yet, so loading never rewrites it
                combo = QComboBox()
                combo.addItems(sorted({*ESTIMATORS, text}))
                combo.setCurrentText(text)
                self.table.setCellWidget(r, c, combo)
            else:
                item = QTableWidgetItem(text)
                self.table.setItem(r, c, item)
                if c == _COLOUR_COL:
                    self._paint(item)

    # _move: swap the selected row with its neighbour
    def _move(self, delta: int) -> None:
        rows = {i.row() for i in self.table.selectedIndexes()}
        if len(rows) != 1:
            return
        a = rows.pop()
        b = a + delta
        if not 0 <= b < self.table.rowCount():
            return
        cells_a, cells_b = self._read_row(a), self._read_row(b)
        self._write_row(a, cells_b)
        self._write_row(b, cells_a)
        self.table.selectRow(b)

    # _paint: shade a colour cell with its colour
    def _paint(self, item: QTableWidgetItem) -> None:
        if item.column() == _COLOUR_COL:
            colour = QColor(item.text().strip())
            item.setBackground(colour if colour.isValid() else QColor('white'))

# _to_cells: the table strings of a kind
def _to_cells(name: str, kind: Kind) -> list[str]:
    tilt = '' if kind.tilt_prior_deg is None else f'{kind.tilt_prior_deg:g}'
    return [
        name, f'{kind.marker_a:g}', f'{kind.box_a:g}', kind.estimator, kind.colour, kind.parent or '',
        f'{kind.parent_tolerance_a:g}', tilt, f'{kind.extract_angpix:g}',
    ]

# _from_cells: the name and Kind for table strings, ValueError on anything unreadable
def _from_cells(cells: list[str]) -> tuple[str, Kind]:
    name, marker, box, estimator, colour, parent, tolerance, tilt, angpix = cells
    try:
        kind = Kind(
            marker_a=float(marker), box_a=float(box), estimator=estimator, colour=colour, parent=parent or None,
            parent_tolerance_a=float(tolerance), tilt_prior_deg=float(tilt) if tilt else None, extract_angpix=float(angpix),
        )
    except ValidationError as e:
        err = e.errors()[0]
        raise ValueError(f'{name or "(unnamed)"}: {err["loc"][0]} {err["msg"]}') from e
    return name, kind
