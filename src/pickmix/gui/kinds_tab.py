'''
pickmix: Kinds tab, listing the kinds, choosing hotkeys and editing both in config.toml
'''

# Import external dependencies
from pydantic import ValidationError
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QScrollArea, QToolButton, QVBoxLayout, QWidget,
)

# Import internal pickmix objects
from pickmix.config import HOTKEYS, Kind
from pickmix.estimates import EstimateService
from pickmix.gui.average_pane import AveragePane
from pickmix.gui.kind_dialog import DELETED, KindDialog
from pickmix.gui.style import heading, icon
from pickmix.model import Session
from pickmix.project import Project

# NO_KIND: text of the hotkey choice that leaves a key unused
NO_KIND: str = '(none)'

# KindsTab: the kinds as a list with an edit button each, and one dropdown per hotkey
class KindsTab(QWidget):
    # config_saved: the kinds or hotkeys were written to config.toml
    config_saved = Signal()

    # __init__: build the Kinds and Hotkeys panes over the Average pane
    def __init__(self) -> None:
        super().__init__()
        self.project: Project | None = None
        self.session: Session | None = None
        self.service: EstimateService | None = None
        self._loading = False
        self.details: dict[str, QLabel] = {}
        self.edit_buttons: dict[str, QToolButton] = {}
        self.add_button = QPushButton('Add')
        self.add_button.clicked.connect(self.add_kind)
        self.cards = QVBoxLayout()
        self.cards.addStretch()
        holder = QWidget()
        holder.setLayout(self.cards)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(holder)
        scroll.setMinimumHeight(220)
        head = QHBoxLayout()
        head.addWidget(heading('Kinds'))
        head.addWidget(self.add_button)
        head.addStretch()
        kinds_pane = QVBoxLayout()
        kinds_pane.addLayout(head)
        kinds_pane.addWidget(scroll, 1)
        self.hotkey_boxes = [QComboBox() for _ in range(HOTKEYS)]
        keys = QFormLayout()
        for i, box in enumerate(self.hotkey_boxes):
            keys.addRow(str(i + 1), box)
            box.currentTextChanged.connect(lambda text, i=i: self._hotkey_changed(i, text))
        hotkeys_pane = QVBoxLayout()
        hotkeys_pane.addWidget(heading('Hotkeys'))
        hotkeys_pane.addLayout(keys)
        hotkeys_pane.addStretch()
        top = QHBoxLayout()
        top.addLayout(kinds_pane, 2)
        top.addLayout(hotkeys_pane, 1)
        self.status = QLabel()
        self.average = AveragePane()
        layout = QVBoxLayout(self)
        layout.addLayout(top, 1)
        layout.addWidget(self.status)
        layout.addWidget(self.average)

    # set_project: show the kinds and hotkeys of a project
    def set_project(self, project: Project) -> None:
        self.project = project
        self.status.setText('')
        self._show()

    # set_session: the picks and estimates that follow a kind when it is renamed or deleted, or none; the Average pane uses them too
    def set_session(self, session: Session | None, service: EstimateService | None) -> None:
        self.session, self.service = session, service
        self.average.set_session(session, service)

    # kind_names: the kinds listed, in order
    def kind_names(self) -> list[str]:
        return list(self.details)

    # add_kind: open the dialog for a new kind
    def add_kind(self) -> None:
        self._edit(None)

    # edit_kind: open the dialog for an existing kind
    def edit_kind(self, name: str) -> None:
        self._edit(name)

    # _show: rebuild the list and the hotkey dropdowns from the config
    def _show(self) -> None:
        assert self.project is not None
        self._loading = True
        while self.cards.count() > 1:
            item = self.cards.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.details, self.edit_buttons = {}, {}
        for i, (name, kind) in enumerate(self.project.config.kinds.items()):
            self.cards.insertWidget(i, self._card(name, kind))
        names = [NO_KIND, *self.project.config.kinds]
        for box, chosen in zip(self.hotkey_boxes, self.project.config.hotkeys, strict=True):
            box.clear()
            box.addItems(names)
            box.setCurrentText(chosen or NO_KIND)
        self._loading = False

    # _card: the name as a subheading with its edit button, then the kind's values as plain text
    def _card(self, name: str, kind: Kind) -> QWidget:
        button = QToolButton()
        edit_icon = icon('edit')
        if edit_icon is None:
            button.setText('Edit')
        else:
            button.setIcon(edit_icon)
        button.setAutoRaise(True)
        button.setToolTip(f'Edit {name}')
        button.clicked.connect(lambda _checked=False, n=name: self.edit_kind(n))
        detail = QLabel(_describe(kind))
        self.details[name], self.edit_buttons[name] = detail, button
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        row = QHBoxLayout()
        row.addWidget(heading(name))
        row.addWidget(button)
        row.addStretch()
        card = QWidget()
        box = QVBoxLayout(card)
        box.setContentsMargins(0, 0, 0, 0)
        box.addLayout(row)
        box.addWidget(detail)
        box.addWidget(line)
        return card

    # _edit: run the dialog for a new kind (name None) or an existing one, then save, delete or do nothing
    def _edit(self, name: str | None) -> None:
        if self.project is None:
            return
        kinds = self.project.config.kinds
        dialog = KindDialog(self, name, None if name is None else kinds[name], [k for k in kinds if k != name], lambda new, kind: self._problem(new, kind, name))
        result = dialog.exec()
        if result == DELETED and name is not None:
            self._delete(name)
        elif result:
            self._apply(*dialog.values(), old=name)

    # _proposal: the config changes for saving a kind. Renaming keeps its place, hotkey and children; a new kind takes the first free hotkey
    def _proposal(self, name: str, kind: Kind, old: str | None) -> dict[str, object]:
        assert self.project is not None
        config = self.project.config
        if old is None:
            hotkeys = list(config.hotkeys)
            if '' in hotkeys:
                hotkeys[hotkeys.index('')] = name
            return {'kinds': {**config.kinds, name: kind}, 'hotkeys': hotkeys}
        kinds = {(name if k == old else k): kind if k == old else v.model_copy(update={'parent': name}) if v.parent == old else v for k, v in config.kinds.items()}
        return {'kinds': kinds, 'hotkeys': [name if h == old else h for h in config.hotkeys]}

    # _problem: why a proposed kind cannot be saved, or None
    def _problem(self, name: str, kind: Kind, old: str | None) -> str | None:
        assert self.project is not None
        if name != old and name in self.project.config.kinds:
            return f'A kind called {name!r} already exists.'
        try:
            self.project.config.replace(**self._proposal(name, kind, old))
        except ValidationError as e:
            return e.errors()[0]['msg']
        return None

    # _apply: save a new or edited kind; a rename takes the kind's picks and fits with it
    def _apply(self, name: str, kind: Kind, *, old: str | None = None) -> None:
        assert self.project is not None
        self.project.update(**self._proposal(name, kind, old))
        if old is not None and old != name:
            if self.service is not None:
                self.service.store.rename_kind(old, name)
            if self.session is not None:
                self.session.store.rename_kind(old, name)
        self._saved()

    # _delete: remove a kind and its picks, asking first if it has any; refused with a reason if the config would not be valid
    def _delete(self, name: str) -> None:
        assert self.project is not None
        config = self.project.config
        changes = {'kinds': {k: v for k, v in config.kinds.items() if k != name}, 'hotkeys': ['' if h == name else h for h in config.hotkeys]}
        try:
            config.replace(**changes)
        except ValidationError as e:
            self.status.setText(f'Not deleted: {e.errors()[0]["msg"]}')
            return
        picks = self.session.store.all(name) if self.session is not None else []
        if picks and not self._confirm(f'Delete kind {name!r} and its {len(picks)} picks in {len({p.tomogram for p in picks})} tomograms? This cannot be undone.'):
            return
        self.project.update(**changes)
        if self.session is not None:
            self.session.store.remove_kind(name)
        self._saved()

    # _confirm: ask a yes or no question
    def _confirm(self, text: str) -> bool:
        return QMessageBox.question(self, 'Delete kind', text) == QMessageBox.StandardButton.Yes

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
        self._saved()

    # _saved: show the config as written and tell the other tabs
    def _saved(self) -> None:
        self._show()
        self.status.setText('Saved')
        self.config_saved.emit()

# _describe: a kind's values as two lines of plain text
def _describe(kind: Kind) -> str:
    box = 'from estimator' if kind.box_a == 0 else f'{kind.box_a:g} Å'
    parent = 'none' if kind.parent is None else f'{kind.parent} (within {kind.parent_tolerance_a:g} Å)'
    tilt = 'none' if kind.tilt_prior_deg is None else f'{kind.tilt_prior_deg:g}°'
    return (
        f'Marker: {kind.marker_a:g} Å    Box: {box}    Estimator: {kind.estimator}\n'
        f'Colour: {kind.colour}    Parent: {parent}    Tilt prior: {tilt}    Extract: {kind.extract_angpix:g} Å/px'
    )
