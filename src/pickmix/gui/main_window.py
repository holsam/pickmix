'''
pickmix: main GUI window
'''

# Import external dependencies
from pathlib import Path
from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QPropertyAnimation, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QKeyEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QLineEdit, QLayout, QMainWindow, QTabWidget

# Import internal pickmix objects
from pickmix.estimates import EstimateService
from pickmix.gui.components.toast import install
from pickmix.gui.tabs.export_tab import ExportTab
from pickmix.gui.tabs.pick_tab import PickTab
from pickmix.gui.tabs.project_tab import ProjectTab
from pickmix.gui.tabs.review_tab import ReviewTab
from pickmix.loader import Loader
from pickmix.matcher import MatchService
from pickmix.model import Session
from pickmix.project import Project

# WELCOME_SIZE, PROJECT_SIZE: window size in pixels on the welcome page and once a project is open
WELCOME_SIZE: tuple[int, int] = (500, 280)
PROJECT_SIZE: tuple[int, int] = (1440, 880)

# RESIZE_MS: milliseconds the window takes to change size
RESIZE_MS: int = 220

# WELCOME_MIN: smallest the window may be dragged to on the welcome page
WELCOME_MIN: tuple[int, int] = (500, 280)

# MainWindow: tabs in workflow order; everything after Project waits for usable tomograms
class MainWindow(QMainWindow):
    # __init__: build the tabs
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle('pickmix')
        self.project: Project | None = None
        self.session: Session | None = None
        self.loader: Loader | None = None
        self.service: EstimateService | None = None
        self.matcher: MatchService | None = None
        self.tabs = QTabWidget()
        self.project_tab = ProjectTab()
        self.kinds_pane = self.project_tab.kinds_pane
        self.pick_tab = PickTab()
        self.review_tab = ReviewTab()
        self.export_tab = ExportTab()
        self.tabs.addTab(self.project_tab, 'Project')
        self.tabs.addTab(self.pick_tab, 'Pick')
        self.tabs.addTab(self.review_tab, 'Review')
        self.tabs.addTab(self.export_tab, 'Export')
        self._set_enabled(session=False)
        self.setCentralWidget(self.tabs)
        # the window's smallest size is set by hand (see _fit_welcome), not taken from the pages, which are all larger than the welcome page
        self.layout().setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._fit_welcome(True)
        self._resizing = QPropertyAnimation(self, b'geometry', self)
        self._resizing.setDuration(RESIZE_MS)
        self._resizing.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._resizing.finished.connect(self._apply_minimum)
        self._restart = QTimer(self)
        self._restart.setSingleShot(True)
        self._restart.setInterval(500)
        self._restart.timeout.connect(self._restart_session)
        self.project_tab.project_changed.connect(self._on_project)
        self.project_tab.config_saved.connect(self._on_settings)
        self.project_tab.project_closed.connect(self._on_closed)
        self.project_tab.kinds_saved.connect(self._on_kinds)
        self.review_tab.open_pick.connect(self._open_pick)
        self.toast = install(self)
        for i in range(1, 10):
            QShortcut(QKeySequence(str(i)), self, context=Qt.ShortcutContext.WindowShortcut).activated.connect(lambda i=i: self._hotkey(i - 1))
        QShortcut(QKeySequence('A'), self, context=Qt.ShortcutContext.WindowShortcut).activated.connect(self._accept_candidate)
        for key in ('Delete', 'Backspace'):
            QShortcut(QKeySequence(key), self, context=Qt.ShortcutContext.WindowShortcut).activated.connect(self._delete_pick)
        self.resize(*WELCOME_SIZE)

    # open_config: open a config.toml in the Project tab
    def open_config(self, path: Path) -> None:
        self.project_tab.open_config(path)

    # keyPressEvent: Enter steps to the next tomogram and Shift+Enter to the previous. A text box handles Return first and ignores it, so a key reaching here was wanted by nothing else
    def keyPressEvent(self, event: QKeyEvent) -> None:
        mods = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and mods in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier):
            self._step(-1 if mods == Qt.KeyboardModifier.ShiftModifier else 1)
            event.accept()
            return
        super().keyPressEvent(event)

    # _step: move between tomograms on the Pick tab, unless a text box has focus
    def _step(self, delta: int) -> None:
        if self.session is None or self.tabs.currentWidget() is not self.pick_tab:
            return
        if isinstance(QApplication.focusWidget(), QLineEdit):
            return
        self.session.step(delta)

    # _picking: whether Pick tab keys apply: a session, the Pick tab showing and no text box (a spin box counts as one) being typed into
    def _picking(self) -> bool:
        return (
            self.session is not None and self.tabs.currentWidget() is self.pick_tab
            and not isinstance(QApplication.focusWidget(), QLineEdit)
        )

    # _hotkey: the number key for the i-th kind, from wherever focus is
    def _hotkey(self, i: int) -> None:
        if self._picking():
            self.pick_tab.pick_kind(i)

    # _accept_candidate: A converts selected candidate to pick
    def _accept_candidate(self) -> None:
        if self._picking():
            self.pick_tab.accept_selected()

    # _delete_pick: Delete or Backspace removes the selected pick, from wherever focus is
    def _delete_pick(self) -> None:
        if self._picking():
            self.pick_tab.delete_selected()

    # _resize_about_centre: glide to a new size keeping the window's centre where it is, nudged back onto its screen; no glide before the window is shown
    def _resize_about_centre(self, size: tuple[int, int]) -> None:
        self._resizing.stop()
        frame, inner = self.frameGeometry(), self.geometry()
        # the frame is the window plus its title bar and borders
        wide, high = frame.width() - inner.width(), frame.height() - inner.height()
        target = QRect(frame.topLeft(), QSize(size[0] + wide, size[1] + high))
        target.moveCenter(frame.center())
        area = self.screen().availableGeometry()
        # keep the whole frame on screen (top-left wins if the frame is bigger than the screen)
        x = max(area.left(), min(target.left(), area.right() - target.width() + 1))
        y = max(area.top(), min(target.top(), area.bottom() - target.height() + 1))
        end = QRect(x + inner.left() - frame.left(), y + inner.top() - frame.top(), size[0], size[1])
        if not self.isVisible():
            self.setGeometry(end)
            return
        self._resizing.setStartValue(inner)
        self._resizing.setEndValue(end)
        self._resizing.start()

    # _fit_welcome: the welcome page has no tab bar and may be small; with a project open the tabs show and set the smallest size. Lowering the minimum is applied now, raising it waits for _apply_minimum
    def _fit_welcome(self, welcome: bool) -> None:
        self.tabs.tabBar().setVisible(not welcome)
        self._minimum = QSize(*WELCOME_MIN) if welcome else self.tabs.minimumSizeHint()
        if welcome:
            self.setMinimumSize(self._minimum)

    # _apply_minimum: set the window's smallest size once any resize has finished; raising it earlier would snap the window to it from its top-left corner and lose the centre
    def _apply_minimum(self) -> None:
        self.setMinimumSize(self._minimum)

    # _set_enabled: Project is always usable; Pick, Review and Export need a session
    def _set_enabled(self, *, session: bool) -> None:
        for tab in (self.pick_tab, self.review_tab, self.export_tab):
            self.tabs.setTabEnabled(self.tabs.indexOf(tab), session)

    # _on_project: build the session and loader for a project and unlock the tabs
    def _on_project(self, project: Project) -> None:
        # only the first project after the welcome page resizes; reloads and settings restarts keep the user's size
        if self.project is None:
            self._fit_welcome(False)
            self._resize_about_centre((max(PROJECT_SIZE[0], self._minimum.width()), max(PROJECT_SIZE[1], self._minimum.height())))
            if self._resizing.state() != QAbstractAnimation.State.Running:
                self._apply_minimum()
        self.project = project
        self.setWindowTitle(f'pickmix • {project.display_name}')
        self._shutdown()
        if project.tomos:
            self.session, self.loader = Session(project), Loader(project)
            self.service = EstimateService(self.session, self.loader)
            self.matcher = MatchService(self.session, self.service.store)
            self.pick_tab.set_session(self.session, self.loader, self.service, self.matcher)
            self.review_tab.set_session(self.session, self.loader, self.service)
            self.export_tab.set_session(self.session, self.loader, self.service)
            self.kinds_pane.set_session(self.session, self.service)
        else:
            self.session = self.loader = self.service = self.matcher = None
            self.kinds_pane.set_session(None, None)
            self.export_tab.clear()
        self._set_enabled(session=self.session is not None)

    # _shutdown: stop the estimate service and loader of the current project, if any
    def _shutdown(self) -> None:
        if self.service is not None:
            self.service.shutdown()
        if self.matcher is not None:
            self.matcher.shutdown()
        if self.loader is not None:
            self.loader.shutdown()
        self.session = self.loader = self.service = self.matcher = None

    # _on_closed: no project; lock everything but the Project tab
    def _on_closed(self) -> None:
        self._restart.stop()
        self._shutdown()
        self.project = None
        self.setWindowTitle('pickmix')
        self._fit_welcome(True)
        self._resize_about_centre(WELCOME_SIZE)
        self.kinds_pane.set_session(None, None)
        self.export_tab.clear()
        self._set_enabled(session=False)
        self.tabs.setCurrentWidget(self.project_tab)

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

    # _open_pick: show a pick from the Review tab in the Pick tab
    def _open_pick(self, _tomogram: str, pick_id: int) -> None:
        self.tabs.setCurrentWidget(self.pick_tab)
        self.pick_tab.show_pick(pick_id)
