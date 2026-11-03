'''
pickmix: tomogram dock
'''

# Import external dependencies
from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtWidgets import QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

# Import internal pickmix objects
from pickmix.model import Session

# COLOUR_VISITED, COLOUR_PENDING, COLOUR_CURRENT: line colours for opened, not yet opened and current tomograms
COLOUR_VISITED: QColor = QColor('#2e9e44')
COLOUR_PENDING: QColor = QColor('#e08a00')
COLOUR_CURRENT: QColor = QColor('#2f7fe0')

# TomoDock: one line per tomogram with number, name and picks, coloured by state
class TomoDock(QWidget):
    # __init__: build the widgets
    def __init__(self) -> None:
        super().__init__()
        self.session: Session | None = None
        self.visited = QLabel()
        self.jump_edit = QLineEdit()
        self.jump_edit.setPlaceholderText('go to number or name, then Enter')
        self.header = QLabel()
        self.list = QListWidget()
        self.list.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.header.setFont(self.list.font())
        layout = QVBoxLayout(self)
        layout.addWidget(self.visited)
        layout.addWidget(self.jump_edit)
        layout.addWidget(self.header)
        layout.addWidget(self.list, 1)
        self.jump_edit.returnPressed.connect(self._jump)
        self.list.itemClicked.connect(self._clicked)

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
        self.header.setText(f'{"No.":>3}  {"Tomogram":<{width}}  Picks')
        for row in rows:
            item = self.list.item(row.index)
            item.setText(f'{row.index + 1:>3}  {row.name:<{width}}  {row.count:>5}')
            item.setForeground(COLOUR_CURRENT if row.current else COLOUR_VISITED if row.visited else COLOUR_PENDING)
            font = item.font()
            font.setBold(row.current)
            item.setFont(font)
        if rows:
            self.list.scrollToItem(self.list.item(self.session.index))
        self.visited.setText(f'Visited {sum(r.visited for r in rows)}/{len(rows)}')

    # _jump: go to the typed number or name
    def _jump(self) -> None:
        if self.session is not None and self.session.jump(self.jump_edit.text()):
            self.jump_edit.clear()
            self.jump_edit.clearFocus()
        else:
            self.jump_edit.selectAll()

    # _clicked: go to the clicked tomogram
    def _clicked(self, item: QListWidgetItem) -> None:
        if self.session is not None:
            self.session.go(self.list.row(item))
