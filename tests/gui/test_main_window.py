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
        assert window.kinds_tab.table.item(0, 0).text() == 'cage'

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