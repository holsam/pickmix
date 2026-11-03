'''
pickmix: tests for GUI main window
'''

# Import external dependencies
from collections.abc import Callable
from pathlib import Path
from pytestqt.qtbot import QtBot

# Import internal pickmix objects
from pickmix.gui.main_window import MainWindow
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

    # test_kinds_tab_follows_project: the Kinds tab shows the opened project's kinds
    def test_kinds_tab_follows_project(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        window = MainWindow()
        qtbot.addWidget(window)
        window.project_tab.set_project(open_project(make_config()))
        assert window.kinds_tab.kind_names() == ['cage']

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
        assert window.tabs.isTabEnabled(1) and not window.tabs.isTabEnabled(2)

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

    # test_average_pane_wired: the Average pane in the Kinds tab lists the project's kinds
    def test_average_pane_wired(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        window = MainWindow()
        qtbot.addWidget(window)
        window.project_tab.set_project(open_project(make_config()))
        assert window.kinds_tab.average.kind_box.count() == 1
        window.service.shutdown()
        window.loader.shutdown()

    # test_dock_only_on_pick_tab: the tomogram dock follows the Pick tab
    def test_dock_only_on_pick_tab(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        window = MainWindow()
        qtbot.addWidget(window)
        assert window.dock_widget.isHidden()
        window.project_tab.set_project(open_project(make_config()))
        assert window.dock_widget.isHidden()
        window.tabs.setCurrentWidget(window.pick_tab)
        assert not window.dock_widget.isHidden()
        window.tabs.setCurrentWidget(window.review_tab)
        assert window.dock_widget.isHidden()
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

    # test_no_kinds: a project with every kind deleted still opens, and every tab copes
    def test_no_kinds(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        path = make_config()
        project = open_project(path)
        project.update(kinds={})
        window = MainWindow()
        qtbot.addWidget(window)
        window.project_tab.set_project(open_project(path))
        for tab in (window.pick_tab, window.review_tab, window.kinds_tab):
            window.tabs.setCurrentWidget(tab)
        assert window.kinds_tab.kind_names() == [] and window.pick_tab.active is None
        window.service.shutdown()
        window.loader.shutdown()
