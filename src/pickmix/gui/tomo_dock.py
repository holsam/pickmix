'''
pickmix: tomogram dock
'''

# Import external dependencies
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

# Import internal pickmix objects
from pickmix.model import Session

# TomoDock: one line per tomogram, current marked > and opened marked *
class TomoDock(QWidget):
    # __init__: build the widgets
    def __init__(self) -> None:
        super().__init__()
        self.session: Session | None = None
        self.jump_edit = QLineEdit()
        self.jump_edit.setPlaceholderText('go to number or name, then Enter')
        self.list = QListWidget()
        self.list.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.totals = QLabel()
        self.totals.setFont(self.list.font())
        layout = QVBoxLayout(self)
        layout.addWidget(self.jump_edit)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.totals)
        self.jump_edit.returnPressed.connect(self._jump)
        self.list.itemClicked.connect(self._clicked)

    # set_session: show a session and follow its picks and navigation
    def set_session(self, session: Session) -> None:
        self.session = session
        session.store.listeners.append(self.refresh)
        session.goto_listeners.append(self.refresh)
        self.list.clear()
        self.refresh()

    # refresh: update the lines and totals in place
    def refresh(self) -> None:
        if self.session is None:
            return
        rows = self.session.rows()
        if self.list.count() != len(rows):
            self.list.clear()
            for _ in rows:
                self.list.addItem(QListWidgetItem())
        for row in rows:
            self.list.item(row.index).setText(f'{">" if row.current else " "} {"*" if row.visited else " "} {row.index + 1:>3}  {row.name}  {row.count}')
        if rows:
            self.list.scrollToItem(self.list.item(self.session.index))
        opened = sum(r.visited for r in rows)
        lines = [f'visited  {opened}/{len(rows)}']
        lines += [f'{name:<10}{self.session.store.total(name)}' for name in self.session.project.config.kinds]
        self.totals.setText('\n'.join(lines))

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
