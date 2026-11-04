'''
pickmix: a directory chooser made of a line edit and a browse button
'''

# Import external dependencies
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLineEdit, QPushButton, QWidget

# PathField: a line edit with a browse button for a directory
class PathField(QWidget):
    # __init__: build the field
    def __init__(self) -> None:
        super().__init__()
        self.edit = QLineEdit()
        button = QPushButton('Browse...')
        button.clicked.connect(self._browse)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.edit)
        layout.addWidget(button)

    # text: the entered path, stripped
    def text(self) -> str:
        return self.edit.text().strip()

    # _browse: pick a directory
    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, 'Choose directory', self.text())
        if chosen:
            self.edit.setText(chosen)
