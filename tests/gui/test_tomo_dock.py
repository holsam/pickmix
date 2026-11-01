'''
pickmix: tests for tomogram dock
'''

# Import external dependencies
from collections.abc import Callable
from pathlib import Path
from pytestqt.qtbot import QtBot

# Import internal pickmix objects
from pickmix.gui.tomo_dock import TomoDock
from pickmix.model import Session
from pickmix.project import open_project

# THREE: tomograms for the dock tests
THREE: tuple[str, ...] = ('Position_1_2', 'Position_1_3', 'Other_9')

# _dock: a dock over a three-tomogram session
def _dock(qtbot: QtBot, make_config: Callable[..., Path]) -> tuple[TomoDock, Session]:
    session = Session(open_project(make_config(names=THREE)))
    dock = TomoDock()
    qtbot.addWidget(dock)
    dock.set_session(session)
    return dock, session

# TestTomoDock: tomogram dock
class TestTomoDock:
    # test_lines: current and opened markers, numbers, names and counts
    def test_lines(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        dock, session = _dock(qtbot, make_config)
        session.store.add('Position_1_2', 'cage', 1.0, 1.0, 1.0)
        assert dock.list.item(0).text().split() == ['>', '*', '1', 'Position_1_2', '1']
        assert dock.list.item(1).text().split() == ['2', 'Position_1_3', '0']

    # test_click_goes: clicking a line shows that tomogram and moves the marker
    def test_click_goes(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        dock, session = _dock(qtbot, make_config)
        dock._clicked(dock.list.item(2))
        assert session.current == 'Other_9'
        assert dock.list.item(2).text().startswith('> *')
        assert dock.list.item(0).text().startswith('  *')

    # test_jump_box: a name jumps and clears the box, no match keeps the text
    def test_jump_box(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        dock, session = _dock(qtbot, make_config)
        dock.jump_edit.setText('other')
        dock.jump_edit.returnPressed.emit()
        assert session.current == 'Other_9' and dock.jump_edit.text() == ''
        dock.jump_edit.setText('zzz')
        dock.jump_edit.returnPressed.emit()
        assert session.current == 'Other_9' and dock.jump_edit.text() == 'zzz'

    # test_totals: visited count and per-kind totals
    def test_totals(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        dock, session = _dock(qtbot, make_config)
        session.store.add('Position_1_3', 'cage', 1.0, 1.0, 1.0)
        assert dock.totals.text().split() == ['visited', '1/3', 'cage', '1']
