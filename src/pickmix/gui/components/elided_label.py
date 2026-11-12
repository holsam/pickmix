'''
pickmix: label that shortens long text to fit
'''

# Import external dependencies
from PySide6.QtCore import Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QLabel, QSizePolicy

# ElidedLabel: one line of text with middle cut out as "…" when it's wider than label
class ElidedLabel(QLabel):
    # __init__: take width from layout
    def __init__(self, text: str = '') -> None:
        super().__init__()
        self._full = ''
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    # setText: keep full text and show as much of it as fits
    def setText(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self._elide()

    # resizeEvent: refit text
    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._elide()

    # _elide: show text cut to width
    def _elide(self) -> None:
        super().setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle, self.width()))
