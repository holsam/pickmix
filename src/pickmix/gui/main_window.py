'''
pickmix: main GUI window
'''

# Import external dependencies
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QDockWidget, QLabel, QLineEdit, QMainWindow, QTabWidget

# Import internal pickmix objects
from pickmix.gui.kinds_tab import KindsTab
from pickmix.gui.pick_tab import PickTab
from pickmix.gui.project_tab import ProjectTab
from pickmix.gui.tomo_dock import TomoDock
from pickmix.loader import Loader
from pickmix.model import Session
from pickmix.project import Project

# MainWindow: tabs in workflow order; everything after Project waits for an open project
class MainWindow(QMainWindow):
    # __init__: build the tabs and dock
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle('pickmix')
        self.resize(1400, 900)
        self.project: Project | None = None
        self.session: Session | None = None
        self.loader: Loader | None = None
        self.tabs = QTabWidget()
        self.project_tab = ProjectTab()
        self.kinds_tab = KindsTab()
        self.pick_tab = PickTab()
        self.dock = TomoDock()
        self.tabs.addTab(self.project_tab, 'Project')
        self.tabs.addTab(self.kinds_tab, 'Kinds')
        self.tabs.addTab(self.pick_tab, 'Pick')
        self.tabs.addTab(QLabel('Review: not built yet'), 'Review')
        for i in range(1, self.tabs.count()):
            self.tabs.setTabEnabled(i, False)
        self.setCentralWidget(self.tabs)
        dock = QDockWidget('Tomograms')
        dock.setWidget(self.dock)
        dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        self.project_tab.project_changed.connect(self._on_project)
        self.project_tab.config_saved.connect(self._on_settings)
        self.kinds_tab.config_saved.connect(self._on_kinds)
        for keys, delta in (('Return', 1), ('Enter', 1), ('Shift+Return', -1), ('Shift+Enter', -1)):
            shortcut = QShortcut(QKeySequence(keys), self, context=Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(lambda delta=delta: self._step(delta))

    # open_config: open a config.toml in the Project tab
    def open_config(self, path: Path) -> None:
        self.project_tab.open_config(path)

    # _step: Enter and Shift+Enter move between tomograms on the Pick tab, unless a text box has focus
    def _step(self, delta: int) -> None:
        if self.session is None or self.tabs.currentWidget() is not self.pick_tab:
            return
        if isinstance(QApplication.focusWidget(), QLineEdit):
            return
        self.session.step(delta)

    # _on_project: remember the project, refresh tabs that show it and unlock them
    def _on_project(self, project: Project) -> None:
        self.project = project
        self.setWindowTitle(f'pickmix: {project.path}')
        if self.loader is not None:
            self.loader.shutdown()
        self.kinds_tab.set_project(project)
        if project.tomos:
            self.session, self.loader = Session(project), Loader(project)
            self.pick_tab.set_session(self.session, self.loader)
            self.dock.set_session(self.session)
        else:
            self.session = self.loader = None
        for i in range(1, self.tabs.count()):
            self.tabs.setTabEnabled(i, True)
        self.tabs.setTabEnabled(2, self.session is not None)

    # _on_settings: source or estimator settings changed, so start the session and loader afresh
    def _on_settings(self) -> None:
        if self.project is not None:
            self._on_project(self.project)

    # _on_kinds: kinds changed; redraw what depends on them
    def _on_kinds(self) -> None:
        self.pick_tab.refresh_kinds()
        self.dock.refresh()
