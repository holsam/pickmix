'''
pickmix: tomogram pane
'''

# Import external dependencies
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtWidgets import QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

# Import internal pickmix objects
from pickmix.gui.style import OK, RUNNING, WARN
from pickmix.model import Session

# COLOUR_VISITED, COLOUR_PENDING, COLOUR_CURRENT: line colours for opened, not yet opened and current tomograms
COLOUR_VISITED: QColor = QColor(OK)
COLOUR_PENDING: QColor = QColor(WARN)
COLOUR_CURRENT: QColor = QColor(RUNNING)

# TomoPane: one line per tomogram with number, name and picks, coloured by state
class TomoPane(QWidget):
    # __init__: build the widgets
    def __init__(self) -> None:
        super().__init__()
        self.session: Session | None = None
        self.visited = QLabel()
        self.jump_edit = QLineEdit()
        self.jump_edit.setPlaceholderText('go to number or name')
        self.header = QLabel()
        self.list = QListWidget()
        self.list.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.header.setFont(self.list.font())
        # no highlight
        self.list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._live = QTimer(self)
        self._live.setSingleShot(True)
        self._live.setInterval(300)
        self._live.timeout.connect(self._live_jump)
        layout = QVBoxLayout(self)
        layout.addWidget(self.visited)
        layout.addWidget(self.jump_edit)
        layout.addWidget(self.header)
        layout.addWidget(self.list, 1)
        self.list.itemClicked.connect(self._clicked)
        self.jump_edit.textChanged.connect(lambda _text: self._live.start())

    # set_session: show a session and follow its picks and navigation
    def set_session(self, session: Session) -> None:
        self.session = session
        session.store.listeners.append(self.refresh)
        session.goto_listeners.append(self.refresh)
        self.list.clear()
        self.refresh()

    # refresh: update the lines in place
    def refresh(self) -> None:
        if self.session is None:
            return
        rows = self.session.rows()
        if self.list.count() != len(rows):
            self.list.clear()
            for _ in rows:
                self.list.addItem(QListWidgetItem())
        width = max((len(r.name) for r in rows), default=0)
        self.header.setText(f'{"No.":<3}  {"Tomogram":<{width}}  Picks')
        for row in rows:
            item = self.list.item(row.index)
            item.setText(f'{row.index + 1:<3}  {row.name:<{width}}  {row.count:>5}')
            item.setForeground(COLOUR_CURRENT if row.current else COLOUR_VISITED if row.visited else COLOUR_PENDING)
            font = item.font()
            font.setBold(row.current)
            item.setFont(font)
        if rows:
            self.list.scrollToItem(self.list.item(self.session.index))
        self.visited.setText(f'Visited {sum(r.visited for r in rows)}/{len(rows)}')

    # _live_jump: show the tomogram the typed text matches, keeping the text so typing can go on
    def _live_jump(self) -> None:
        if self.session is None:
            return
        hit = self.session.find(self.jump_edit.text())
        if hit is not None and hit != self.session.index:
            self.session.go(hit)

    # _clicked: go to the clicked tomogram
    def _clicked(self, item: QListWidgetItem) -> None:
        if self.session is not None:
            self.session.go(self.list.row(item))
