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
