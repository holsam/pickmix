'''
pickmix: settings pane, volume source, hotkeys and estimator parameters, written to config.toml as they change
'''

# Import external dependencies
from pydantic import BaseModel, ValidationError
from typing import get_args
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QSpinBox, QVBoxLayout, QWidget

# Import internal pickmix objects
from pickmix.config import HOTKEYS, Config, FilamentParams, MatchParams, RingParams
from pickmix.gui.components.collapsible import Collapsible
from pickmix.gui.components.toast import notify
from pickmix.gui.style import form_label, heading
from pickmix.project import Project

# NO_KIND: text of the hotkey choice that leaves a key unused
NO_KIND: str = '(none)'

# ParamsForm: a form for a flat pydantic model of numbers, number pairs and choices between a few words, labelled from the field titles
class ParamsForm(QWidget):
    # changed: a value was committed (arrow, wheel, Enter or focus loss), not set from code
    changed = Signal()

    # __init__: one row per field, "Title (units) (?): [a] - [b]"
    def __init__(self, params: BaseModel) -> None:
        super().__init__()
        self._cls = type(params)
        self._boxes: dict[str, list[QSpinBox | QDoubleSpinBox | QComboBox]] = {}
        self._setting = False
        self.labels: dict[str, QLabel] = {}
        layout = QFormLayout(self)
        for name, value in params:
            info = type(params).model_fields[name]
            values = value if isinstance(value, tuple) else (value,)
            boxes = [_field(v, info.annotation) for v in values]
            self._boxes[name] = boxes
            row = QHBoxLayout()
            for i, box in enumerate(boxes):
                if i:
                    row.addWidget(QLabel('-'))
                row.addWidget(box)
                # no valueChanged per keystroke; it fires when the typed value is committed
                if isinstance(box, QComboBox):
                    box.currentTextChanged.connect(self._emit)
                else:
                    box.setKeyboardTracking(False)
                    box.valueChanged.connect(self._emit)
            row.addStretch()
            # "Title (units) (?):" in the label column, then the values
            head = form_label(info.title or name, info.description or '')
            self.labels[name] = head.findChild(QLabel)
            layout.addRow(head, row)

    # set: show the values of a model without announcing a change
    def set(self, params: BaseModel) -> None:
        self._setting = True
        for name, value in params:
            for box, v in zip(self._boxes[name], value if isinstance(value, tuple) else (value,), strict=True):
                _write(box, v)
        self._setting = False

    # get: a model of the shown values, validated by pydantic
    def get(self) -> BaseModel:
        return self._cls(**{n: tuple(_read(b) for b in boxes) if len(boxes) > 1 else _read(boxes[0]) for n, boxes in self._boxes.items()})

    # _emit: announce a committed change
    def _emit(self, _value: object) -> None:
        if not self._setting:
            self.changed.emit()

# SettingsPane: General (volume source and hotkeys) and Estimators (ring and filament), saved as they change
class SettingsPane(QWidget):
    # config_saved: source or estimator parameters were written to config.toml
    config_saved = Signal()
    # hotkeys_saved: the hotkeys were written to config.toml
    hotkeys_saved = Signal()

    # __init__: build the groups
    def __init__(self) -> None:
        super().__init__()
        self.project: Project | None = None
        self._loading = False
        self.source_box = QComboBox()
        self.source_box.addItems(['denoised', 'raw'])
        self.cache_spin = QSpinBox()
        self.cache_spin.setRange(64, 1_000_000)
        self.cache_spin.setSingleStep(256)
        self.cache_spin.setKeyboardTracking(False)
        self.hotkey_boxes = [QComboBox() for _ in range(HOTKEYS)]
        self.ring_form = ParamsForm(RingParams())
        self.match_form = ParamsForm(MatchParams())
        self.filament_form = ParamsForm(FilamentParams())
        general = QGroupBox('General')
        form = QFormLayout(general)
        form.addRow('Volume source', self.source_box)
        cache = Config.model_fields['cache_mb']
        form.addRow(form_label(cache.title or 'cache_mb', cache.description or ''), self.cache_spin)
        for i, box in enumerate(self.hotkey_boxes):
            form.addRow(f'Hotkey {i + 1}', box)
            box.currentTextChanged.connect(lambda text, i=i: self._hotkey_changed(i, text))
        estimators = QGroupBox('Estimators')
        estimator_box = QVBoxLayout(estimators)
        self.ring_section = Collapsible('Ring', self.ring_form)
        estimator_box.addWidget(self.ring_section)
        self.filament_section = Collapsible('Filament', self.filament_form)
        estimator_box.addWidget(self.filament_section)
        matching = QGroupBox('Template matching')
        matching_box = QVBoxLayout(matching)
        self.match_section = Collapsible('Scan', self.match_form)
        matching_box.addWidget(self.match_section)
        self.setMinimumWidth(max(form.sizeHint().width() for form in (self.ring_form, self.filament_form, self.match_form)) + 48)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(heading('Settings'))
        layout.addWidget(general)
        layout.addWidget(estimators)
        layout.addWidget(matching)
        layout.addStretch()
        self.source_box.currentTextChanged.connect(self._save)
        self.cache_spin.valueChanged.connect(self._save)
        self.ring_form.changed.connect(self._save)
        self.match_form.changed.connect(self._save)
        self.filament_form.changed.connect(self._save)

    # set_project: show a project's settings without saving them back
    def set_project(self, project: Project) -> None:
        self.project = project
        self._loading = True
        self.source_box.setCurrentText(project.config.source)
        self.cache_spin.setValue(project.config.cache_mb)
        self.ring_form.set(project.config.ring)
        self.match_form.set(project.config.match)
        self.filament_form.set(project.config.filament)
        self._loading = False
        self.refresh_hotkeys()

    # refresh_hotkeys: list the project's kinds in every dropdown and select each key's kind
    def refresh_hotkeys(self) -> None:
        if self.project is None:
            return
        self._loading = True
        names = [NO_KIND, *self.project.config.kinds]
        for box, chosen in zip(self.hotkey_boxes, self.project.config.hotkeys, strict=True):
            box.clear()
            box.addItems(names)
            box.setCurrentText(chosen or NO_KIND)
        self._loading = False

    # _save: write source, slice cache, ring, match and filament parameters; a value the config refuses is not written
    def _save(self) -> None:
        if self._loading or self.project is None:
            return
        try:
            self.project.update(source=self.source_box.currentText(), cache_mb=self.cache_spin.value(), ring=self.ring_form.get(), match=self.match_form.get(), filament=self.filament_form.get())
        except ValidationError as e:
            notify(f'Not saved: {e.errors()[0]["msg"]}')
            return
        self.config_saved.emit()

    # _hotkey_changed: save a hotkey choice; a kind lives on one key, so choosing it moves it
    def _hotkey_changed(self, slot: int, text: str) -> None:
        if self._loading or self.project is None:
            return
        self._loading = True
        for i, box in enumerate(self.hotkey_boxes):
            if i != slot and text != NO_KIND and box.currentText() == text:
                box.setCurrentText(NO_KIND)
        self._loading = False
        keys = [b.currentText() for b in self.hotkey_boxes]
        self.project.update(hotkeys=['' if k == NO_KIND else k for k in keys])
        self.hotkeys_saved.emit()

# _field: the widget for a value: a drop-down for a word, over the choices its annotation allows, else a spin box
def _field(value: object, annotation: object) -> QSpinBox | QDoubleSpinBox | QComboBox:
    if isinstance(value, str):
        box = QComboBox()
        box.addItems(list(get_args(annotation)))
        box.setCurrentText(value)
        return box
    return _spin(value)

# _read: the value shown by a field
def _read(box: QSpinBox | QDoubleSpinBox | QComboBox) -> float | str:
    return box.currentText() if isinstance(box, QComboBox) else box.value()

# _write: show a value in a field
def _write(box: QSpinBox | QDoubleSpinBox | QComboBox, value: object) -> None:
    box.setCurrentText(value) if isinstance(box, QComboBox) else box.setValue(value)

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
