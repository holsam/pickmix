'''
pickmix: shared GUI text levels and spacing
'''

# Import external dependencies
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QLayout, QWidget

# MARGIN, SPACING: outer margin and gap between widgets, pixels
MARGIN: int = 8
SPACING: int = 6

# TITLE_STEP, HEADING_STEP, HINT_STEP: point-size offsets from the application font for each text level
TITLE_STEP: float = 4.0
HEADING_STEP: float = 1.0
HINT_STEP: float = -1.0

# ICON_DIR: bundled icon files
ICON_DIR: Path = Path(__file__).parent / 'icons'

# _SMALL_NATIVE: widget classes whose native font is smaller than a label's
_SMALL_NATIVE: tuple[str, ...] = ('QGroupBox', 'QToolButton', 'QHeaderView')

# body_pt: point size of an ordinary label, the reference every other widget is matched to
def body_pt() -> float:
    return QLabel().font().pointSizeF()

# standardise: give widgets with a smaller native font the body size, so all text is one size unless a level says otherwise
def standardise(app: QApplication) -> None:
    app.setStyleSheet(f'{", ".join(_SMALL_NATIVE)} {{ font-size: {body_pt()}pt; }}')

# icon: a bundled icon by file stem, or None when its file is not there so the caller can fall back to text
def icon(stem: str) -> QIcon | None:
    path = ICON_DIR / f'{stem}.svg'
    return QIcon(str(path)) if path.exists() else None

# help_marker: the question mark icon, or (?) without its file, explaining itself on hover
def help_marker(text: str) -> QLabel:
    label = QLabel()
    help_icon = icon('help')
    if help_icon is None:
        label.setText('(?)')
    else:
        label.setPixmap(help_icon.pixmap(16, 16))
    label.setToolTip(text)
    label.setCursor(Qt.CursorShape.WhatsThisCursor)
    return label

# eye_toggle: small grey eye icon (open when shown, crossed when hidden) on a toggle, or the words (hidden)/(shown) without the icon files
def eye_toggle(button: QPushButton, shown: bool) -> None:
    eye = icon('visibility' if shown else 'visibility_off')
    if eye is None:
        button.setText('(hidden)' if shown else '(shown)')
    else:
        button.setIcon(eye)

# form_label: "Title (?):" for the label column of a form, the marker explaining the field on hover
def form_label(title: str, tip: str) -> QWidget:
    label = QLabel(title)
    label.setToolTip(tip)
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(4)
    row.addWidget(label)
    row.addWidget(help_marker(tip))
    row.addWidget(QLabel(':'))
    row.addStretch()
    return box

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

# bold_safe: style a checkable text button so it is bold when checked without changing its width
def bold_safe(button: QPushButton) -> None:
    plain = 'QPushButton { border: none; background: transparent; padding: 2px 4px; }'
    bold = 'QPushButton { border: none; background: transparent; padding: 2px 4px; font-weight: bold; }'
    button.setStyleSheet(bold)
    button.ensurePolished()
    button.setMinimumWidth(button.sizeHint().width())
    button.setStyleSheet(plain + 'QPushButton:checked { font-weight: bold; }')

# _styled: a label in the application font shifted by step points
def _styled(text: str, step: float, *, bold: bool) -> QLabel:
    label = QLabel(text)
    font = label.font()
    font.setPointSizeF(font.pointSizeF() + step)
    font.setBold(bold)
    label.setFont(font)
    return label
