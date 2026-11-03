'''
pickmix: tests for the Project tab
'''

# Import external dependencies
from collections.abc import Callable
from pathlib import Path
from pytestqt.qtbot import QtBot

# Import internal pickmix objects
from pickmix.config import load_config
from pickmix.gui.project_tab import ProjectTab
from pickmix.project import open_project

# TestProjectTab: project tab
class TestProjectTab:
    # test_table: usable tomograms are listed and counted
    def test_table(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        tab = ProjectTab()
        qtbot.addWidget(tab)
        tab.set_project(open_project(make_config()))
        assert tab.table.rowCount() == 1
        assert tab.table.item(0, 0).text() == 'Position_1_2'
        assert tab.table.item(0, 4).text() == 'ok'
        assert tab.summary.text() == '1 usable (1 with denoised), 0 rejected'

    # test_rejected_row: a rejected tomogram shows its reason
    def test_rejected_row(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        tab = ProjectTab()
        qtbot.addWidget(tab)
        tab.set_project(open_project(make_config(shape=(4, 6, 20))))
        assert tab.table.item(0, 4).text() == 'rejected: shape mismatch'
        assert tab.table.item(0, 1).text() == '(4, 6, 20)'

    # test_open_config: opening in the background fills the tab and announces the project
    def test_open_config(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        tab = ProjectTab()
        qtbot.addWidget(tab)
        with qtbot.waitSignal(tab.project_changed):
            tab.open_config(make_config())
        assert tab.table.rowCount() == 1

    # test_save_settings: source and a ring parameter reach config.toml
    def test_save_settings(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        path = make_config()
        tab = ProjectTab()
        qtbot.addWidget(tab)
        tab.set_project(open_project(path))
        tab.source_box.setCurrentText('raw')
        tab.ring_form._boxes['radius_step_a'][0].setValue(50.0)
        with qtbot.waitSignal(tab.config_saved):
            tab.save_button.click()
        config = load_config(path)
        assert config.source == 'raw'
        assert config.ring.radius_step_a == 50.0
        assert config.ring.radius_range_a == (150.0, 500.0)

    # test_form_labels: parameters show their title and explain themselves on hover
    def test_form_labels(self, qtbot: QtBot) -> None:
        tab = ProjectTab()
        qtbot.addWidget(tab)
        label = tab.ring_form.labels['radius_range_a']
        assert label.text() == 'Radius range (Å)' and label.toolTip()
        assert len(tab.ring_form._boxes['radius_range_a']) == 2

    # test_ring_section_collapsed: ring parameters are hidden until the section is opened
    def test_ring_section_collapsed(self, qtbot: QtBot) -> None:
        tab = ProjectTab()
        qtbot.addWidget(tab)
        assert tab.ring_form.isHidden()
        tab.ring_section.toggle.setChecked(True)
        assert not tab.ring_form.isHidden()

    # test_settings_width_fixed: opening the ring section does not change settings pane width
    def test_settings_width_fixed(self, qtbot: QtBot) -> None:
        tab = ProjectTab()
        qtbot.addWidget(tab)
        closed = tab.settings.minimumSizeHint().width()
        tab.ring_section.toggle.setChecked(True)
        assert tab.settings.minimumSizeHint().width() == closed
