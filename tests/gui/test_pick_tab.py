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
from pickmix.estimates import EstimateService
from pickmix.gui.pick_tab import PickTab
from pickmix.loader import Loader
from pickmix.model import Session
from pickmix.project import open_project

# THREE: tomograms for navigation tests
THREE: tuple[str, ...] = ('Position_1_2', 'Position_1_3', 'Other_9')

# Setup: a tab over a session, loader and estimate service, shut down after the test
@pytest.fixture
def setup(qtbot: QtBot, make_config: Callable[..., Path]) -> Iterator[Callable[..., tuple[PickTab, Session]]]:
    closers: list[Callable[[], None]] = []

    # build: a tab on the first tomogram, with two kinds
    def build(names: tuple[str, ...] = ('Position_1_2',)) -> tuple[PickTab, Session]:
        project = open_project(make_config(names=names))
        project.update(kinds={
            'cage': Kind(marker_a=600, box_a=700), 'yellow': Kind(marker_a=100, box_a=100),
            'green': Kind(marker_a=40, box_a=200, parent='cage'),
        })
        session, loader = Session(project), Loader(project)
        service = EstimateService(session, loader)
        closers.extend([service.shutdown, loader.shutdown])
        tab = PickTab()
        qtbot.addWidget(tab)
        tab.set_session(session, loader, service)
        qtbot.waitUntil(lambda: tab.canvas.has_image, timeout=5000)
        return tab, session

    yield build
    for close in closers:
        close()

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

    # test_estimate_overlay: a fitted pick gets its box drawn and its SNR and flag listed
    def test_estimate_overlay(self, qtbot: QtBot, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, session = setup()
        pick = session.store.add('Position_1_2', 'yellow', 3.0, 2.0, 2.0)
        qtbot.waitUntil(lambda: tab.canvas.overlay_visible(pick.id)[1], timeout=5000)
        qtbot.waitUntil(lambda: tab.table.item(0, 4) is not None and tab.table.item(0, 4).text() == '0.00', timeout=5000)
        assert tab.table.item(0, 5).text() == ''

    # test_show_pick: a pick in another tomogram opens that tomogram and selects the pick
    def test_show_pick(self, qtbot: QtBot, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, session = setup(THREE)
        pick = session.store.add('Other_9', 'cage', 1.0, 1.0, 1.0)
        tab.show_pick(pick.id)
        assert session.current == 'Other_9'
        qtbot.waitUntil(lambda: tab.canvas.selected_id == pick.id, timeout=5000)
        assert tab.z == 1

    # test_normals_and_noparent: a pick on its parent's surface gets a normal, one off the surface is flagged noparent
    def test_normals_and_noparent(self, qtbot: QtBot, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, session = setup()
        session.store.add('Position_1_2', 'cage', 3.0, 2.0, 2.0)
        near = session.store.add('Position_1_2', 'green', 3.0 + 56.0, 2.0, 2.0)
        session.store.add('Position_1_2', 'green', 3.0 + 20.0, 2.0, 2.0)
        qtbot.waitUntil(lambda: tab.canvas.normal_visible(near.id), timeout=5000)
        qtbot.waitUntil(lambda: 'noparent' in {tab.table.item(r, 5).text() for r in range(tab.table.rowCount())}, timeout=5000)
        assert [tab.table.item(r, 5).text() for r in range(3)] == ['', '', 'noparent']

    # test_hotkeys_follow_config: keys choose the kind the config puts on them, and buttons show their number
    def test_hotkeys_follow_config(self, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, session = setup()
        session.project.update(hotkeys=['', 'green', 'cage'])
        tab.refresh_kinds()
        tab._pick_kind(0)
        assert tab.active == 'cage'
        tab._pick_kind(1)
        assert tab.active == 'green'
        tab._pick_kind(2)
        assert tab.active == 'cage'
        assert tab.kind_buttons['green'].text() == '2 green' and tab.kind_buttons['yellow'].text() == 'yellow'

    # test_no_kinds: with every kind deleted there is no active kind and a click adds nothing
    def test_no_kinds(self, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, session = setup()
        session.project.update(kinds={})
        tab.refresh_kinds()
        assert tab.active is None and tab.kind_buttons == {}
        tab.canvas.add_requested.emit(1.0, 1.0)
        assert session.store.all() == []
        tab._pick_kind(0)
        assert tab.active is None
