'''
pickmix: tests for GUI main window
'''

# Import external dependencies
from collections.abc import Callable
from pathlib import Path
from PySide6.QtCore import QAbstractAnimation, QSize, Qt
from PySide6.QtGui import QShortcut
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit
from pytestqt.qtbot import QtBot

# Import internal pickmix objects
from pickmix.config import Kind
from pickmix.gui.main_window import PROJECT_SIZE, WELCOME_SIZE, MainWindow
from pickmix.project import open_project

# TestMainWindow: main window
class TestMainWindow:
    # test_tabs_locked_until_project: only Project is usable at first, all tabs after a project opens
    def test_tabs_locked_until_project(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        window = MainWindow()
        qtbot.addWidget(window)
        assert [window.tabs.isTabEnabled(i) for i in range(4)] == [True, False, False, False]
        window.project_tab.set_project(open_project(make_config()))
        assert all(window.tabs.isTabEnabled(i) for i in range(4))
        assert window.project is not None

    # test_kinds_pane_follows_project: the kinds pane shows the opened project's kinds
    def test_kinds_pane_follows_project(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        window = MainWindow()
        qtbot.addWidget(window)
        window.project_tab.set_project(open_project(make_config()))
        assert window.kinds_pane.kind_names() == ['cage']

    # test_step_only_on_pick_tab: Enter steps tomograms on the Pick tab and nowhere else
    def test_step_only_on_pick_tab(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        window = MainWindow()
        qtbot.addWidget(window)
        window.project_tab.set_project(open_project(make_config(names=('A_1', 'B_2', 'C_3'))))
        window._step(1)
        assert window.session.index == 0
        window.tabs.setCurrentWidget(window.pick_tab)
        window._step(1)
        assert window.session.index == 1
        window._step(-1)
        window._step(-1)
        assert window.session.index == 0
        window.loader.shutdown()

    # test_no_usable_tomograms: a project with nothing usable keeps the Pick tab locked
    def test_no_usable_tomograms(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        window = MainWindow()
        qtbot.addWidget(window)
        window.project_tab.set_project(open_project(make_config(shape=(4, 6, 20))))
        assert window.session is None
        assert window.tabs.isTabEnabled(0) and not any(window.tabs.isTabEnabled(i) for i in (1, 2, 3))
        assert window.kinds_pane.kind_names() == ['cage']


    # test_review_tab_wired: the Review tab is built for an opened project and opening a pick switches tabs
    def test_review_tab_wired(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        window = MainWindow()
        qtbot.addWidget(window)
        window.project_tab.set_project(open_project(make_config()))
        assert window.tabs.isTabEnabled(3) and window.service is not None
        pick = window.session.store.add('Position_1_2', 'cage', 1.0, 1.0, 1.0)
        window._open_pick('Position_1_2', pick.id)
        assert window.tabs.currentWidget() is window.pick_tab
        window.service.shutdown()
        window.loader.shutdown()

    # test_average_pane_wired: the Average pane in the Export tab lists the project's kinds
    def test_average_pane_wired(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        window = MainWindow()
        qtbot.addWidget(window)
        window.project_tab.set_project(open_project(make_config()))
        assert window.export_tab.average.kind_box.count() == 1
        window.service.shutdown()
        window.loader.shutdown()

    # test_close_project: closing re-locks the other tabs and drops the session
    def test_close_project(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        window = MainWindow()
        qtbot.addWidget(window)
        window.project_tab.set_project(open_project(make_config()))
        window.project_tab.close_button.click()
        assert window.project is None and window.session is None
        assert [window.tabs.isTabEnabled(i) for i in range(4)] == [True, False, False, False]

    # test_window_size_follows_page: small on the welcome page, default size once a project opens, a hand size survives a reload, small again on close
    def test_window_size_follows_page(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        window = MainWindow()
        qtbot.addWidget(window)
        window.show()
        size = lambda: (window.width(), window.height())
        assert size() == WELCOME_SIZE
        project = open_project(make_config())
        window.project_tab.set_project(project)
        # the platform may hold the window inside a small screen, so it only has to have grown and settled
        qtbot.waitUntil(lambda: window._resizing.state() == window._resizing.State.Stopped, timeout=3000)
        assert window.width() > WELCOME_SIZE[0] and window.height() > WELCOME_SIZE[1]
        window.resize(1300, 950)
        window.project_tab.set_project(project)
        assert size() == (1300, 950)
        window.project_tab.close_button.click()
        qtbot.waitUntil(lambda: size() == WELCOME_SIZE, timeout=3000)

    # test_resize_keeps_centre_on_screen: the window grows and shrinks about its centre and stays inside its screen
    def test_resize_keeps_centre_on_screen(self, qtbot: QtBot) -> None:
        window = MainWindow()
        qtbot.addWidget(window)
        window.show()
        area = window.screen().availableGeometry()
        frame = window.frameGeometry()
        frame.moveCenter(area.center())
        window.move(frame.topLeft())
        centre = window.frameGeometry().center()
        window._resize_about_centre((520, 300))
        qtbot.waitUntil(lambda: window.width() == 520, timeout=3000)
        assert (window.frameGeometry().center() - centre).manhattanLength() <= 2
        window.move(area.right() - 100, area.bottom() - 100)
        window._resize_about_centre(PROJECT_SIZE)
        qtbot.wait(400)
        assert window.frameGeometry().left() >= area.left() and window.frameGeometry().top() >= area.top()
        assert window.frameGeometry().right() <= area.right() or window.frameGeometry().width() > area.width()

    # test_welcome_has_no_tab_bar: the tab bar only shows while a project is open
    def test_welcome_has_no_tab_bar(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        window = MainWindow()
        qtbot.addWidget(window)
        window.show()
        assert not window.tabs.tabBar().isVisible()
        window.project_tab.set_project(open_project(make_config()))
        assert window.tabs.tabBar().isVisible()
        window.project_tab.close_button.click()
        assert not window.tabs.tabBar().isVisible()

    # test_open_grows_about_centre: opening a project from the welcome page keeps the window's centre, even though the tabs' minimum size is bigger than the welcome page
    def test_open_grows_about_centre(self, qtbot: QtBot, make_config: Callable[..., Path], monkeypatch) -> None:
        monkeypatch.setattr('pickmix.gui.main_window.PROJECT_SIZE', (620, 360))
        window = MainWindow()
        qtbot.addWidget(window)
        window.show()
        window.setMinimumSize(0, 0)
        window.resize(520, 300)
        area = window.screen().availableGeometry()
        frame = window.frameGeometry()
        frame.moveCenter(area.center())
        window.move(frame.topLeft())
        centre = window.frameGeometry().center()
        monkeypatch.setattr(window.tabs, 'minimumSizeHint', lambda: QSize(600, 350))
        window.project_tab.set_project(open_project(make_config()))
        qtbot.waitUntil(lambda: window._resizing.state() == QAbstractAnimation.State.Stopped, timeout=3000)
        assert window.width() >= 620 and (window.frameGeometry().center() - centre).manhattanLength() <= 3
        assert window.minimumSize() == QSize(600, 350)

    # test_resize_is_instant_before_show: a window not yet shown takes its size at once
    def test_resize_is_instant_before_show(self, qtbot: QtBot) -> None:
        window = MainWindow()
        qtbot.addWidget(window)
        window._resize_about_centre((600, 350))
        assert (window.width(), window.height()) == (600, 350)

    # test_no_kinds: a project with every kind deleted still opens, and every tab copes
    def test_no_kinds(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        path = make_config()
        project = open_project(path)
        project.update(kinds={})
        window = MainWindow()
        qtbot.addWidget(window)
        window.project_tab.set_project(open_project(path))
        for tab in (window.pick_tab, window.review_tab, window.export_tab):
            window.tabs.setCurrentWidget(tab)
        assert window.kinds_pane.kind_names() == [] and window.pick_tab.active is None
        window.service.shutdown()
        window.loader.shutdown()

    # test_window_title: the title carries the project name while one is open
    def test_window_title(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        path = make_config()
        project = open_project(path)
        project.update(name='Cages')
        window = MainWindow()
        qtbot.addWidget(window)
        assert window.windowTitle() == 'pickmix'
        window.project_tab.set_project(open_project(path))
        assert window.windowTitle() == 'pickmix • Cages'
        window.project_tab.close_button.click()
        assert window.windowTitle() == 'pickmix'

    # test_settings_restart_is_debounced: a settings change rebuilds the session once after the changes stop
    def test_settings_restart_is_debounced(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        window = MainWindow()
        qtbot.addWidget(window)
        window.project_tab.set_project(open_project(make_config()))
        old = window.session
        window._on_settings()
        window._on_settings()
        assert window.session is old
        qtbot.waitUntil(lambda: window.session is not old, timeout=3000)
        window.service.shutdown()
        window.loader.shutdown()

    # test_pick_keys_are_window_wide: number and delete keys are window shortcuts, so they do not depend on canvas focus
    def test_pick_keys_are_window_wide(self, qtbot: QtBot) -> None:
        window = MainWindow()
        qtbot.addWidget(window)
        keys = {s.key().toString(): s for s in window.findChildren(QShortcut)}
        assert all(str(i) in keys for i in range(1, 10)) and 'Del' in keys and 'Backspace' in keys
        assert all(s.context() == Qt.ShortcutContext.WindowShortcut for s in keys.values())

    # test_hotkey_and_delete_from_other_focus: with focus off the canvas, a hotkey still picks the kind and delete still removes the pick
    def test_hotkey_and_delete_from_other_focus(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        path = make_config()
        project = open_project(path)
        project.update(kinds={'cage': Kind(marker_a=600, box_a=700), 'yellow': Kind(marker_a=100, box_a=100)})
        window = MainWindow()
        qtbot.addWidget(window)
        window.project_tab.set_project(open_project(path))
        window.tabs.setCurrentWidget(window.pick_tab)
        qtbot.waitUntil(lambda: window.pick_tab.canvas.has_image, timeout=5000)
        window.tabs.tabBar().setFocus()
        window._hotkey(1)
        assert window.pick_tab.active == 'yellow'
        window.pick_tab.canvas.add_requested.emit(3.0, 2.0)
        window._delete_pick()
        assert window.session.store.total() == 0
        window.service.shutdown()
        window.loader.shutdown()

    # test_pick_keys_ignored_elsewhere: not on another tab and not while typing in a text box
    def test_pick_keys_ignored_elsewhere(self, qtbot: QtBot, make_config: Callable[..., Path], monkeypatch) -> None:
        path = make_config()
        project = open_project(path)
        project.update(kinds={'cage': Kind(marker_a=600, box_a=700), 'yellow': Kind(marker_a=100, box_a=100)})
        window = MainWindow()
        qtbot.addWidget(window)
        window.project_tab.set_project(open_project(path))
        qtbot.waitUntil(lambda: window.pick_tab.canvas.has_image, timeout=5000)
        window._hotkey(1)
        assert window.pick_tab.active == 'cage'
        window.tabs.setCurrentWidget(window.pick_tab)
        monkeypatch.setattr(QApplication, 'focusWidget', staticmethod(lambda: QLineEdit()))
        window._hotkey(1)
        assert window.pick_tab.active == 'cage'
        window.service.shutdown()
        window.loader.shutdown()

    # test_return_steps_from_the_window: Enter and Shift+Enter reaching the window step tomograms on the Pick tab
    def test_return_steps_from_the_window(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        window = MainWindow()
        qtbot.addWidget(window)
        window.project_tab.set_project(open_project(make_config(names=('A_1', 'B_2', 'C_3'))))
        window.tabs.setCurrentWidget(window.pick_tab)
        QTest.keyClick(window, Qt.Key.Key_Return)
        assert window.session.index == 1
        QTest.keyClick(window, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
        assert window.session.index == 0
        window.loader.shutdown()
