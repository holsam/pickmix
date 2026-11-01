'''
pickmix: tests for the Kinds tab
'''

# Import external dependencies
from collections.abc import Callable
from pathlib import Path
from pytestqt.qtbot import QtBot
from PySide6.QtWidgets import QComboBox

# Import internal pickmix objects
from pickmix.config import Kind, load_config
from pickmix.gui.kinds_tab import KindsTab
from pickmix.project import open_project

# _tab: a Kinds tab showing a fresh project; returns the tab and the config path
def _tab(qtbot: QtBot, make_config: Callable[..., Path]) -> tuple[KindsTab, Path]:
    path = make_config()
    tab = KindsTab()
    qtbot.addWidget(tab)
    tab.set_project(open_project(path))
    return tab, path

# TestKindsTab: kinds tab
class TestKindsTab:
    # test_load: the default cage kind shows and collects back unchanged
    def test_load(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        tab, _ = _tab(qtbot, make_config)
        assert tab.table.rowCount() == 1
        assert tab.collect() == tab.project.config.kinds

    # test_unregistered_estimator_kept: an estimator name the registry does not know must survive load and save
    def test_unregistered_estimator_kept(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        path = make_config()
        project = open_project(path)
        project.update(kinds={'cage': Kind(marker_a=600, estimator='future_fit')})
        tab = KindsTab()
        qtbot.addWidget(tab)
        tab.set_project(project)
        combo = tab.table.cellWidget(0, 3)
        assert isinstance(combo, QComboBox) and combo.currentText() == 'future_fit'
        tab.save()
        assert load_config(path).kinds['cage'].estimator == 'future_fit'

    # test_add_edit_save: a new kind edited in the table reaches config.toml in order
    def test_add_edit_save(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        tab, path = _tab(qtbot, make_config)
        tab.add_kind()
        tab.table.item(1, 0).setText('yellow')
        tab.table.item(1, 1).setText('100')
        with qtbot.waitSignal(tab.config_saved):
            tab.save()
        kinds = load_config(path).kinds
        assert list(kinds) == ['cage', 'yellow']
        assert kinds['yellow'] == Kind(marker_a=100, box_a=100)

    # test_invalid_not_saved: a bad table leaves the file alone and says why
    def test_invalid_not_saved(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        tab, path = _tab(qtbot, make_config)
        before = path.read_text()
        tab.add_kind()
        tab.table.item(1, 5).setText('missing')
        tab.save()
        assert 'unknown parent' in tab.status.text()
        assert path.read_text() == before

    # test_bad_number_and_colour: unreadable cells are reported with the row
    def test_bad_number_and_colour(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        tab, _ = _tab(qtbot, make_config)
        tab.table.item(0, 1).setText('abc')
        tab.save()
        assert tab.status.text().startswith('Not saved: row 1')
        tab.table.item(0, 1).setText('600')
        tab.table.item(0, 4).setText('notacolour')
        tab.save()
        assert 'not a colour' in tab.status.text()

    # test_duplicate_name: two rows with one name are rejected
    def test_duplicate_name(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        tab, _ = _tab(qtbot, make_config)
        tab.add_kind()
        tab.table.item(1, 0).setText('cage')
        tab.save()
        assert 'duplicate' in tab.status.text()

    # test_move_and_remove: Up swaps rows, Remove drops the selection
    def test_move_and_remove(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        tab, _ = _tab(qtbot, make_config)
        tab.add_kind()
        tab.table.selectRow(1)
        tab._move(-1)
        assert list(tab.collect()) == ['kind1', 'cage']
        tab.table.selectRow(0)
        tab.remove_selected()
        assert list(tab.collect()) == ['cage']
