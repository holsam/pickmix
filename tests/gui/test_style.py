'''
pickmix: tests for shared GUI styling
'''

# Import external dependencies
from pytestqt.qtbot import QtBot
from PySide6.QtWidgets import QLabel, QVBoxLayout

# Import internal pickmix objects
from pickmix.gui.style import MARGIN, SPACING, heading, hint, tidy, title

# TestStyle: shared text levels and spacing
class TestStyle:
    # test_levels: title is larger than heading, heading larger than body, body larger than hint
    def test_levels(self, qtbot: QtBot) -> None:
        body = QLabel('x')
        sizes = [w.font().pointSizeF() for w in (title('x'), heading('x'), body, hint('x'))]
        assert sizes == sorted(sizes, reverse=True) and len(set(sizes)) == 4
        assert title('x').font().bold() and not hint('x').font().bold()

    # test_tidy: margins and spacing come from the constants
    def test_tidy(self, qtbot: QtBot) -> None:
        layout = QVBoxLayout()
        tidy(layout)
        assert layout.contentsMargins().left() == MARGIN and layout.spacing() == SPACING
