'''
pickmix: kinds pane, listing the kinds, choosing hotkeys and editing both in config.toml
'''

# Import external dependencies
import html
from pydantic import ValidationError
from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QScrollArea, QToolButton, QVBoxLayout, QWidget,
)

# Import internal pickmix objects
from pickmix.config import Kind
from pickmix.estimates import EstimateService
from pickmix.gui.dialogs.kind_dialog import DELETED, KindDialog
from pickmix.gui.style import heading, icon
from pickmix.model import Session
from pickmix.project import Project

# _CARD_WIDTH: narrowest a kind's block gets, in pixels, before the grid drops a column
_CARD_WIDTH: int = 260

# KindsPane: the kinds as a list with an edit button each, and one dropdown per hotkey
class KindsPane(QWidget):
    # config_saved: the kinds or hotkeys were written to config.toml
    config_saved = Signal()

    # __init__: build the Kinds and Hotkeys panes
    def __init__(self) -> None:
        super().__init__()
        self.project: Project | None = None
        self.session: Session | None = None
        self.service: EstimateService | None = None
        self.details: dict[str, QLabel] = {}
        self.edit_buttons: dict[str, QToolButton] = {}
        self.add_button = QPushButton('Add')
        self.add_button.clicked.connect(self.add_kind)
        self.cards: list[QWidget] = []
        self._columns = 0
        self.grid = QGridLayout()
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        holder = QWidget()
        holder.setLayout(self.grid)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(holder)
        self.scroll.setMinimumHeight(220)
        self.scroll.viewport().installEventFilter(self)
        head = QHBoxLayout()
        head.addWidget(heading('Kinds'))
        head.addStretch()
        head.addWidget(self.add_button)
        self.status = QLabel()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(head)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(self.status)

    # set_project: show the kinds and hotkeys of a project
    def set_project(self, project: Project) -> None:
        self.project = project
        self.status.setText('')
        self._show()

    # set_session: the picks and estimates that follow a kind when it is renamed or deleted, or none; the Average pane uses them too
    def set_session(self, session: Session | None, service: EstimateService | None) -> None:
        self.session, self.service = session, service

    # eventFilter: lay the kinds out again when the list is resized
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.scroll.viewport() and event.type() == QEvent.Type.Resize:
            self._reflow()
        return super().eventFilter(watched, event)

    # kind_names: the kinds listed, in order
    def kind_names(self) -> list[str]:
        return list(self.details)

    # add_kind: open the dialog for a new kind
    def add_kind(self) -> None:
        self._edit(None)

    # edit_kind: open the dialog for an existing kind
    def edit_kind(self, name: str) -> None:
        self._edit(name)

    # _show: rebuild the list from the config
    def _show(self) -> None:
        assert self.project is not None
        for card in self.cards:
            self.grid.removeWidget(card)
            card.deleteLater()
        self.details, self.edit_buttons, self.cards = {}, {}, []
        for name, kind in self.project.config.kinds.items():
            self.cards.append(self._card(name, kind))
        self._columns = 0
        self._reflow()

    # _reflow: put the kinds in as many equal columns as fit, filling across then down
    def _reflow(self) -> None:
        columns = max(1, self.scroll.viewport().width() // _CARD_WIDTH)
        if columns == self._columns:
            return
        for c in range(self._columns):
            self.grid.setColumnStretch(c, 0)
        for card in self.cards:
            self.grid.removeWidget(card)
        for i, card in enumerate(self.cards):
            self.grid.addWidget(card, i // columns, i % columns)
        for c in range(columns):
            self.grid.setColumnStretch(c, 1)
        self._columns = columns

    # _card: the name as a subheading with its edit button, then the kind's values as plain text
    def _card(self, name: str, kind: Kind) -> QWidget:
        button = QToolButton()
        edit_icon = icon('edit')
        if edit_icon is None:
            button.setText('Edit')
        else:
            button.setIcon(edit_icon)
        button.setAutoRaise(True)
        button.setStyleSheet('QToolButton { border: none; background: transparent; }')
        button.setToolTip(f'Edit {name}')
        button.clicked.connect(lambda _checked=False, n=name: self.edit_kind(n))
        detail = QLabel(_describe(kind))
        detail.setTextFormat(Qt.TextFormat.RichText)
        self.details[name], self.edit_buttons[name] = detail, button
        row = QHBoxLayout()
        row.addWidget(heading(name))
        row.addWidget(button)
        row.addStretch()
        card = QWidget()
        box = QVBoxLayout(card)
        box.setContentsMargins(0, 0, 0, 0)
        box.addLayout(row)
        box.addWidget(detail)
        box.addStretch()
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

    # _saved: show the config as written and tell the other tabs
    def _saved(self) -> None:
        self._show()
        self.status.setText('Saved')
        self.config_saved.emit()

# _describe: a kind's values as a vertical list with bold keys
def _describe(kind: Kind) -> str:
    box = 'from estimator' if kind.box_a == 0 else f'{kind.box_a:g} Å'
    parent = 'none' if kind.parent is None else f'{kind.parent} (within {kind.parent_tolerance_a:g} Å)'
    tilt = 'none' if kind.tilt_prior_deg is None else f'{kind.tilt_prior_deg:g}°'
    pairs = [
        ('Marker', f'{kind.marker_a:g} Å'), ('Box', box), ('Estimator', kind.estimator), ('Colour', kind.colour),
        ('Parent', parent), ('Tilt prior', tilt), ('Extract', f'{kind.extract_angpix:g} Å/px'),
    ]
    return '<br>'.join(f'<b>{key}:</b> {html.escape(value)}' for key, value in pairs)
