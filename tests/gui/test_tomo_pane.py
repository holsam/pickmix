'''
pickmix: tests for tomogram pane
'''

# Import external dependencies
from collections.abc import Callable
from pathlib import Path
from pytestqt.qtbot import QtBot

# Import internal pickmix objects
from pickmix.gui.panes.tomo_pane import COLOUR_CURRENT, COLOUR_PENDING, COLOUR_VISITED, TomoPane

from pickmix.model import Session
from pickmix.project import open_project

# THREE: tomograms for the dock tests
THREE: tuple[str, ...] = ('Position_1_2', 'Position_1_3', 'Other_9')

# _pane: a pane over a three-tomogram session
def _pane(qtbot: QtBot, make_config: Callable[..., Path]) -> tuple[TomoPane, Session]:
    session = Session(open_project(make_config(names=THREE)))
    pane = TomoPane()
    qtbot.addWidget(pane)
    pane.set_session(session)
    return pane, session

# TestTomoPane: tomogram dock
class TestTomoPane:
    # test_lines: number, name and picks, no markers
    def test_lines(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, session = _pane(qtbot, make_config)
        session.store.add('Position_1_2', 'cage', 1.0, 1.0, 1.0)
        assert pane.list.item(0).text().split() == ['1', 'Position_1_2', '1']
        assert pane.list.item(1).text().split() == ['2', 'Position_1_3', '0']

    # test_state_colours: current blue and bold, opened green, not yet opened orange
    def test_state_colours(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, session = _pane(qtbot, make_config)
        assert pane.list.item(0).foreground().color() == COLOUR_CURRENT and pane.list.item(0).font().bold()
        assert pane.list.item(1).foreground().color() == COLOUR_PENDING and not pane.list.item(1).font().bold()
        pane._clicked(pane.list.item(2))
        assert session.current == 'Other_9'
        assert pane.list.item(2).foreground().color() == COLOUR_CURRENT
        assert pane.list.item(0).foreground().color() == COLOUR_VISITED and not pane.list.item(0).font().bold()
        assert pane.list.item(1).foreground().color() == COLOUR_PENDING

    # test_visited_label: visited count sits above the search box, with no per-kind totals
    def test_visited_label(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, session = _pane(qtbot, make_config)
        assert pane.visited.text() == 'Visited 1/3'
        session.go(1)
        assert pane.visited.text() == 'Visited 2/3'
        assert not hasattr(pane, 'totals')

    # test_jump_box: a name jumps and clears the box, no match keeps the text
    def test_jump_box(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, session = _pane(qtbot, make_config)
        pane.jump_edit.setText('other')
        pane.jump_edit.returnPressed.emit()
        assert session.current == 'Other_9' and pane.jump_edit.text() == ''
        pane.jump_edit.setText('zzz')
        pane.jump_edit.returnPressed.emit()
        assert session.current == 'Other_9' and pane.jump_edit.text() == 'zzz'
