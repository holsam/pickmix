'''
pickmix: shared GUI text levels and spacing
'''

# Import external dependencies
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import QAbstractItemView, QApplication, QHBoxLayout, QLabel, QLayout, QPushButton, QScrollArea, QTableWidget, QToolButton, QVBoxLayout, QWidget

# Import internal pickmix objects
from pickmix.gui.components.icons import icon, tinted

# MARGIN, SPACING: outer margin and gap between widgets, pixels
MARGIN: int = 8
SPACING: int = 6

# CELL_PADDING: horizontal padding in pixels inside every table cell and heading
CELL_PADDING: int = 14

# RADIUS: corner radius of rounded buttons, pixels
RADIUS: int = 16

# ICON_COLOUR: colour of every action icon
ICON_COLOUR: str = '#ffffff'

# MEDIUM_PAD: pixels added to a medium button's icon edge to get its square size
MEDIUM_PAD: int = 16

# BIG_ICON, BIG_GAP: edge in pixels of the icon on a big button, and the pixels between it and the text
BIG_ICON: int = 48
BIG_GAP: int = 8

# OK, WARN, ERROR, RUNNING: state colours, shared by status icons, table marks and anything else that shows a state
OK: str = '#90a959'
WARN: str = '#e9b872'
ERROR: str = '#a63d40'
RUNNING: str = '#6494aa'

# MUTED: grey of hints and of anything dimmed or unavailable
MUTED: str = '#808080'

# LABEL_BG, OVERLAY_TEXT: translucent dark box and white text drawn over images
LABEL_BG: QColor = QColor(0, 0, 0, 150)
OVERLAY_TEXT: QColor = QColor('white')

# WELL_BG, WELL_TEXT: dark backdrop and dim placeholder text of the frames that hold images
WELL_BG: str = '#141414'
WELL_TEXT: str = '#888'

# TITLE_STEP, HEADING_STEP, HINT_STEP: point-size offsets from the application font for each text level
TITLE_STEP: float = 4.0
HEADING_STEP: float = 1.0
HINT_STEP: float = -1.0

# _SMALL_NATIVE: widget classes whose native font is smaller than a label's
_SMALL_NATIVE: tuple[str, ...] = ('QGroupBox', 'QToolButton', 'QHeaderView')

# body_pt: point size of an ordinary label, the reference every other widget is matched to
def body_pt() -> float:
    return QLabel().font().pointSizeF()

# standardise: give widgets with a smaller native font the body size, so all text is one size unless a level says otherwise
def standardise(app: QApplication) -> None:
    app.setStyleSheet(f'{", ".join(_SMALL_NATIVE)} {{ font-size: {body_pt()}pt; }}')

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

# view_toggle: a checkable toggle named after what it shows, its eye icon open when shown and crossed when hidden
def view_toggle(name: str) -> QToolButton:
    button = QToolButton()
    button.setText(name)
    button.setCheckable(True)
    button.setChecked(True)
    button.setAutoRaise(True)
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setStyleSheet('QToolButton { border: none; background: transparent; }')
    button.setToolTip(f'Show or hide {name.lower()}')
    button.toggled.connect(lambda shown, b=button, n=name: _view_look(b, n, shown))
    _view_look(button, name, True)
    return button

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
    label.setStyleSheet(f'color: {MUTED}')
    return label

# error_look: the error colour for a label that shows a problem
def error_look(label: QLabel) -> None:
    label.setStyleSheet(f'color: {ERROR}')

# bold_safe: style a checkable text button so it is bold when checked without changing its width
def bold_safe(button: QPushButton) -> None:
    plain = 'QPushButton { border: none; background: transparent; padding: 2px 4px; }'
    bold = 'QPushButton { border: none; background: transparent; padding: 2px 4px; font-weight: bold; }'
    button.setStyleSheet(bold)
    button.ensurePolished()
    button.setMinimumWidth(button.sizeHint().width())
    button.setStyleSheet(plain + 'QPushButton:checked { font-weight: bold; }')

# rounded: give a button rounded corners in the theme colours; a stylesheet is needed for any radius
def rounded(button: QPushButton) -> None:
    button.setStyleSheet(
        f'QPushButton {{ background: palette(button); border: 1px solid palette(mid); border-radius: {RADIUS}px; }}'
        'QPushButton:hover { background: palette(midlight); }'
        'QPushButton:pressed { background: palette(mid); }'
    )

# toast_look: dark translucent rounded box with white text
def toast_look(label: QLabel) -> None:
    label.setStyleSheet('background: rgba(40, 40, 40, 230); color: white; border-radius: 6px; padding: 8px 12px;')

# big_button: icon over text with a fixed gap when the icon file exists, text alone otherwise
def big_button(text: str, stem: str) -> QPushButton:
    button = QPushButton()
    button.setMinimumSize(200, 150)
    rounded(button)
    inner = QVBoxLayout(button)
    inner.setSpacing(BIG_GAP)
    inner.setAlignment(Qt.AlignmentFlag.AlignCenter)
    found = tinted(stem, colour='#ffffff', size=BIG_ICON)
    if found is not None:
        picture = QLabel()
        picture.setPixmap(found.pixmap(QSize(BIG_ICON, BIG_ICON)))
        picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(picture)
    label = heading(text)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    inner.addWidget(label)
    # clicks fall through to the button
    for child in button.findChildren(QLabel):
        child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    return button

# white: a bundled icon redrawn in the action colour, or None when its file is not there
def white(stem: str, size: int = 16) -> QIcon | None:
    return tinted(stem, colour=ICON_COLOUR, size=size)

# icon_button: an icon-only white button with a tooltip, or a text button when the icon file is missing; size makes it a rounded square of that icon edge plus padding
def icon_button(stem: str, text: str, tip: str, *, size: int | None = None) -> QPushButton:
    found = white(stem, size or 16)
    button = QPushButton() if found is not None else QPushButton(text)
    if found is not None:
        button.setIcon(found)
    if size is not None:
        button.setIconSize(QSize(size, size))
        button.setFixedSize(size + MEDIUM_PAD, size + MEDIUM_PAD)
        rounded(button)
    button.setToolTip(tip)
    return button

# image_well: a fixed square frame for an image, dark with its placeholder text centred
def image_well(label: QLabel, size: int) -> None:
    label.setFixedSize(size, size)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet(f'background: {WELL_BG}; color: {WELL_TEXT}')

# pad_cells: the quiet table look, with padded cells and headings, no heading borders and left-aligned heading text
def pad_cells(table: QTableWidget) -> None:
    table.setStyleSheet(f'QTableWidget::item {{ padding: 0 {CELL_PADDING}px; }} QHeaderView::section {{ padding: 4px {CELL_PADDING}px; border: none; text-align: left; }}')

# quiet_table: the Project > Tomograms look for any table: no grid, no row numbers, whole-row selection, padded cells, left-aligned headings
def quiet_table(table: QTableWidget, *, editable: bool = False) -> None:
    table.verticalHeader().hide()
    table.setShowGrid(False)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers if editable else QAbstractItemView.EditTrigger.NoEditTriggers)
    table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    pad_cells(table)

# transparent_scroll: a scroll area that shows what is behind it instead of painting the window colour; call after setWidget
def transparent_scroll(scroll: QScrollArea) -> None:
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.viewport().setAutoFillBackground(False)
    scroll.widget().setAutoFillBackground(False)

# _styled: a label in the application font shifted by step points
def _styled(text: str, step: float, *, bold: bool) -> QLabel:
    label = QLabel(text)
    font = label.font()
    font.setPointSizeF(font.pointSizeF() + step)
    font.setBold(bold)
    label.setFont(font)
    return label

# _view_look: the eye icon for a toggle's state, or the word hidden after the name without the icon files
def _view_look(button: QToolButton, name: str, shown: bool) -> None:
    eye = icon('visibility' if shown else 'visibility_off')
    if eye is None:
        button.setText(name if shown else f'{name} (hidden)')
    else:
        button.setIcon(eye)
