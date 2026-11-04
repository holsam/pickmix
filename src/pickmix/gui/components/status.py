'''
pickmix: status icons and badges
'''

# Import external dependencies
from typing import Literal
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QTableWidgetItem

# Import internal pickmix objects
from pickmix.gui.components.icons import tinted

# Status: ok is a green tick, warn a yellow warning sign, error a red stop sign, running a blue spinner
type Status = Literal['ok', 'warn', 'error', 'running']

# STATUS_STYLE: icon stem, colour and the text used when the icon file is missing
STATUS_STYLE: dict[Status, tuple[str, str, str]] = {
    'ok': ('check', '#90a959', '✓'),
    'warn': ('warning', '#e9b872', '!'),
    'error': ('error', '#a63d40', '✖'),
    'running': ('refresh', '#6494aa', '…'),
}

# _SIZE: edge in pixels of a status icon
_SIZE: int = 16

# _FRAME_MS, _FRAME_DEG: time between spinner frames and the turn each one makes
_FRAME_MS: int = 80
_FRAME_DEG: int = 30

# status_icon: the icon of a status, or None without its file
def status_icon(status: Status) -> QIcon | None:
    stem, colour, _ = STATUS_STYLE[status]
    return tinted(stem, colour, _SIZE)

# status_item: a centred table cell showing a status, empty for None
def status_item(status: Status | None, tip: str = '') -> QTableWidgetItem:
    item = QTableWidgetItem()
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    if status is not None:
        found = status_icon(status)
        if found is None:
            item.setText(STATUS_STYLE[status][2])
        else:
            item.setIcon(found)
    item.setToolTip(tip)
    return item

# StatusBadge: one status as a label; running turns the icon, so it suits single widgets and short tables
class StatusBadge(QLabel):
    # __init__: start empty
    def __init__(self, status: Status | None = None, tip: str = '') -> None:
        super().__init__()
        self.status: Status | None = None
        self._base: QPixmap | None = None
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(_FRAME_MS)
        self._timer.timeout.connect(self._turn)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_status(status, tip)

    # set_status: show a status, or nothing for None
    def set_status(self, status: Status | None, tip: str = '') -> None:
        self.status = status
        self._timer.stop()
        self.setToolTip(tip)
        self.clear()
        if status is None:
            return
        found = status_icon(status)
        if found is None:
            self.setText(STATUS_STYLE[status][2])
            return
        self._base = found.pixmap(_SIZE, _SIZE)
        self.setPixmap(self._base)
        if status == 'running':
            self._timer.start()

    # _turn: draw the next spinner frame
    def _turn(self) -> None:
        assert self._base is not None
        self._angle = (self._angle + _FRAME_DEG) % 360
        frame = QPixmap(self._base.size())
        frame.fill(Qt.GlobalColor.transparent)
        painter = QPainter(frame)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.translate(frame.width() / 2, frame.height() / 2)
        painter.rotate(self._angle)
        painter.translate(-frame.width() / 2, -frame.height() / 2)
        painter.drawPixmap(0, 0, self._base)
        painter.end()
        self.setPixmap(frame)
