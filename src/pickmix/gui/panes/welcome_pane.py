'''
pickmix: welcome pane shown when no project is open
'''

# Import external dependencies
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QHideEvent, QIcon, QKeySequence, QResizeEvent, QShortcut, QShowEvent
from PySide6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

# Import internal pickmix objects
from pickmix import __version__
from pickmix.gui.components.icons import icon
from pickmix.gui.style import big_button, hint, tidy

# _CORNER: gap in pixels between the theme button and the window corner
_CORNER: int = 10

# _ICON: edge in pixels of the theme button's icon
_ICON: int = 28

# WelcomePane: Open project and New project side by side, centred, with the version at the bottom
class WelcomePane(QWidget):
    # theme_toggled: the user asked for the other colour theme
    theme_toggled = Signal()

    # __init__: build the buttons and the shortcuts
    def __init__(self) -> None:
        super().__init__()
        self.open_button = big_button('Open project', 'folder_open')
        self.new_button = big_button('New project', 'create_new_folder')
        self.version = hint(f'pickmix v{__version__}')
        self.theme_button = QPushButton(self)
        self.theme_button.setIconSize(QSize(_ICON, _ICON))
        self.theme_button.setStyleSheet('QPushButton { border: none; background: transparent; }')
        self.theme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_theme_button()
        self.theme_button.clicked.connect(self.theme_toggled)
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

    # update_theme_button: theme button offers the other theme, light_mode while dark and dark_mode while light
    def update_theme_button(self) -> None:
        to_light = QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        stem, name = ('light_mode', 'Light mode') if to_light else ('dark_mode', 'Dark mode')
        found = icon(stem)
        self.theme_button.setText(name if found is None else '')
        self.theme_button.setIcon(found or QIcon())
        self.theme_button.setToolTip(f'Switch to {name.lower()}')
        self.theme_button.adjustSize()

    # showEvent: put theme theme button in the window's corner
    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._place()

    # hideEvent: theme button belongs to the window, so hide it with this page
    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        self.theme_button.hide()

    # resizeEvent: keep the theme button in the corner
    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._place()

    # _place: place theme button relative to window
    def _place(self) -> None:
        top = self.window()
        if self.theme_button.parent() is not top:
            self.theme_button.setParent(top)
        self.theme_button.adjustSize()
        self.theme_button.move(top.width() - self.theme_button.width() - _CORNER, _CORNER)
        self.theme_button.raise_()
        self.theme_button.show()
