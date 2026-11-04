'''
pickmix: welcome pane shown when no project is open
'''

# Import external dependencies
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

# Import internal pickmix objects
from pickmix import __version__
from pickmix.gui.components.icons import tinted
from pickmix.gui.style import heading, hint, rounded, tidy

# _ICON: edge in pixels of the icons on the big buttons
_ICON: int = 48

# _GAP: pixels between the icon and the text on the big buttons
_GAP: int = 8

# WelcomePane: Open project and New project side by side, centred, with the version at the bottom
class WelcomePane(QWidget):
    # __init__: build the buttons and the shortcuts
    def __init__(self) -> None:
        super().__init__()
        self.open_button = _big_button('Open project', 'folder_open')
        self.new_button = _big_button('New project', 'create_new_folder')
        self.version = hint(f'pickmix v{__version__}')
        row = QHBoxLayout()
        row.setSpacing(48)
        row.addStretch()
        row.addWidget(self.open_button)
        row.addWidget(self.new_button)
        row.addStretch()
        layout = QVBoxLayout(self)
        tidy(layout)
        layout.addStretch()
        layout.addLayout(row)
        layout.addStretch()
        layout.addWidget(self.version, alignment=Qt.AlignmentFlag.AlignHCenter)
        # click() so a button disabled while a project loads ignores its shortcut; window-wide, but only live while this pane is visible
        for keys, button in (('Ctrl+O', self.open_button), ('Ctrl+N', self.new_button)):
            QShortcut(QKeySequence(keys), self, context=Qt.ShortcutContext.WindowShortcut).activated.connect(button.click)
        self.open_button.setToolTip('Open an existing project (Ctrl+O)')
        self.new_button.setToolTip('Create a project from RELION runs (Ctrl+N)')

# _big_button: icon over text with a fixed gap when the icon file exists, text alone otherwise
def _big_button(text: str, stem: str) -> QPushButton:
    button = QPushButton()
    button.setMinimumSize(200, 150)
    rounded(button)
    inner = QVBoxLayout(button)
    inner.setSpacing(_GAP)
    inner.setAlignment(Qt.AlignmentFlag.AlignCenter)
    found = tinted(stem, colour='#ffffff', size=_ICON)
    if found is not None:
        icon = QLabel()
        icon.setPixmap(found.pixmap(QSize(_ICON, _ICON)))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(icon)
    label = heading(text)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    inner.addWidget(label)
    # clicks fall through to the button
    for child in button.findChildren(QLabel):
        child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    return button
