'''
pickmix: 'Project' tab for creating/opening projects and showing tomograms, kinds and settings
'''

# Import external dependencies
from collections.abc import Callable
from pathlib import Path
from typing import Literal
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget

# Import internal pickmix objects
from pickmix.gui.dialogs.new_project_dialog import NewProjectDialog
from pickmix.gui.panes.kinds_pane import KindsPane
from pickmix.gui.panes.loading_pane import LoadingPane
from pickmix.gui.panes.settings_pane import SettingsPane
from pickmix.gui.panes.tomograms_pane import TomogramsPane
from pickmix.gui.panes.welcome_pane import WelcomePane
from pickmix.gui.style import hint, icon_button, tidy, title, transparent_scroll
from pickmix.gui.workers import post, run_in_background
from pickmix.lock import ProjectBusy, ProjectLock
from pickmix.project import Project, create_project, open_project
from pickmix.utils.star import MergeResult

# ProjectTab: the welcome page when no project is open, else a top bar over tomograms, kinds and settings
class ProjectTab(QWidget):
    # project_changed: a project was opened or created
    project_changed = Signal(object)
    # config_saved: settings of the open project were written to config.toml
    config_saved = Signal()
    # project_closed: the open project was closed
    project_closed = Signal()
    # kinds_saved: the kinds or hotkeys were written to config.toml
    kinds_saved = Signal()

    # __init__: build the layout
    def __init__(self) -> None:
        super().__init__()
        self.project: Project | None = None
        # held while project is open
        self.lock: ProjectLock | None = None
        self.welcome = WelcomePane()
        self.loading = LoadingPane()
        self._before = 0
        self.open_button = self.welcome.open_button
        self.new_button = self.welcome.new_button
        self.reload_button = icon_button('refresh', 'Reload', 'Reload config.toml and rescan the tomograms', size=28)
        self.close_button = icon_button('logout', 'Close', 'Close the project', size=28)
        self.title_label = title()
        self.path_label = hint()
        self.status = QLabel()
        self.tomograms = TomogramsPane()
        self.kinds_pane = KindsPane()
        self.settings_pane = SettingsPane()
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        settings_scroll.setWidget(self.settings_pane)
        transparent_scroll(settings_scroll)
        settings_scroll.setMinimumWidth(self.settings_pane.minimumWidth() + 24)
        # top bar: name and path on the left, reload and close on the right
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(self.title_label)
        names.addWidget(self.path_label)
        top = QHBoxLayout()
        top.addLayout(names, 1)
        top.addWidget(self.reload_button, alignment=Qt.AlignmentFlag.AlignTop)
        top.addWidget(self.close_button, alignment=Qt.AlignmentFlag.AlignTop)
        columns = QHBoxLayout()
        columns.addWidget(self.tomograms, 7)
        columns.addWidget(self.kinds_pane, 2)
        columns.addWidget(settings_scroll, 0)
        opened = QWidget()
        opened_layout = QVBoxLayout(opened)
        opened_layout.setContentsMargins(0, 0, 0, 0)
        opened_layout.addLayout(top)
        opened_layout.addLayout(columns, 1)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.welcome)
        self.stack.addWidget(opened)
        self.stack.addWidget(self.loading)
        layout = QVBoxLayout(self)
        tidy(layout)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.status)
        self.open_button.clicked.connect(self._open_dialog)
        self.new_button.clicked.connect(self._new_dialog)
        self.reload_button.clicked.connect(self._reload)
        self.close_button.clicked.connect(self.close_project)
        self.settings_pane.config_saved.connect(self.config_saved)
        self.settings_pane.hotkeys_saved.connect(self.kinds_saved)
        self.kinds_pane.config_saved.connect(self._kinds_saved)
        self.loading.dismissed.connect(self._dismissed)

    # open_config: open a config.toml in the background
    def open_config(self, path: Path) -> None:
        say = self._busy('open', str(path))
        run_in_background(lambda: open_project(path, say=say), self.set_project, self._failed)

    # set_project: lock then show a project and announce it
    def set_project(self, project: Project) -> None:
        if not self._lock(project):
            return
        self.project = project
        self.title_label.setText(project.display_name)
        self.path_label.setText(str(project.path))
        self.tomograms.set_project(project)
        self.kinds_pane.set_project(project)
        self.settings_pane.set_project(project)
        self.stack.setCurrentIndex(1)
        self._idle('')
        self.project_changed.emit(project)

    # close_project: close the open project and go back to the welcome page
    def close_project(self) -> None:
        self.project = None
        if self.lock is not None:
            self.lock.release()
            self.lock = None
        self.stack.setCurrentIndex(0)
        self.status.setText('')
        self.project_closed.emit()

    # _lock: hold project's lock, keeping one already held when reloading the same project
    def _lock(self, project: Project) -> bool:
        out_dir = project.config.out_dir
        if self.lock is not None and self.lock.path.parent == out_dir:
            return True
        try:
            taken = ProjectLock(out_dir, 'GUI')
        except ProjectBusy as e:
            self._idle('')
            self.loading.fail(str(e))
            self.stack.setCurrentWidget(self.loading)
            return False
        if self.lock is not None:
            self.lock.release()
        self.lock = taken
        return True

    # _kinds_saved: kinds changed, so the hotkey dropdowns list the new ones, then tell the other tabs
    def _kinds_saved(self) -> None:
        self.settings_pane.refresh_hotkeys()
        self.kinds_saved.emit()

    # _open_dialog: choose a config.toml
    def _open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, 'Open config', '', 'TOML (*.toml)')
        if path:
            self.open_config(Path(path))

    # _reload: reopen the current config.toml, picking up hand edits and rescanning tomograms
    def _reload(self) -> None:
        if self.project is not None:
            self.open_config(self.project.path)

    # _new_dialog: collect runs, merge them, write the config and open it
    def _new_dialog(self) -> None:
        dialog = NewProjectDialog(self)
        if not dialog.exec():
            return
        values = dialog.values()
        say = self._busy('create', str(values['project_dir']))
        run_in_background(lambda: _create_and_open(values, say), self._created, self._failed)

    # _created: show the new project and say what the merge did
    def _created(self, made: tuple[Project, MergeResult]) -> None:
        project, result = made
        self.set_project(project)
        self.status.setText(f'Created with {result.count} tomograms, {len(result.skipped)} duplicates skipped')

    # _busy: show the loading page and block the open, create, reload and close buttons while work runs
    def _busy(self, kind: Literal['open', 'create'], path: str) -> Callable[[str], None]:
        if self.stack.currentWidget() is not self.loading:
            self._before = self.stack.currentIndex()
        for button in (self.open_button, self.new_button, self.reload_button, self.close_button):
            button.setEnabled(False)
        self.status.setText('')
        self.loading.begin(kind, path)
        self.stack.setCurrentWidget(self.loading)
        return lambda message: post(lambda: self.loading.step(message))

    # _idle: unblock the buttons
    def _idle(self, message: str) -> None:
        for button in (self.open_button, self.new_button, self.reload_button, self.close_button):
            button.setEnabled(True)
        self.status.setText(message)

    # _failed: unblock buttons and show an error on the loading page, which stays until Back
    def _failed(self, message: str) -> None:
        self._idle('')
        self.loading.fail(message)

    # _dismissed: go back to the page that was showing before loading started
    def _dismissed(self) -> None:
        self.stack.setCurrentIndex(self._before)

# _create_and_open: create the project on disk, then open it
def _create_and_open(values: dict[str, object], say: Callable[[str], None]) -> tuple[Project, MergeResult]:
    say('Merging RELION runs and writing config.toml')
    path, result = create_project(**values)
    return open_project(path, say=say), result
