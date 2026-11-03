'''
pickmix: application start-up for GUI
'''

# Import external dependencies
from pathlib import Path
from PySide6.QtWidgets import QApplication

# Import internal pickmix objects
from pickmix.gui.main_window import MainWindow
from pickmix.gui.style import standardise

# run: show the main window, opening the config.toml in args if one is given, and return the exit code
def run(args: list[str]) -> int:
    app = QApplication.instance() or QApplication(['pickmix'])
    standardise(app)
    window = MainWindow()
    window.show()
    if args:
        window.open_config(Path(args[0]))
    return app.exec()
