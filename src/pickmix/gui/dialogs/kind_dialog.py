'''
pickmix: dialog for adding a kind or editing one
'''

# Import external dependencies
import re
from collections.abc import Callable
from pydantic import ValidationError
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

# Import internal pickmix objects
from pickmix.config import Kind
from pickmix.estimate.registry import ESTIMATORS
from pickmix.gui.style import error_look, form_label, tidy

# DELETED: result code of the dialog when the user chose to delete the kind
DELETED: int = 2

# _TEXT: label and help of the rows that are not Kind fields
_TEXT: dict[str, tuple[str, str]] = {
    'name': ('Name', 'Letters, digits and underscores. Changing it renames the kind and its picks.'),
}

# NO_PARENT: text of the parent choice that means no parent
NO_PARENT: str = '(none)'

# KindDialog: sections for the kind's identity, size, estimation and extraction, each row labelled "Title (units) (?):"
class KindDialog(QDialog):
    # __init__: build the form; name and kind are None when adding, others are the kinds besides this one (so the parent choices and the names this kind cannot take), and check returns why a name and kind cannot be saved, or None
    def __init__(
        self, parent: QWidget | None, name: str | None, kind: Kind | None, others: list[str],
        check: Callable[[str, Kind], str | None], *, tomo_angpix: float | None = None,
    ) -> None:
        super().__init__(parent)
        self._check = check
        self._others = others
        self.labels: dict[str, QLabel] = {}
        self.adding = name is None
        kind = kind or Kind(marker_a=100.0, box_a=100.0)
        self.setWindowTitle('Add kind' if self.adding else f'Edit kind {name}')
        self.name_edit = QLineEdit(name or '')
        self.colour_edit = QLineEdit(kind.colour)
        choose = QPushButton('Choose...')
        choose.clicked.connect(self._choose_colour)
        self.marker_spin = _spin(kind.marker_a, minimum=0.01)
        self.box_spin = _spin(kind.box_a)
        self.estimator_box = QComboBox()
        # keep a name the registry does not know yet, so editing never rewrites it
        self.estimator_box.addItems(sorted({*ESTIMATORS, kind.estimator}))
        self.estimator_box.setCurrentText(kind.estimator)
        self.parent_box = QComboBox()
        self.parent_box.addItems([NO_PARENT, *others])
        self.parent_box.setCurrentText(kind.parent or NO_PARENT)
        self.tolerance_spin = _spin(kind.parent_tolerance_a, minimum=0.01)
        self.tilt_box = QCheckBox('Write tilt prior')
        self.tilt_spin = _spin(kind.tilt_prior_deg or 0.0, minimum=-360.0, maximum=360.0)
        self.tilt_box.setChecked(kind.tilt_prior_deg is not None)
        self.tilt_spin.setEnabled(self.tilt_box.isChecked())
        self.tilt_box.toggled.connect(self.tilt_spin.setEnabled)
        self.angpix_spin = _spin(kind.extract_angpix, minimum=0.01, decimals=3)
        self.tomo_button = QPushButton('Tomogram')
        self.tomo_button.setVisible(tomo_angpix is not None)
        if tomo_angpix is not None:
            self.tomo_button.setToolTip(f'Use the tomogram pixel size, {tomo_angpix:g} Å/px')
            self.tomo_button.clicked.connect(lambda: self.angpix_spin.setValue(tomo_angpix))
        self.error = QLabel()
        error_look(self.error)
        self.error.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.delete_button = QPushButton('Delete kind')
        self.delete_button.setVisible(not self.adding)
        self.delete_button.clicked.connect(lambda: self.done(DELETED))
        colour_row = QHBoxLayout()
        colour_row.addWidget(self.colour_edit)
        colour_row.addWidget(choose)
        angpix_row = QHBoxLayout()
        angpix_row.addWidget(self.angpix_spin, 1)
        angpix_row.addWidget(self.tomo_button)        
        tilt_row = QHBoxLayout()
        tilt_row.addWidget(self.tilt_box)
        tilt_row.addWidget(self.tilt_spin)
        footer = QHBoxLayout()
        footer.addWidget(self.delete_button)
        footer.addStretch()
        footer.addWidget(buttons)
        layout = QVBoxLayout(self)
        tidy(layout)
        layout.addWidget(self._section('General', [('name', self.name_edit), ('colour', colour_row)]))
        layout.addWidget(self._section('Size', [('marker_a', self.marker_spin), ('box_a', self.box_spin)]))
        layout.addWidget(self._section('Estimation', [
            ('estimator', self.estimator_box), ('parent', self.parent_box), ('parent_tolerance_a', self.tolerance_spin),
        ]))
        layout.addWidget(self._section('Extraction', [('tilt_prior_deg', tilt_row), ('extract_angpix', angpix_row)]))
        layout.addWidget(self.error)
        layout.addLayout(footer)

    # values: the name and Kind as entered; ValidationError if a field is out of range
    def values(self) -> tuple[str, Kind]:
        parent = self.parent_box.currentText()
        return self.name_edit.text().strip(), Kind(
            marker_a=self.marker_spin.value(), box_a=self.box_spin.value(), estimator=self.estimator_box.currentText(),
            colour=self.colour_edit.text().strip(), parent=None if parent == NO_PARENT else parent,
            parent_tolerance_a=self.tolerance_spin.value(),
            tilt_prior_deg=self.tilt_spin.value() if self.tilt_box.isChecked() else None,
            extract_angpix=self.angpix_spin.value(),
        )

    # accept: close only when the entries make a kind the caller can save; otherwise say why
    def accept(self) -> None:
        message = self._problem()
        self.error.setText(message or '')
        if message is None:
            super().accept()

    # _problem: why the entries cannot be saved, or None
    def _problem(self) -> str | None:
        name = self.name_edit.text().strip()
        if not re.fullmatch(r'[A-Za-z0-9_]+', name):
            return 'Name may only use letters, digits and underscores.'
        if name in self._others:
            return f'A kind called {name!r} already exists.'
        if not QColor(self.colour_edit.text().strip()).isValid():
            return f'{self.colour_edit.text().strip()!r} is not a colour.'
        try:
            _, kind = self.values()
        except ValidationError as e:
            return e.errors()[0]['msg']
        return self._check(name, kind)

    # _section: a titled group box of rows, each labelled from its key's title and description
    def _section(self, title: str, rows: list[tuple[str, QWidget | QHBoxLayout]]) -> QGroupBox:
        box = QGroupBox(title)
        form = QFormLayout(box)
        for key, field in rows:
            label, tip = _TEXT[key] if key in _TEXT else (Kind.model_fields[key].title or key, Kind.model_fields[key].description or '')
            head = form_label(label, tip)
            self.labels[key] = head.findChild(QLabel)
            form.addRow(head, field)
        return box

    # _choose_colour: pick a colour in the system colour dialog
    def _choose_colour(self) -> None:
        colour = QColorDialog.getColor(QColor(self.colour_edit.text().strip()), self)
        if colour.isValid():
            self.colour_edit.setText(colour.name())

# _spin: a float spin box, two decimals unless asked for more
def _spin(value: float, *, minimum: float = 0.0, maximum: float = 1_000_000.0, decimals: int = 2) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setDecimals(decimals)
    box.setValue(value)
    return box
