'''
pickmix: loading pane shown while a project opens or is created
'''

# Import external dependencies
from typing import Literal
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

# Import internal pickmix objects
from pickmix.gui.components.elided_label import ElidedLabel
from pickmix.gui.components.status import StatusBadge
from pickmix.gui.style import MUTED, error_look, tidy, title

# _ICON: edge in pixels of the spinner
_ICON: int = 48

# _WIDTH: widest the column of text grows, pixels
_WIDTH: int = 520

# _TITLES: heading while working and heading after a failure, per kind of work
_TITLES: dict[str, tuple[str, str]] = {
    'open': ('Opening project', 'Could not open project'),
    'create': ('Creating project', 'Could not create project'),
}

# LoadingPane: spinner, what's being opened, and line per step as it happens
class LoadingPane(QWidget):
    # dismissed: Back was pressed after a failure
    dismissed = Signal()

    # __init__: build the pane
    def __init__(self) -> None:
        super().__init__()
        self._kind: Literal['open', 'create'] = 'open'
        self._done: list[str] = []
        self.badge = StatusBadge(size=_ICON)
        self.title = title()
        self.path = ElidedLabel()
        self.path.setStyleSheet(f'color: {MUTED}')
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.back_button = QPushButton('Back')
        self.back_button.clicked.connect(self.dismissed)
        # one column of text, centred and no wider than _WIDTH
        column = QWidget()
        column.setMaximumWidth(_WIDTH)
        inner = QVBoxLayout(column)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.addWidget(self.badge, alignment=Qt.AlignmentFlag.AlignHCenter)
        for widget in (self.title, self.path, self.detail):
            widget.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            inner.addWidget(widget)
        inner.addWidget(self.back_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(column, 100)
        row.addStretch(1)
        layout = QVBoxLayout(self)
        tidy(layout)
        layout.addStretch()
        layout.addLayout(row)
        layout.addStretch()
        self.back_button.hide()

    # begin: start over for opening or creating the project at this path
    def begin(self, kind: Literal['open', 'create'], path: str) -> None:
        self._kind, self._done = kind, []
        self.badge.set_status('running')
        self.title.setText(_TITLES[kind][0])
        self.path.setText(path)
        self.detail.setStyleSheet('')
        self.detail.setText('')
        self.back_button.hide()

    # step: the next step has started, so the one before is ticked off
    def step(self, message: str) -> None:
        lines = [f'✓ {line}' for line in self._done] + [f'{message}...']
        self._done.append(message)
        self.detail.setText('\n'.join(lines))

    # fail: stop spinner and show why
    def fail(self, message: str) -> None:
        self.badge.set_status('error')
        self.title.setText(_TITLES[self._kind][1])
        error_look(self.detail)
        self.detail.setText(message)
        self.back_button.show()
