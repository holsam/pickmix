'''
pickmix: main GUI window
'''

# Import external dependencies
from pathlib import Path
from PySide6.QtWidgets import QLabel, QMainWindow, QTabWidget

# Import internal pickmix objects
from pickmix.gui.project_tab import ProjectTab
from pickmix.project import Project

# MainWindow: tabs in workflow order; everything after Project waits for an open project
class MainWindow(QMainWindow):
    # __init__: build the tabs
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle('pickmix')
        self.resize(1400, 900)
        self.project: Project | None = None
        self.tabs = QTabWidget()
        self.project_tab = ProjectTab()
        self.tabs.addTab(self.project_tab, 'Project')
        for title in ('Kinds', 'Pick', 'Review'):
            i = self.tabs.addTab(QLabel(f'{title}: not built yet'), title)
            self.tabs.setTabEnabled(i, False)
        self.setCentralWidget(self.tabs)
        self.project_tab.project_changed.connect(self._on_project)

    # open_config: open a config.toml in the Project tab
    def open_config(self, path: Path) -> None:
        self.project_tab.open_config(path)

    # _on_project: remember the project and unlock the other tabs
    def _on_project(self, project: Project) -> None:
        self.project = project
        self.setWindowTitle(f'pickmix: {project.path}')
        for i in range(1, self.tabs.count()):
            self.tabs.setTabEnabled(i, True)
