'''
pickmix: tests for the Pick tab
'''

# Import external dependencies
import pytest
from collections.abc import Callable, Iterator
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView
from pytestqt.qtbot import QtBot

# Import internal pickmix objects
from pickmix.candidates import Hit
from pickmix.config import Kind
from pickmix.estimates import EstimateService
from pickmix.gui.tabs.pick_tab import PickTab
from pickmix.loader import Loader
from pickmix.matcher import MatchService
from pickmix.model import Session
from pickmix.project import open_project

# NAME: the first tomogram of the fixture project
NAME: str = 'Position_1_2'

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

    # test_quiet_table: the pick table has the shared quiet look
    def test_quiet_table(self, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, _ = setup()
        assert tab.table.verticalHeader().isHidden() and not tab.table.showGrid()

    # test_add_pick: a click adds a pick of the active kind on the current slice
    def test_add_pick(self, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, session = setup()
        tab.canvas.add_requested.emit(3.0, 2.0)
        [pick] = session.store.all()
        assert (pick.kind, pick.x, pick.y, pick.z) == ('cage', 3.0, 2.0, 2.0)
        assert tab.canvas.marker_ids() == [pick.id] and tab.canvas.selected_id == pick.id
        assert tab.table.rowCount() == 1 and tab.table.item(0, 1).text() == 'cage'

    # test_kind_switch: number keys choose the kind that new picks get
    def test_kind_switch(self, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, session = setup()
        tab.pick_kind(1)
        assert tab.active == 'yellow' and tab.kind_buttons['yellow'].isChecked()
        tab.canvas.add_requested.emit(1.0, 1.0)
        assert session.store.all()[0].kind == 'yellow'
        tab.pick_kind(8)
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

    # test_delete_needs_selection: Delete is greyed until a pick is selected and again once it is gone
    def test_delete_needs_selection(self, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, _ = setup()
        assert not tab.delete_button.isEnabled()
        tab.canvas.add_requested.emit(3.0, 2.0)
        assert tab.delete_button.isEnabled()
        tab.delete_selected()
        assert not tab.delete_button.isEnabled()

    # test_hide_kind: a hidden kind's markers go but its picks stay in the list
    def test_hide_kind(self, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, session = setup()
        session.store.add('Position_1_2', 'cage', 1.0, 1.0, 1.0)
        tab.kind_toggles['cage'].setChecked(False)
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
        qtbot.waitUntil(lambda: tab.table.item(0, 5) is not None and tab.table.item(0, 5).text() == '0.00', timeout=5000)
        assert tab.table.item(0, 6).text() == ''

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
        qtbot.waitUntil(lambda: 'noparent' in {tab.table.item(r, 6).text() for r in range(tab.table.rowCount())}, timeout=5000)
        assert [tab.table.item(r, 6).text() for r in range(3)] == ['', '', 'noparent']

    # test_hotkeys_follow_config: keys choose the kind the config puts on them, and buttons show their number
    def test_hotkeys_follow_config(self, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, session = setup()
        session.project.update(hotkeys=['', 'green', 'cage'])
        tab.refresh_kinds()
        tab.pick_kind(0)
        assert tab.active == 'cage'
        tab.pick_kind(1)
        assert tab.active == 'green'
        tab.pick_kind(2)
        assert tab.active == 'cage'
        assert tab.kind_buttons['green'].text() == '(2) green' and tab.kind_buttons['yellow'].text() == 'yellow'

    # test_no_kinds: with every kind deleted there is no active kind and a click adds nothing
    def test_no_kinds(self, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, session = setup()
        session.project.update(kinds={})
        tab.refresh_kinds()
        assert tab.active is None and tab.kind_buttons == {}
        tab.canvas.add_requested.emit(1.0, 1.0)
        assert session.store.all() == []
        tab.pick_kind(0)
        assert tab.active is None

    # test_title_is_name_only: the title is the tomogram name, with the navigation help kept below
    def test_title_is_name_only(self, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, session = setup()
        assert tab.title.text() == session.current and tab.title.font().bold()
        assert 'Enter' in tab.help.text()

    # test_hotkeys_row: the key and name label chooses the kind, the eye icon toggles it and starts checked
    def test_hotkeys_row(self, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, _ = setup()
        assert tab.kind_buttons['yellow'].text() == '(2) yellow'
        assert all(t.isChecked() for t in tab.kind_toggles.values())
        assert tab.kind_buttons['yellow'].minimumWidth() > 0
        tab.kind_toggles['yellow'].click()
        assert 'yellow' in tab.hidden and not tab.kind_toggles['yellow'].isChecked()
        tab.pick_kind(1)
        assert tab.active == 'yellow'

    # test_auto_and_manual: Auto starts ticked, a manual change unticks it and ticking it restores the tomogram's limits
    def test_auto_and_manual(self, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, _ = setup()
        assert tab.auto_box.isChecked() and tab.invert_box.isChecked() is False
        auto = tab.contrast.values()
        tab.contrast.set_values(auto[0] + 10, auto[1] - 10, emit=True)
        assert not tab.auto_box.isChecked() and tab.contrast.values() != auto
        tab.auto_box.setChecked(True)
        assert tab.contrast.values() == auto and tab.brightness.value() == 0

    # test_brightness_shifts_window: positive brightness lowers the window by that share of its width
    def test_brightness_shifts_window(self, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, _ = setup()
        lo, hi = tab._window()
        tab.brightness.setValue(10)
        new_lo, new_hi = tab._window()
        assert not tab.auto_box.isChecked()
        assert abs((lo - new_lo) - 0.1 * (hi - lo)) < 1e-6 and abs((new_hi - new_lo) - (hi - lo)) < 1e-6

    # test_manual_window_kept_across_tomograms: with Auto off, the next tomogram opens with the same pixel-value window
    def test_manual_window_kept_across_tomograms(self, qtbot: QtBot, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, session = setup(THREE)
        low, high = tab.contrast.values()
        tab.contrast.set_values(low + 50, high - 50, emit=True)
        raw = tab._raw_window()
        session.step(1)
        qtbot.waitUntil(lambda: tab.opened is not None and tab.opened.name == 'Position_1_3', timeout=5000)
        new = tab._raw_window()
        assert abs(new[0] - raw[0]) < 2 and abs(new[1] - raw[1]) < 2

    # test_layout: Z is a vertical scrollbar and image and overlay controls sit in the settings pane
    def test_layout(self, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, _ = setup()
        assert tab.z_slider.orientation() == Qt.Orientation.Vertical and tab.settings.width() <= 220
        for widget in (tab.contrast, tab.brightness, tab.auto_box, tab.invert_box, tab.fit_button, tab.fill_button, tab.rings_box, tab.boxes_box, tab.normals_box, *tab.kind_buttons.values()):
            assert tab.settings.isAncestorOf(widget)
        assert not tab.settings.isAncestorOf(tab.table) and not tab.settings.isAncestorOf(tab.z_slider)
        header = tab.table.horizontalHeader()
        assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.Fixed and header.sectionResizeMode(1) == QHeaderView.ResizeMode.ResizeToContents

    # test_tomo_pane_toggle: the tomogram pane sits in the tab and its button hides and shows it
    def test_tomo_pane_toggle(self, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, session = setup(THREE)
        assert tab.splitter.indexOf(tab.tomo) == 0 and not tab.tomo.isHidden()
        assert tab.tomo.list.count() == 3
        tab.tomo_toggle.click()
        assert tab.tomo.isHidden()
        tab.tomo_toggle.click()
        assert not tab.tomo.isHidden()
        assert not tab.tomo_toggle.icon().isNull()

    # test_tomo_pane_navigates: choosing a tomogram in the pane changes the tomogram shown
    def test_tomo_pane_navigates(self, qtbot: QtBot, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, session = setup(THREE)
        tab.tomo._clicked(tab.tomo.list.item(2))
        assert session.current == 'Other_9' and tab.title.text() == 'Other_9'

    # test_status_badges: each row has a badge, spinning until the estimate arrives and ok after
    def test_status_badges(self, qtbot: QtBot, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, session = setup()
        session.store.add('Position_1_2', 'yellow', 3.0, 2.0, 2.0)
        assert tab.table.horizontalHeaderItem(0).text() == '' and tab.table.cellWidget(0, 0) is not None
        qtbot.waitUntil(lambda: tab.table.cellWidget(0, 0).status == 'ok', timeout=5000)
        assert tab.status.text() == ''

    # test_view_toggles: each overlay toggle starts shown, hides its overlay and shows a different eye when hidden
    def test_view_toggles(self, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, _ = setup()
        assert all(b.isChecked() for b in (tab.rings_box, tab.boxes_box, tab.normals_box))
        shown_icon = tab.rings_box.icon().cacheKey()
        tab.rings_box.click()
        assert not tab.rings_box.isChecked() and tab.rings_box.icon().cacheKey() != shown_icon
        assert tab.rings_box.text() == 'Rings'

    # test_delete_icon: delete is an icon button with a tooltip
    def test_delete_icon(self, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, _ = setup()
        assert not tab.delete_button.icon().isNull() and tab.delete_button.toolTip()

    # test_fit_and_fill_buttons: both buttons act on the canvas view
    def test_fit_and_fill_buttons(self, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, _ = setup()
        tab.resize(900, 600)
        tab.show()
        tab.fit_button.click()
        fit_scale = tab.canvas.transform().m11()
        tab.fill_button.click()
        assert tab.canvas.transform().m11() >= fit_scale

    # test_candidates_drawn: candidates of shown kinds are drawn with negative ids, best-score filter applied
    def test_candidates_drawn(self, qtbot: QtBot, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, session = setup()
        session.candidates.replace(NAME, 'cage', [Hit(2, 2, 1, 0.3), Hit(5, 4, 2, 0.6)], reach=1)
        qtbot.waitUntil(lambda: len(tab.canvas.marker_ids()) == 2, timeout=5000)
        assert tab.canvas.marker_ids() == [-2, -1]
        tab.match_pane.score_slider.setValue(50)
        assert tab.canvas.marker_ids() == [-2]
        assert 'score 0.60' in tab.canvas._items[-2].toolTip()

    # test_hidden_kind_hides_candidates: hiding a kind hides its candidates too
    def test_hidden_kind_hides_candidates(self, qtbot: QtBot, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, session = setup()
        session.candidates.replace(NAME, 'cage', [Hit(2, 2, 1, 0.6)], reach=1)
        qtbot.waitUntil(lambda: tab.canvas.marker_ids() == [-1], timeout=5000)
        tab.kind_toggles['cage'].setChecked(False)
        assert tab.canvas.marker_ids() == []

    # test_accept_selected: accepting a selected candidate converts it to a pick of its kind and selects it
    def test_accept_selected(self, qtbot: QtBot, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, session = setup()
        session.candidates.replace(NAME, 'cage', [Hit(2, 2, 1, 0.6)], reach=1)
        qtbot.waitUntil(lambda: tab.canvas.marker_ids() == [-1], timeout=5000)
        tab._clicked(-1)
        assert tab.canvas.selected_id == -1 and tab.z_slider.value() == 1 and tab.match_pane.accept_button.isEnabled()
        tab.accept_selected()
        (pick,) = session.store.all('cage')
        assert (pick.x, pick.y, pick.z) == (2, 2, 1) and tab.canvas.selected_id == pick.id
        assert session.candidates.count('cage') == 0 and tab.canvas.marker_ids() == [pick.id]

    # test_delete_rejects_candidate: delete on a selected candidate rejects it and a later scan leaves it out
    def test_delete_rejects_candidate(self, qtbot: QtBot, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, session = setup()
        session.candidates.replace(NAME, 'cage', [Hit(2, 2, 1, 0.6)], reach=1)
        qtbot.waitUntil(lambda: tab.canvas.marker_ids() == [-1], timeout=5000)
        tab._clicked(-1)
        tab.delete_selected()
        assert tab.canvas.marker_ids() == [] and session.store.total() == 0
        session.candidates.replace(NAME, 'cage', [Hit(2, 2, 1, 0.6)], reach=1)
        assert session.candidates.count('cage') == 0

    # test_accept_shown: test accept all converts all candidates of a kind in active tomogram to pick (if above score)
    def test_accept_shown(self, qtbot: QtBot, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, session = setup()
        session.candidates.replace(NAME, 'cage', [Hit(2, 2, 1, 0.3), Hit(5, 4, 2, 0.6)], reach=1)
        qtbot.waitUntil(lambda: len(tab.canvas.marker_ids()) == 2, timeout=5000)
        tab.match_pane.score_slider.setValue(50)
        assert tab.match_pane.accept_all_button.isEnabled()
        tab.accept_shown()
        assert [(p.x, p.y) for p in session.store.all('cage')] == [(5, 4)] and session.candidates.count('cage') == 1

    # test_scan_needs_picks: scan waits for a pick of active kind
    def test_scan_needs_picks(self, qtbot: QtBot, setup: Callable[..., tuple[PickTab, Session]]) -> None:
        tab, session = setup()
        matcher = MatchService(session)
        tab.matcher = matcher
        tab.match_pane.set_matcher(matcher, 0.2)
        tab._set_active('cage')
        assert not tab.match_pane.scan_button.isEnabled() and 'Pick some cage' in tab.match_pane.status.text()
        session.store.add(NAME, 'cage', 3, 3, 2)
        assert tab.match_pane.scan_button.isEnabled()
        matcher.shutdown()
