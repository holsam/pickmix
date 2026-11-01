'''
pickmix: tests for the Pick tab
'''

# Import external dependencies
import pytest
from collections.abc import Callable, Iterator
from pathlib import Path
from pytestqt.qtbot import QtBot

# Import internal pickmix objects
from pickmix.config import Kind
from pickmix.gui.pick_tab import PickTab
from pickmix.loader import Loader
from pickmix.model import Session
from pickmix.project import open_project

# THREE: tomograms for navigation tests
THREE: tuple[str, ...] = ('Position_1_2', 'Position_1_3', 'Other_9')

# Setup: a tab over a session and loader, shut down after the test
@pytest.fixture
def setup(qtbot: QtBot, make_config: Callable[..., Path]) -> Iterator[Callable[..., tuple[PickTab, Session]]]:
    loaders: list[Loader] = []

    # build: a tab on the first tomogram, with two kinds
    def build(names: tuple[str, ...] = ('Position_1_2',)) -> tuple[PickTab, Session]:
        project = open_project(make_config(names=names))
        project.update(kinds={'cage': Kind(marker_a=600, estimator='ring'), 'yellow': Kind(marker_a=100, box_a=100)})
        session, loader = Session(project), Loader(project)
        loaders.append(loader)
        tab = PickTab()
        qtbot.addWidget(tab)
        tab.set_session(session, loader)
        qtbot.waitUntil(lambda: tab.canvas.has_image, timeout=5000)
        return tab, session

    yield build
    for loader in loaders:
        loader.shutdown()

# TestPickTab: Pick tab
class TestPickTab:
    # test_opens_middle_slice: the middle slice of the tomogram is shown
    def test_opens_middle_slice(self, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, _ = setup()
        assert tab.z == 2 and tab.canvas.image_size() == (8, 6)
        assert tab.z_label.text() == '3 / 4'

    # test_add_pick: a click adds a pick of the active kind on the current slice
    def test_add_pick(self, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, session = setup()
        tab.canvas.add_requested.emit(3.0, 2.0)
        [pick] = session.store.all()
        assert (pick.kind, pick.x, pick.y, pick.z) == ('cage', 3.0, 2.0, 2.0)
        assert tab.canvas.marker_ids() == [pick.id] and tab.canvas.selected_id == pick.id
        assert tab.table.rowCount() == 1 and tab.table.item(0, 0).text() == 'cage'

    # test_kind_switch: number keys choose the kind that new picks get
    def test_kind_switch(self, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, session = setup()
        tab._pick_kind(1)
        assert tab.active == 'yellow' and tab.kind_buttons['yellow'].isChecked()
        tab.canvas.add_requested.emit(1.0, 1.0)
        assert session.store.all()[0].kind == 'yellow'
        tab._pick_kind(8)
        assert tab.active == 'yellow'

    # test_move_and_delete: moving keeps z, deleting removes the marker
    def test_move_and_delete(self, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, session = setup()
        tab.canvas.add_requested.emit(3.0, 2.0)
        pick = session.store.all()[0]
        tab.canvas.move_requested.emit(pick.id, 5.0, 4.0)
        assert (pick.x, pick.y, pick.z) == (5.0, 4.0, 2.0)
        tab.delete_selected()
        assert session.store.total() == 0 and tab.canvas.marker_ids() == []

    # test_click_pick_jumps_to_z: selecting a pick shows the slice it was picked on
    def test_click_pick_jumps_to_z(self, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, session = setup()
        pick = session.store.add('Position_1_2', 'cage', 1.0, 1.0, 0.0)
        tab.canvas.marker_clicked.emit(pick.id)
        assert tab.z == 0 and tab.canvas.selected_id == pick.id

    # test_scroll_z: wheel steps move the slice within range
    def test_scroll_z(self, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, _ = setup()
        tab.canvas.z_scrolled.emit(5)
        assert tab.z == 3
        tab.canvas.z_scrolled.emit(-9)
        assert tab.z == 0

    # test_hide_kind: a hidden kind's markers go but its picks stay in the list
    def test_hide_kind(self, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, session = setup()
        session.store.add('Position_1_2', 'cage', 1.0, 1.0, 1.0)
        tab.kind_boxes['cage'].setChecked(False)
        assert tab.canvas.marker_ids() == [] and tab.table.rowCount() == 1

    # test_navigation_clears_selection: a new tomogram starts with no selection and its own picks
    def test_navigation_clears_selection(self, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, session = setup(THREE)
        tab.canvas.add_requested.emit(3.0, 2.0)
        assert tab.canvas.selected_id is not None
        session.step(1)
        assert tab.canvas.selected_id is None and tab.table.rowCount() == 0
        assert tab.canvas.marker_ids() == []
        session.step(-1)
        assert tab.table.rowCount() == 1

    # test_late_open_ignored: results for a tomogram the user already left are dropped
    def test_late_open_ignored(self, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, session = setup(THREE)
        future = tab.loader.open('Position_1_2')
        session.step(1)
        tab._open_done('Position_1_2', future)
        assert tab.opened is None or tab.opened.name == 'Position_1_3'
