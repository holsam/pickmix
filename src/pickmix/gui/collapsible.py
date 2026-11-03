'''
pickmix: collapsible section widget
'''

# Import external dependencies
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolButton, QVBoxLayout, QWidget

# Collapsible: a header button with an arrow that shows or hides a widget
class Collapsible(QWidget):
    # __init__: header over content, collapsed unless expanded
    def __init__(self, text: str, content: QWidget, *, expanded: bool = False) -> None:
        super().__init__()
        self.content = content
        self.toggle = QToolButton()
        self.toggle.setText(text)
        self.toggle.setCheckable(True)
        self.toggle.setStyleSheet('QToolButton { border: none; background: transparent; }')
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.toggle, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(content)
        self.toggle.toggled.connect(self._show)
        self.toggle.setChecked(expanded)
        self._show(expanded)

    # _show: arrow and content follow the toggle
    def _show(self, expanded: bool) -> None:
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.content.setVisible(expanded)
