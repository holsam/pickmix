'''
pickmix: tests for the Review tab
'''

# Import external dependencies
import numpy as np
from collections.abc import Callable, Iterator
from pathlib import Path
import pytest
from pytestqt.qtbot import QtBot

# Import internal pickmix objects
from pickmix.config import Kind
from pickmix.estimates import EstimateService
from pickmix.gui.review_tab import ReviewTab
from pickmix.loader import Loader
from pickmix.model import Session
from pickmix.project import open_project
from pickmix.utils.star import read_star_loop

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

# TestReviewTab: Review tab
class TestReviewTab:
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
        tab.flagged_box.setChecked(True)
        assert [tab.table.item(r, 1).text() for r in range(tab.table.rowCount())] == ['bad']

    # test_delete_flagged: only flagged picks shown are removed
    def test_delete_flagged(self, qtbot: QtBot, setup: Callable[[], tuple[ReviewTab, Session, EstimateService]]) -> None:
        tab, session, service = setup()
        good = session.store.add(NAME, 'yellow', 4.0, 3.0, 2.0)
        session.store.add(NAME, 'bad', 1.0, 1.0, 1.0)
        qtbot.waitUntil(lambda: all(service.store.state(p) == 'ok' for p in session.store.all()), timeout=5000)
        tab.refresh()
        assert tab.delete_flagged() == 1
        assert [p.id for p in session.store.all()] == [good.id]

    # test_kind_numbers: per-kind counts and box in the export table
    def test_kind_numbers(self, qtbot: QtBot, setup: Callable[[], tuple[ReviewTab, Session, EstimateService]]) -> None:
        tab, session, service = setup()
        pick = session.store.add(NAME, 'yellow', 4.0, 3.0, 2.0)
        qtbot.waitUntil(lambda: service.store.state(pick) == 'ok', timeout=5000)
        tab.refresh()
        assert [tab.kinds_table.item(0, c).text() for c in range(6)] == ['yellow', '1', '1', '0', '21', '4']

    # test_export_and_extract: both write their files and report skipped picks
    def test_export_and_extract(self, qtbot: QtBot, setup: Callable[[], tuple[ReviewTab, Session, EstimateService]]) -> None:
        tab, session, service = setup()
        pick = session.store.add(NAME, 'yellow', 4.0, 3.0, 2.0)
        qtbot.waitUntil(lambda: service.store.state(pick) == 'ok', timeout=5000)
        out = session.project.config.out_dir
        lines = tab.export_all()
        assert any(l.startswith('yellow: wrote 1 particles') for l in lines) and 'bad: nothing to export' in lines
        assert read_star_loop(out / 'relion' / 'yellow' / 'particles.star')[0]['rlnCenteredCoordinateXAngst'] == '0.00'
        lines = tab.extract_all()
        assert any(l.startswith('yellow: wrote 1 boxes of 4 px') for l in lines)
        assert (out / 'particles' / 'yellow' / NAME / f'{NAME}_000.mrc').exists()
        service.shutdown()
        session.store.add(NAME, 'yellow', 1.0, 1.0, 1.0)
        assert any('no current estimate' in l for l in tab.export_all())

    # test_crops: preview crops are cut around the pick
    def test_crops(self, qtbot: QtBot, setup: Callable[[], tuple[ReviewTab, Session, EstimateService]]) -> None:
        tab, _, _ = setup()
        xy, xz = tab.crops(NAME, (4.0, 3.0, 2.0))
        vol = np.arange(4 * 6 * 8, dtype=np.float32).reshape(4, 6, 8)
        assert np.array_equal(xy, vol[2]) and np.array_equal(xz, vol[:, 3, :])

    # test_double_click_opens: double-clicking a row asks to open the pick
    def test_double_click_opens(self, qtbot: QtBot, setup: Callable[[], tuple[ReviewTab, Session, EstimateService]]) -> None:
        tab, session, service = setup()
        pick = session.store.add(NAME, 'yellow', 4.0, 3.0, 2.0)
        tab.refresh()
        with qtbot.waitSignal(tab.open_pick) as blocker:
            tab._double_clicked(0, 0)
        assert blocker.args == [NAME, pick.id]
