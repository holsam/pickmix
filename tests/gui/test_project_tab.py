'''
pickmix: tests for the Project tab
'''

# Import external dependencies
from collections.abc import Callable
from pathlib import Path
from pytestqt.qtbot import QtBot

# Import internal pickmix objects
from pickmix.config import load_config
from pickmix.gui.tabs.project_tab import ProjectTab
from pickmix.project import open_project

# TestProjectTab: project tab
class TestProjectTab:
    # test_top_bar: the project name and config path sit on the left, reload and close on the right
    def test_top_bar(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        path = make_config()
        tab = ProjectTab()
        qtbot.addWidget(tab)
        tab.set_project(open_project(path))
        assert tab.title_label.text() == path.parent.name and tab.path_label.text() == str(path.resolve())
        assert tab.title_label.font().bold() and tab.reload_button.toolTip() and tab.close_button.toolTip()

    # test_table: usable tomograms are listed and counted
    def test_table(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        tab = ProjectTab()
        qtbot.addWidget(tab)
        tab.set_project(open_project(make_config()))
        assert tab.tomograms.table.rowCount() == 1
        assert tab.tomograms.table.item(0, 1).text() == 'Position_1_2'
        assert tab.tomograms.summary.text() == '1 total (1 denoised), 0 rejected'

    # test_rejected_row: a rejected tomogram shows its reason
    def test_rejected_row(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        tab = ProjectTab()
        qtbot.addWidget(tab)
        tab.set_project(open_project(make_config(shape=(4, 6, 20))))
        assert 'shape mismatch' in tab.tomograms.table.item(0, 0).toolTip()
        assert tab.tomograms.table.item(0, 2).text() == '(4, 6, 20)'

    # test_open_config: opening in the background fills the tab and announces the project
    def test_open_config(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        tab = ProjectTab()
        qtbot.addWidget(tab)
        with qtbot.waitSignal(tab.project_changed):
            tab.open_config(make_config())
        assert tab.tomograms.table.rowCount() == 1

    # test_settings_autosave: changing source in the tab reaches config.toml and announces it, with no save button
    def test_settings_autosave(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        path = make_config()
        tab = ProjectTab()
        qtbot.addWidget(tab)
        tab.set_project(open_project(path))
        with qtbot.waitSignal(tab.config_saved):
            tab.settings_pane.source_box.setCurrentText('raw')
        assert load_config(path).source == 'raw'
        assert not hasattr(tab, 'save_button')

    # test_kinds_pane_shows_kinds: the kinds of the opened project are listed in their column
    def test_kinds_pane_shows_kinds(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        tab = ProjectTab()
        qtbot.addWidget(tab)
        tab.set_project(open_project(make_config()))
        assert tab.kinds_pane.kind_names() == ['cage']

    # test_hotkey_change_announces_kinds: a hotkey saved in the settings column tells the other tabs
    def test_hotkey_change_announces_kinds(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        tab = ProjectTab()
        qtbot.addWidget(tab)
        tab.set_project(open_project(make_config()))
        with qtbot.waitSignal(tab.kinds_saved):
            tab.settings_pane.hotkey_boxes[2].setCurrentText('cage')

    # test_new_kind_reaches_hotkeys: a kind added in the kinds column is offered in the settings dropdowns
    def test_new_kind_reaches_hotkeys(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        from pickmix.config import Kind
        tab = ProjectTab()
        qtbot.addWidget(tab)
        tab.set_project(open_project(make_config()))
        with qtbot.waitSignal(tab.kinds_saved):
            tab.kinds_pane._apply('yellow', Kind(marker_a=100, box_a=100))
        assert tab.settings_pane.hotkey_boxes[1].currentText() == 'yellow'

    # test_start_page_and_close: the welcome page shows until a project opens, and closing returns to it
    def test_start_page_and_close(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        tab = ProjectTab()
        qtbot.addWidget(tab)
        assert tab.stack.currentIndex() == 0
        tab.set_project(open_project(make_config()))
        assert tab.stack.currentIndex() == 1
        with qtbot.waitSignal(tab.project_closed):
            tab.close_button.click()
        assert tab.stack.currentIndex() == 0 and tab.project is None
