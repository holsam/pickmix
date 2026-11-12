'''
pickmix: application start-up for GUI
'''

# Import external dependencies
from pathlib import Path
from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtWidgets import QApplication, QWidget

# Import internal pickmix objects
from pickmix.gui.main_window import MainWindow
from pickmix.gui.style import retint, standardise

# _set_scheme: apply saved colour theme
def _set_scheme(app: QApplication) -> None:
    saved = QSettings('pickmix', 'pickmix').value('theme', '')
    if saved in ('light', 'dark'):
        app.styleHints().setColorScheme(Qt.ColorScheme.Light if saved == 'light' else Qt.ColorScheme.Dark)

# _toggle_theme: save theme and apply it
def _toggle_theme(app: QApplication) -> None:
    dark = app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    QSettings('pickmix', 'pickmix').setValue('theme', 'light' if dark else 'dark')
    _set_scheme(app)

# _restyle: redraw tinted icons in new theme colour
def _restyle(app: QApplication, window: MainWindow) -> None:
    def apply() -> None:
        app.setPalette(app.style().standardPalette())
        for top in app.topLevelWidgets():
            for widget in (top, *top.findChildren(QWidget)):
                app.style().unpolish(widget)
                app.style().polish(widget)
                widget.update()
            retint(top)
        window.project_tab.welcome.update_theme_button()
    QTimer.singleShot(1, apply)

# run: show the main window, opening the config.toml in args if one is given, and return the exit code
def run(args: list[str]) -> int:
    app = QApplication.instance() or QApplication(['pickmix'])
    _set_scheme(app)
    standardise(app)
    window = MainWindow()
    window.project_tab.welcome.theme_toggled.connect(lambda: _toggle_theme(app))
    app.styleHints().colorSchemeChanged.connect(lambda _: _restyle(app, window))
    window.show()
    if args:
        window.open_config(Path(args[0]))
    return app.exec()
