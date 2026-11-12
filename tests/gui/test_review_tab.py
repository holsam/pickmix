'''
pickmix: tests for the Review tab
'''

# Import external dependencies
import numpy as np
from collections.abc import Callable, Iterator
from pathlib import Path
import pytest
from PySide6.QtWidgets import QHeaderView
from pytestqt.qtbot import QtBot

# Import internal pickmix objects
from pickmix.config import Kind
from pickmix.estimate.registry import Fit
from pickmix.estimates import EstimateService
from pickmix.gui.tabs.review_tab import ReviewTab
from pickmix.loader import Loader
from pickmix.model import Session
from pickmix.project import open_project

# NAME: the single tomogram of the fixture project
NAME: str = 'Position_1_2'

# Setup: a review tab over a session with a passthrough kind and a failing kind, shut down after the test
@pytest.fixture
def setup(qtbot: QtBot, make_config: Callable[..., Path]) -> Iterator[Callable[[], tuple[ReviewTab, Session, EstimateService]]]:
    closers: list[Callable[[], None]] = []

    # build: the tab and its parts
    def build() -> tuple[ReviewTab, Session, EstimateService]:
        project = open_project(make_config())
        project.update(kinds={'yellow': Kind(marker_a=20, box_a=21.44), 'bad': Kind(marker_a=20, box_a=21.44, estimator='missing')})
        session, loader = Session(project), Loader(project)
        service = EstimateService(session, loader)
        closers.extend([service.shutdown, loader.shutdown])
        tab = ReviewTab()
        qtbot.addWidget(tab)
        tab.set_session(session, loader, service)
        return tab, session, service

    yield build
    for close in closers:
        close()

# parent_setup: a review tab over a session with a cage kind and a green kind whose parent is the cage
@pytest.fixture
def parent_setup(qtbot: QtBot, make_config: Callable[..., Path]) -> Iterator[tuple[ReviewTab, Session, EstimateService]]:
    project = open_project(make_config())
    project.update(kinds={
        'cage': Kind(marker_a=600, box_a=700),
        'green': Kind(marker_a=40, box_a=200, parent='cage', tilt_prior_deg=0.0),
    })
    session, loader = Session(project), Loader(project)
    service = EstimateService(session, loader)
    tab = ReviewTab()
    qtbot.addWidget(tab)
    tab.set_session(session, loader, service)
    yield tab, session, service
    service.shutdown()
    loader.shutdown()

# TestReviewTab: Review tab
class TestReviewTab:
    # test_quiet_table: the pick table has the shared quiet look
    def test_quiet_table(self, setup: Callable[[], tuple[ReviewTab, Session, EstimateService]]) -> None:
        tab, _, _ = setup()
        assert tab.table.verticalHeader().isHidden() and not tab.table.showGrid()

    # test_table_and_filters: rows follow the filters
    def test_table_and_filters(self, qtbot: QtBot, setup: Callable[[], tuple[ReviewTab, Session, EstimateService]]) -> None:
        tab, session, service = setup()
        session.store.add(NAME, 'yellow', 4.0, 3.0, 2.0)
        session.store.add(NAME, 'bad', 1.0, 1.0, 1.0)
        qtbot.waitUntil(lambda: service.pending == 0 and service.store.state(session.store.all()[1]) == 'ok', timeout=5000)
        tab.refresh()
        assert tab.table.rowCount() == 2 and tab.count_label.text() == '2 shown of 2'
        tab.kind_filter.setCurrentText('bad')
        assert tab.table.rowCount() == 1 and tab.table.item(0, 6).text() == 'error'
        tab.kind_filter.setCurrentText('(all)')
        tab.flag_filter.setCurrentText('Flagged only')
        assert [tab.table.item(r, 1).text() for r in range(tab.table.rowCount())] == ['bad']

    # test_delete_shown: only the picks the filters show are removed, here the flagged ones
    def test_delete_shown(self, qtbot: QtBot, setup: Callable[[], tuple[ReviewTab, Session, EstimateService]]) -> None:
        tab, session, service = setup()
        good = session.store.add(NAME, 'yellow', 4.0, 3.0, 2.0)
        session.store.add(NAME, 'bad', 1.0, 1.0, 1.0)
        qtbot.waitUntil(lambda: all(service.store.state(p) == 'ok' for p in session.store.all()), timeout=5000)
        tab.flag_filter.setCurrentText('Flagged only')
        assert tab.delete_shown() == 1
        assert [p.id for p in session.store.all()] == [good.id]

    # test_delete_selected: the selected pick goes, others stay, and nothing selected deletes nothing
    def test_delete_selected(self, qtbot: QtBot, setup: Callable[[], tuple[ReviewTab, Session, EstimateService]]) -> None:
        tab, session, service = setup()
        session.store.add(NAME, 'yellow', 4.0, 3.0, 2.0)
        second = session.store.add(NAME, 'yellow', 5.0, 3.0, 2.0)
        tab.refresh()
        tab.table.clearSelection()
        tab.table.setCurrentCell(-1, -1)
        assert tab.delete_selected() == 0
        tab.table.selectRow(0)
        assert tab.delete_selected() == 1
        assert [p.id for p in session.store.all()] == [second.id]

    # test_flag_filter_modes: all, flagged only and non-flagged only partition the picks
    def test_flag_filter_modes(self, qtbot: QtBot, setup: Callable[[], tuple[ReviewTab, Session, EstimateService]]) -> None:
        tab, session, service = setup()
        session.store.add(NAME, 'yellow', 4.0, 3.0, 2.0)
        session.store.add(NAME, 'bad', 1.0, 1.0, 1.0)
        qtbot.waitUntil(lambda: all(service.store.state(p) == 'ok' for p in session.store.all()), timeout=5000)
        tab.refresh()
        counts = []
        for choice in ('(all)', 'Flagged only', 'Non-flagged only'):
            tab.flag_filter.setCurrentText(choice)
            counts.append(tab.table.rowCount())
        assert counts == [2, 1, 1]

    # test_controls_layout: filters, buttons and the count are three separate columns of one row
    def test_controls_layout(self, setup: Callable[[], tuple[ReviewTab, Session, EstimateService]]) -> None:
        tab, _, _ = setup()
        assert tab.flag_filter.itemText(0) == '(all)' and tab.reestimate_button.text() == 'Re-estimate all'
        assert not tab.reestimate_button.icon().isNull()
        assert not hasattr(tab, 'delete_button') and not hasattr(tab, 'flagged_box')

    # test_status_icons_and_columns: the estimate column is an icon, and only tomogram and kind size to their contents
    def test_status_icons_and_columns(self, qtbot: QtBot, setup: Callable[[], tuple[ReviewTab, Session, EstimateService]]) -> None:
        tab, session, service = setup()
        session.store.add(NAME, 'yellow', 4.0, 3.0, 2.0)
        session.store.add(NAME, 'bad', 1.0, 1.0, 1.0)
        qtbot.waitUntil(lambda: all(service.store.state(p) == 'ok' for p in session.store.all()), timeout=5000)
        tab.refresh()
        rows = {tab.table.item(r, 1).text(): tab.table.item(r, 7) for r in range(tab.table.rowCount())}
        assert rows['yellow'].text() == '' and not rows['yellow'].icon().isNull() and rows['yellow'].toolTip() == 'Estimate is fine'
        assert not rows['bad'].icon().isNull() and 'error' in rows['bad'].toolTip()
        header = tab.table.horizontalHeader()
        modes = [header.sectionResizeMode(c) for c in range(8)]
        assert modes[:2] == [QHeaderView.ResizeMode.ResizeToContents] * 2 and set(modes[2:]) == {QHeaderView.ResizeMode.Stretch}

    # test_preview_labels: the headings are gone and each image is labelled in its corner instead
    def test_preview_labels(self, qtbot: QtBot, setup: Callable[[], tuple[ReviewTab, Session, EstimateService]]) -> None:
        tab, session, _ = setup()
        assert not hasattr(tab, 'xy_heading') and not hasattr(tab, 'xz_heading')
        session.store.add(NAME, 'yellow', 4.0, 3.0, 2.0)
        tab.refresh()
        tab.table.selectRow(0)
        qtbot.waitUntil(lambda: all(not label.pixmap().isNull() for label in (tab.xy_label, tab.xz_label, tab.yz_label)) and tab.patch_canvas.has_patch, timeout=5000)
        assert tab.yz_label.toolTip() and not tab.reestimate_button.icon().isNull()

    # test_crops: preview crops are cut around the pick
    def test_crops(self, qtbot: QtBot, setup: Callable[[], tuple[ReviewTab, Session, EstimateService]]) -> None:
        tab, _, _ = setup()
        xy, xz, yz = tab.crops(NAME, (4.0, 3.0, 2.0))
        vol = np.arange(4 * 6 * 8, dtype=np.float32).reshape(4, 6, 8)
        assert np.array_equal(xy, vol[2]) and np.array_equal(xz, vol[:, 3, :]) and np.array_equal(yz, vol[:, :, 4])

    # test_preview_grid: the previews are four panels, XY and the patch above XZ and YZ
    def test_preview_grid(self, setup: Callable[[], tuple[ReviewTab, Session, EstimateService]]) -> None:
        tab, _, _ = setup()
        grid = tab.previews
        assert [grid.itemAtPosition(r, c).widget() for r, c in ((0, 0), (0, 1), (1, 0), (1, 1))] == [tab.xy_label, tab.patch_canvas, tab.xz_label, tab.yz_label]
        assert tab.patch_canvas.toolTip()

    # test_preview_uses_pick_box: a pick with its box is outlined at that size
    def test_preview_uses_pick_box(self, setup: Callable[[], tuple[ReviewTab, Session, EstimateService]]) -> None:
        tab, session, _ = setup()
        pick = session.store.add(NAME, 'yellow', 4.0, 3.0, 2.0, box_a=10.72)
        preview = tab.preview(pick, None)
        px = session.project.tomos[NAME].pixel_size
        assert preview.patch.box_px == 10.72 / px

    # test_preview_geometry: the patch is 1.5 times the box, centred on the pick, and the outlines surround the pick in each crop
    def test_preview_geometry(self, setup: Callable[[], tuple[ReviewTab, Session, EstimateService]]) -> None:
        tab, session, _ = setup()
        pick = session.store.add(NAME, 'yellow', 4.0, 3.0, 2.0)
        px = session.project.tomos[NAME].pixel_size
        preview = tab.preview(pick, None)
        box = 21.44 / px
        assert preview.patch.pixels.shape == (6, 6) and preview.patch.origin == (1, 0) and preview.patch.box_px == box
        assert preview.patch.pick == (4.0, 3.0) and preview.patch.bounds == (8, 6)
        assert preview.outlines[0] == (4.5 - box / 2, 3.5 - box / 2, 4.5 + box / 2, 3.5 + box / 2)
        assert preview.outlines[1] == (4.5 - box / 2, 2.5 - box / 2, 4.5 + box / 2, 2.5 + box / 2)
        assert preview.outlines[2][:2] == (3.5 - box / 2, 2.5 - box / 2) and preview.slabs is None

    # test_preview_slab_from_fit: with a fit, the z range it used is outlined in XZ and YZ and the preview centres on the fit
    def test_preview_slab_from_fit(self, setup: Callable[[], tuple[ReviewTab, Session, EstimateService]]) -> None:
        tab, session, _ = setup()
        pick = session.store.add(NAME, 'yellow', 4.0, 3.0, 2.0)
        fit = Fit(x=5.0, y=3.0, z=2.0, radius_a=10, box_a=21.44, snr=1, z_lo=1, z_hi=3)
        preview = tab.preview(pick, fit)
        assert preview.patch.pick == (4.0, 3.0) and preview.patch.box_centre == (5.0, 3.0)
        assert preview.slabs is not None and (preview.slabs[0][1], preview.slabs[0][3]) == (1, 4)

    # test_patch_shows_filament_axis: the patch of a pick with a filament fit carries the fit's direction
    def test_patch_shows_filament_axis(self, setup: Callable[[], tuple[ReviewTab, Session, EstimateService]]) -> None:
        tab, session, _ = setup()
        pick = session.store.add(NAME, 'yellow', 4.0, 3.0, 2.0)
        fit = Fit(x=4.0, y=3.0, z=2.0, radius_a=10, box_a=21.44, snr=1, z_lo=1, z_hi=3, psi_deg=120.0)
        assert tab.preview(pick, fit).patch.psi_deg == 120.0 and tab.preview(pick, None).patch.psi_deg is None

    # test_patch_shown: selecting a pick shows its patch
    def test_patch_shown(self, qtbot: QtBot, setup: Callable[[], tuple[ReviewTab, Session, EstimateService]]) -> None:
        tab, session, _ = setup()
        session.store.add(NAME, 'yellow', 4.0, 3.0, 2.0)
        tab.refresh()
        tab.table.selectRow(0)
        qtbot.waitUntil(lambda: tab.patch_canvas.has_patch, timeout=5000)
        assert tab.patch_canvas.box_rect()[2] > 0

    # test_patch_drag_moves_pick: dragging the patch moves the pick, keeps it selected and refreshes the patch
    def test_patch_drag_moves_pick(self, qtbot: QtBot, setup: Callable[[], tuple[ReviewTab, Session, EstimateService]]) -> None:
        tab, session, _ = setup()
        pick = session.store.add(NAME, 'yellow', 4.0, 3.0, 2.0)
        tab.refresh()
        tab.table.selectRow(0)
        qtbot.waitUntil(lambda: tab.patch_canvas.has_patch, timeout=5000)
        tab.patch_canvas.move_requested.emit(pick.id, 5.0, 3.0)
        assert (session.store.get(pick.id).x, session.store.get(pick.id).y) == (5.0, 3.0)
        qtbot.waitUntil(lambda: tab.patch_canvas.patch is not None and tab.patch_canvas.patch.pick == (5.0, 3.0), timeout=5000)
        assert tab.table.currentRow() == 0

    # test_box_column_only_with_own_boxes: the review table shows each pick's own box once any shown pick has one
    def test_box_column_only_with_own_boxes(self, setup: Callable[[], tuple[ReviewTab, Session, EstimateService]]) -> None:
        tab, session, _ = setup()
        session.store.add(NAME, 'yellow', 4.0, 3.0, 2.0)
        tab.refresh()
        assert tab.table.isColumnHidden(8)
        session.store.add(NAME, 'yellow', 5.0, 3.0, 2.0, box_a=412.0)
        tab.refresh()
        assert not tab.table.isColumnHidden(8)
        assert sorted(tab.table.item(r, 8).text() for r in range(2)) == ['', '412']

    # test_validate_controls: the tab has a Validate button with an explanation and a Worst first box
    def test_validate_controls(self, setup: Callable[[], tuple[ReviewTab, Session, EstimateService]]) -> None:
        tab, _, _ = setup()
        assert tab.validate_button.text() == 'Validate' and 'lowcc' in tab.validate_button.toolTip() and 'several distinct views' in tab.validate_button.toolTip()
        assert tab.worst_first_box.text() == 'Worst first' and not tab.worst_first_box.isChecked()

    # test_score_column_and_worst_first: scores appear once a pick has one, and Worst first puts the lowest first with unscored picks last
    def test_score_column_and_worst_first(self, qtbot: QtBot, setup: Callable[[], tuple[ReviewTab, Session, EstimateService]]) -> None:
        tab, session, service = setup()
        picks = [session.store.add(NAME, 'yellow', float(x), 3.0, 2.0) for x in (1, 2, 3, 4)]
        qtbot.waitUntil(lambda: all(service.store.state(p) == 'ok' for p in picks), timeout=5000)
        tab.refresh()
        assert tab.table.isColumnHidden(9) and [tab.table.item(r, 2).text() for r in range(4)] == ['1.0', '2.0', '3.0', '4.0']
        service.validation.put_kind('yellow', [(picks[0], 0.50, False), (picks[1], 0.10, True), (picks[3], 0.30, False)])
        qtbot.waitUntil(lambda: not tab.table.isColumnHidden(9), timeout=5000)
        assert [tab.table.item(r, 9).text() for r in range(4)] == ['0.50', '0.10', '', '0.30']
        assert [tab.table.item(r, 6).text() for r in range(4)] == ['', 'lowcc', '', '']
        tab.worst_first_box.setChecked(True)
        assert [tab.table.item(r, 2).text() for r in range(4)] == ['2.0', '4.0', '1.0', '3.0']
        tab.flag_filter.setCurrentIndex(1)
        assert tab.table.rowCount() == 1 and tab.table.item(0, 2).text() == '2.0'

    # test_validate_reports: Validate scores the chosen kind in the background and says what it found; a kind with too few picks says so
    def test_validate_reports(self, qtbot: QtBot, setup: Callable[[], tuple[ReviewTab, Session, EstimateService]], capsys) -> None:
        tab, session, service = setup()
        for x in range(12):
            session.store.add(NAME, 'yellow', float(x % 8), float(x % 6), float(x % 4))
        session.store.add(NAME, 'bad', 1.0, 1.0, 1.0)
        qtbot.waitUntil(lambda: all(service.store.state(p) == 'ok' for p in session.store.all()), timeout=5000)
        tab.refresh()
        tab.kind_filter.setCurrentText('yellow')
        capsys.readouterr()
        tab.validate_button.click()
        assert not tab.validate_button.isEnabled()
        qtbot.waitUntil(lambda: tab.validate_button.isEnabled(), timeout=10000)
        assert 'yellow: scored 12' in capsys.readouterr().out
        assert all(service.validation.state(p) == 'ok' for p in session.store.all('yellow'))
        tab.kind_filter.setCurrentText('(all)')
        tab.validate_button.click()
        qtbot.waitUntil(lambda: tab.validate_button.isEnabled(), timeout=10000)
        assert "kind 'bad': needs at least 10 picks to validate, has 1" in capsys.readouterr().out

    # test_validate_nothing_to_do: with no picks of the chosen kind it says so and starts nothing
    def test_validate_nothing_to_do(self, setup: Callable[[], tuple[ReviewTab, Session, EstimateService]], capsys) -> None:
        tab, _, _ = setup()
        tab.validate_button.click()
        assert 'No picks to validate' in capsys.readouterr().out and tab.validate_button.isEnabled()

    # test_double_click_opens: double-clicking a row asks to open the pick
    def test_double_click_opens(self, qtbot: QtBot, setup: Callable[[], tuple[ReviewTab, Session, EstimateService]]) -> None:
        tab, session, service = setup()
        pick = session.store.add(NAME, 'yellow', 4.0, 3.0, 2.0)
        tab.refresh()
        with qtbot.waitSignal(tab.open_pick) as blocker:
            tab._double_clicked(0, 0)
        assert blocker.args == [NAME, pick.id]

    # test_unmatched_flagged: a pick off its parent's surface is flagged noparent and can be deleted
    def test_unmatched_flagged(self, qtbot: QtBot, parent_setup: tuple[ReviewTab, Session, EstimateService]) -> None:
        tab, session, service = parent_setup
        session.store.add(NAME, 'cage', 10.0, 10.0, 10.0)
        session.store.add(NAME, 'green', 10.0 + 56.0, 10.0, 10.0)
        session.store.add(NAME, 'green', 10.0 + 20.0, 10.0, 10.0)
        qtbot.waitUntil(lambda: all(service.store.state(p) == 'ok' for p in session.store.all()), timeout=5000)
        tab.refresh()
        flags = {(tab.table.item(r, 1).text(), tab.table.item(r, 6).text()) for r in range(tab.table.rowCount())}
        assert ('green', 'noparent') in flags
