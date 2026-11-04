'''
pickmix: main GUI window
'''

# Import external dependencies
from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeyEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QDockWidget, QLineEdit, QMainWindow, QTabWidget

# Import internal pickmix objects
from pickmix.estimates import EstimateService
from pickmix.gui.components.toast import install
from pickmix.gui.panes.tomo_pane import TomoPane
from pickmix.gui.tabs.export_tab import ExportTab
from pickmix.gui.tabs.pick_tab import PickTab
from pickmix.gui.tabs.project_tab import ProjectTab
from pickmix.gui.tabs.review_tab import ReviewTab
from pickmix.loader import Loader
from pickmix.model import Session
from pickmix.project import Project

# MainWindow: tabs in workflow order; everything after Project waits for usable tomograms
class MainWindow(QMainWindow):
    # __init__: build the tabs and dock
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle('pickmix')
        self.resize(1400, 900)
        self.project: Project | None = None
        self.session: Session | None = None
        self.loader: Loader | None = None
        self.service: EstimateService | None = None
        self.tabs = QTabWidget()
        self.project_tab = ProjectTab()
        self.kinds_pane = self.project_tab.kinds_pane
        self.pick_tab = PickTab()
        self.review_tab = ReviewTab()
        self.export_tab = ExportTab()
        self.dock = TomoPane()
        self.tabs.addTab(self.project_tab, 'Project')
        self.tabs.addTab(self.pick_tab, 'Pick')
        self.tabs.addTab(self.review_tab, 'Review')
        self.tabs.addTab(self.export_tab, 'Export')
        self._set_enabled(session=False)
        self.setCentralWidget(self.tabs)
        self.dock_widget = QDockWidget('Tomograms')
        self.dock_widget.setWidget(self.dock)
        self.dock_widget.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.dock_widget.hide()
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.dock_widget)
        self._restart = QTimer(self)
        self._restart.setSingleShot(True)
        self._restart.setInterval(500)
        self._restart.timeout.connect(self._restart_session)
        self.tabs.currentChanged.connect(self._sync_dock)
        self.project_tab.project_changed.connect(self._on_project)
        self.project_tab.config_saved.connect(self._on_settings)
        self.project_tab.project_closed.connect(self._on_closed)
        self.project_tab.kinds_saved.connect(self._on_kinds)
        self.review_tab.open_pick.connect(self._open_pick)
        self.toast = install(self)
        for i in range(1, 10):
            QShortcut(QKeySequence(str(i)), self, context=Qt.ShortcutContext.WindowShortcut).activated.connect(lambda i=i: self._hotkey(i - 1))
        for key in ('Delete', 'Backspace'):
            QShortcut(QKeySequence(key), self, context=Qt.ShortcutContext.WindowShortcut).activated.connect(self._delete_pick)

    # keyPressEvent: Enter steps to the next tomogram and Shift+Enter to the previous. A text box handles Return first and ignores it, so a key reaching here was wanted by nothing else
    def keyPressEvent(self, event: QKeyEvent) -> None:
        mods = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and mods in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier):
            self._step(-1 if mods == Qt.KeyboardModifier.ShiftModifier else 1)
            event.accept()
            return
        super().keyPressEvent(event)

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

    # _picking: whether Pick tab keys apply: a session, the Pick tab showing and no text box (a spin box counts as one) being typed into
    def _picking(self) -> bool:
        return (self.session is not None and self.tabs.currentWidget() is self.pick_tab and not isinstance(QApplication.focusWidget(), QLineEdit))

    # _hotkey: the number key for the i-th kind, from wherever focus is
    def _hotkey(self, i: int) -> None:
        if self._picking():
            self.pick_tab.pick_kind(i)

    # _delete_pick: Delete or Backspace removes the selected pick, from wherever focus is
    def _delete_pick(self) -> None:
        if self._picking():
            self.pick_tab.delete_selected()

    # _sync_dock: the tomogram dock is only for the Pick tab, and only with a session
    def _sync_dock(self) -> None:
        self.dock_widget.setVisible(self.session is not None and self.tabs.currentWidget() is self.pick_tab)

    # _set_enabled: Project is always usable; Pick, Review and Export need a session
    def _set_enabled(self, *, session: bool) -> None:
        for tab in (self.pick_tab, self.review_tab, self.export_tab):
            self.tabs.setTabEnabled(self.tabs.indexOf(tab), session)

    # _on_project: build the session and loader for a project and unlock the tabs
    def _on_project(self, project: Project) -> None:
        self.project = project
        self.setWindowTitle(f'pickmix • {project.display_name}')
        self._shutdown()
        if project.tomos:
            self.session, self.loader = Session(project), Loader(project)
            self.service = EstimateService(self.session, self.loader)
            self.pick_tab.set_session(self.session, self.loader, self.service)
            self.review_tab.set_session(self.session, self.loader, self.service)
            self.export_tab.set_session(self.session, self.loader, self.service)
            self.dock.set_session(self.session)
            self.kinds_pane.set_session(self.session, self.service)
        else:
            self.session = self.loader = self.service = None
            self.kinds_pane.set_session(None, None)
            self.export_tab.clear()
        self._set_enabled(session=self.session is not None)
        self._sync_dock()

    # _shutdown: stop the estimate service and loader of the current project, if any
    def _shutdown(self) -> None:
        if self.service is not None:
            self.service.shutdown()
        if self.loader is not None:
            self.loader.shutdown()
        self.session = self.loader = self.service = None

    # _on_closed: no project; lock everything but the Project tab
    def _on_closed(self) -> None:
        self._restart.stop()
        self._shutdown()
        self.project = None
        self.setWindowTitle('pickmix')
        self.kinds_pane.set_session(None, None)
        self.export_tab.clear()
        self._set_enabled(session=False)
        self.tabs.setCurrentWidget(self.project_tab)
        self._sync_dock()

    # _on_settings: source or estimator settings changed; rebuild once the changes stop, as they save on every edit
    def _on_settings(self) -> None:
        self._restart.start()

    # _restart_session: start the session, loader and estimators afresh with the saved settings
    def _restart_session(self) -> None:
        if self.project is not None:
            self._on_project(self.project)

    # _on_kinds: kinds changed; redraw what depends on them
    def _on_kinds(self) -> None:
        self.pick_tab.refresh_kinds()
        self.review_tab.refresh_kinds()
        self.export_tab.refresh_kinds()
        self.dock.refresh()

    # _open_pick: show a pick from the Review tab in the Pick tab
    def _open_pick(self, _tomogram: str, pick_id: int) -> None:
        self.tabs.setCurrentWidget(self.pick_tab)
        self.pick_tab.show_pick(pick_id)
