'''
pickmix: welcome pane shown when no project is open
'''

# Import external dependencies
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

# Import internal pickmix objects
from pickmix import __version__
from pickmix.gui.style import big_button, hint, tidy

# WelcomePane: Open project and New project side by side, centred, with the version at the bottom
class WelcomePane(QWidget):
    # __init__: build the buttons and the shortcuts
    def __init__(self) -> None:
        super().__init__()
        self.open_button = big_button('Open project', 'folder_open')
        self.new_button = big_button('New project', 'create_new_folder')
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
