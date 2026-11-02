'''
pickmix: shared GUI text levels and spacing
'''

# Import external dependencies
from PySide6.QtWidgets import QLabel, QLayout

# MARGIN, SPACING: outer margin and gap between widgets, pixels
MARGIN: int = 8
SPACING: int = 6

# TITLE_STEP, HEADING_STEP, HINT_STEP: point-size offsets from the application font for each text level
TITLE_STEP: float = 4.0
HEADING_STEP: float = 1.0
HINT_STEP: float = -1.0

# tidy: apply the shared margin and spacing to a layout
def tidy(layout: QLayout) -> None:
    layout.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
    layout.setSpacing(SPACING)

# title: large bold label, for the name of the thing being worked on
def title(text: str = '') -> QLabel:
    return _styled(text, TITLE_STEP, bold=True)

# heading: slightly larger bold label, for a section
def heading(text: str = '') -> QLabel:
    return _styled(text, HEADING_STEP, bold=True)

# hint: small grey label, for help text
def hint(text: str = '') -> QLabel:
    label = _styled(text, HINT_STEP, bold=False)
    label.setStyleSheet('color: gray')
    return label

# _styled: a label in the application font shifted by step points
def _styled(text: str, step: float, *, bold: bool) -> QLabel:
    label = QLabel(text)
    font = label.font()
    font.setPointSizeF(font.pointSizeF() + step)
    font.setBold(bold)
    label.setFont(font)
    return label
