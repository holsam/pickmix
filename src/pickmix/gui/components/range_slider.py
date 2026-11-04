'''
pickmix: slider with two handles for a low and a high value
'''

# Import external dependencies
from typing import Literal
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

# _HANDLE: radius in pixels of a handle
_HANDLE: int = 7

# RangeSlider: integer low and high between a minimum and maximum, low never above high
class RangeSlider(QWidget):
    # valueChanged: low or high changed through the user or set_values(emit=True)
    valueChanged = Signal(int, int)

    # __init__: both handles at the ends
    def __init__(self, minimum: int = 0, maximum: int = 1000) -> None:
        super().__init__()
        self._min, self._max = minimum, maximum
        self._low, self._high = minimum, maximum
        self._active: Literal['low', 'high'] = 'low'
        self._dragging: Literal['low', 'high'] | None = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(2 * _HANDLE + 6)

    # sizeHint: as wide as a normal slider and as tall as the handles
    def sizeHint(self) -> QSize:
        return QSize(120, 2 * _HANDLE + 6)

    # set_range: new ends; the values are pulled inside
    def set_range(self, minimum: int, maximum: int) -> None:
        self._min, self._max = minimum, maximum
        self.set_values(self._low, self._high)

    # values: (low, high)
    def values(self) -> tuple[int, int]:
        return self._low, self._high

    # set_values: move both handles, clamped; announces the change only when emit is set
    def set_values(self, low: int, high: int, *, emit: bool = False) -> None:
        low = min(max(low, self._min), self._max)
        high = min(max(high, low), self._max)
        changed = (low, high) != (self._low, self._high)
        self._low, self._high = low, high
        self.update()
        if changed and emit:
            self.valueChanged.emit(low, high)

    # keyPressEvent: Left and Right move the active handle, Up and Down switch handle, PageUp and PageDown move by a tenth
    def keyPressEvent(self, event: QKeyEvent) -> None:
        small, large = max(1, (self._max - self._min) // 100), max(1, (self._max - self._min) // 10)
        steps = {Qt.Key.Key_Left: -small, Qt.Key.Key_Right: small, Qt.Key.Key_PageDown: -large, Qt.Key.Key_PageUp: large}
        if event.key() in steps:
            self._move(self._active, (self._low if self._active == 'low' else self._high) + steps[event.key()])
        elif event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self._active = 'high' if self._active == 'low' else 'low'
            self.update()
        else:
            super().keyPressEvent(event)

    # mousePressEvent: grab the nearest handle (the high one when they overlap and the press is to the right)
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x = event.position().x()
        low_gap, high_gap = abs(x - self._x(self._low)), abs(x - self._x(self._high))
        self._dragging = self._active = 'low' if low_gap < high_gap or (low_gap == high_gap and x < self._x(self._low)) else 'high'
        self.setFocus()
        self._move(self._dragging, self._value_at(x))

    # mouseMoveEvent: drag the grabbed handle
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging is not None:
            self._move(self._dragging, self._value_at(event.position().x()))

    # mouseReleaseEvent: let go
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._dragging = None

    # paintEvent: groove, the span between the handles, then the handles
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette, mid = self.palette(), self.height() / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(palette.mid())
        painter.drawRoundedRect(QRectF(_HANDLE, mid - 2, self.width() - 2 * _HANDLE, 4), 2, 2)
        painter.setBrush(palette.highlight())
        painter.drawRoundedRect(QRectF(self._x(self._low), mid - 2, self._x(self._high) - self._x(self._low), 4), 2, 2)
        for which, value in (('low', self._low), ('high', self._high)):
            ring = palette.highlight().color() if self.hasFocus() and which == self._active else palette.dark().color()
            painter.setPen(QPen(ring, 2))
            painter.setBrush(palette.base())
            painter.drawEllipse(QPointF(self._x(value), mid), _HANDLE - 1, _HANDLE - 1)

    # _x: pixel position of a value
    def _x(self, value: int) -> float:
        span = max(self._max - self._min, 1)
        return _HANDLE + (value - self._min) / span * (self.width() - 2 * _HANDLE)

    # _value_at: value under a pixel position
    def _value_at(self, x: float) -> int:
        span = max(self._max - self._min, 1)
        return round(self._min + (x - _HANDLE) / max(self.width() - 2 * _HANDLE, 1) * span)

    # _move: set one handle, never past the other
    def _move(self, which: Literal['low', 'high'], value: int) -> None:
        if which == 'low':
            self.set_values(min(value, self._high), self._high, emit=True)
        else:
            self.set_values(self._low, max(value, self._low), emit=True)
