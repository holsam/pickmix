'''
pickmix: tests for picks paired with their fits
'''

# Import external dependencies
import pytest
from collections.abc import Callable, Iterator
from pathlib import Path
from pytestqt.qtbot import QtBot

# Import internal pickmix objects
from pickmix.config import Kind
from pickmix.estimates import EstimateService
from pickmix.export import recommend_box
from pickmix.extract import box_pixels
from pickmix.items import flagged, items, matched
from pickmix.loader import Loader
from pickmix.model import Session
from pickmix.project import open_project

# NAME: the single tomogram of the fixture project
NAME: str = 'Position_1_2'

# parts: a session over a cage kind and a green kind whose parent is the cage, with its service, shut down afterwards
@pytest.fixture
def parts(make_config: Callable[..., Path]) -> Iterator[tuple[Session, EstimateService]]:
    project = open_project(make_config())
    project.update(kinds={'cage': Kind(marker_a=600, box_a=700), 'green': Kind(marker_a=40, box_a=200, parent='cage')})
    session, loader = Session(project), Loader(project)
    service = EstimateService(session, loader)
    yield session, service
    service.shutdown()
    loader.shutdown()

# TestItems: pick and fit helpers
class TestItems:
    # test_no_parent_kind: a kind without a parent matches nothing
    def test_no_parent_kind(self, parts: tuple[Session, EstimateService]) -> None:
        session, service = parts
        assert matched(session, service, 'cage') == {}

    # test_flagged_adds_lowcc: a pick validation scored low gets lowcc beside its other flags, and one it scored well does not
    def test_flagged_adds_lowcc(self, qtbot: QtBot, parts: tuple[Session, EstimateService]) -> None:
        session, service = parts
        a = session.store.add(NAME, 'cage', 10.0, 10.0, 10.0)
        b = session.store.add(NAME, 'cage', 20.0, 10.0, 10.0)
        qtbot.waitUntil(lambda: all(service.store.state(p) == 'ok' for p in session.store.all()), timeout=5000)
        assert all('lowcc' not in f.flag for _, f in items(session, service, 'cage'))
        service.validation.put_kind('cage', [(a, 0.1, True), (b, 0.6, False)])
        got = {p.id: f.flag for p, f in items(session, service, 'cage')}
        assert got[a.id] == 'lowcc' and got[b.id] == ''
        session.store.add(NAME, 'cage', 30.0, 10.0, 10.0)
        assert all('lowcc' not in f.flag for _, f in items(session, service, 'cage'))

    # test_flagged_adds_noparent: a pick with no parent in reach gets noparent, others do not
    def test_flagged_adds_noparent(self, qtbot: QtBot, parts: tuple[Session, EstimateService]) -> None:
        session, service = parts
        session.store.add(NAME, 'cage', 10.0, 10.0, 10.0)
        near = session.store.add(NAME, 'green', 10.0 + 56.0, 10.0, 10.0)
        far = session.store.add(NAME, 'green', 10.0 + 20.0, 10.0, 10.0)
        qtbot.waitUntil(lambda: all(service.store.state(p) == 'ok' for p in session.store.all()), timeout=5000)
        got = {p.id: f.flag for p, f in items(session, service, 'green')}
        assert 'noparent' not in got[near.id] and 'noparent' in got[far.id]
        assert flagged(session, 'green', far, service.store.get(far), matched(session, service, 'green')).flag.endswith('noparent')

    # test_items_skip_missing_fits: a pick with no current fit is left out
    def test_items_skip_missing_fits(self, parts: tuple[Session, EstimateService]) -> None:
        session, service = parts
        service.shutdown()
        session.store.add(NAME, 'cage', 10.0, 10.0, 10.0)
        assert items(session, service, 'cage') == []

    # test_own_boxes_reach_export_and_extraction: a kind with no box of its own takes its box from the picks' boxes, at the 95th percentile
    def test_own_boxes_reach_export_and_extraction(self, qtbot: QtBot, parts: tuple[Session, EstimateService]) -> None:
        session, service = parts
        session.project.update(kinds={'tube': Kind(marker_a=100, pick_mode='bounds', extract_angpix=5.36)})
        for i, box in enumerate((100.0, 200.0, 300.0)):
            session.store.add(NAME, 'tube', 1.0 + i, 2.0, 1.0, box_a=box)
        qtbot.waitUntil(lambda: all(service.store.state(p) == 'ok' for p in session.store.all()), timeout=5000)
        got = items(session, service, 'tube')
        assert sorted(f.box_a for _, f in got) == [100.0, 200.0, 300.0]
        box_a, box_px = recommend_box(session.project.config.kinds['tube'], got)
        assert abs(box_a - 290.0) < 1e-6 and box_px % 2 == 0
        # extraction cuts at the tomogram's own sampling and rounds to the nearest even edge
        assert box_pixels(session.project.config.kinds['tube'], got, session.project.tomos[NAME].pixel_size) == 54
