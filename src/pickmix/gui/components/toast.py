'''
pickmix: short-lived messages over the main window, also printed to the terminal
'''

# Import external dependencies
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QWidget
from shiboken6 import isValid

# Import internal pickmix objects
from pickmix.gui.style import toast_look

# _SHOWN_LINES: most lines of a message the toast shows; stdout always gets all of it
_SHOWN_LINES: int = 3

# _MARGIN: gap in pixels between the toast and the bottom of the window
_MARGIN: int = 24

# Toast: a dark rounded label near the bottom of its parent that hides itself
class Toast(QLabel):
    # __init__: hidden until a message is shown
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        toast_look(self)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.hide()

    # show_message: show a message for ms milliseconds, centred near the bottom of the parent
    def show_message(self, message: str, ms: int = 4000) -> None:
        self.setText(message)
        self.adjustSize()
        parent = self.parentWidget()
        self.move((parent.width() - self.width()) // 2, parent.height() - self.height() - _MARGIN)
        self.raise_()
        self.show()
        self._timer.start(ms)

# _toast: the toast of the main window, set by install
_toast: Toast | None = None

# install: make a toast on a window; notify shows its messages there
def install(window: QWidget) -> Toast:
    global _toast
    _toast = Toast(window)
    return _toast

# notify: print a message to stdout and show its first lines in the toast, if one is installed
def notify(message: str) -> None:
    print(message, flush=True)
    if _toast is None or not isValid(_toast):
        return
    lines = message.splitlines() or ['']
    shown = lines[:_SHOWN_LINES]
    if len(lines) > _SHOWN_LINES:
        shown.append('...')
    _toast.show_message('\n'.join(shown))
