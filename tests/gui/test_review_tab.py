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
