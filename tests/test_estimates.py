'''
pickmix: tests for the estimate store and background service
'''

# Import external dependencies
import pytest, time
from collections.abc import Callable, Iterator
from pathlib import Path

# Import internal pickmix objects
from pickmix.config import Kind
from pickmix.estimate.registry import Fit
from pickmix.estimates import EstimateService, EstimateStore, effective_box_a
from pickmix.loader import Loader
from pickmix.model import Pick, Session
from pickmix.project import open_project

# NAME: the single tomogram of the fixture project
NAME: str = 'Position_1_2'

# _wait: poll until a condition holds
def _wait(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    end = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < end, 'timed out'
        time.sleep(0.01)

# service: a service over a project with a passthrough kind, a failing kind, and a session and loader that are shut down afterwards
@pytest.fixture
def service(make_config: Callable[..., Path]) -> Iterator[EstimateService]:
    project = open_project(make_config())
    project.update(kinds={'yellow': Kind(marker_a=100, box_a=100), 'bad': Kind(marker_a=50, box_a=50, estimator='missing')})
    session = Session(project)
    loader = Loader(project)
    svc = EstimateService(session, loader)
    yield svc
    svc.shutdown()
    loader.shutdown()

# TestEstimates: staleness, persistence and background running
class TestEstimates:
    # test_estimate_on_add: a new pick is estimated without being asked
    def test_estimate_on_add(self, service: EstimateService) -> None:
        pick = service.session.store.add(NAME, 'yellow', 3.0, 2.0, 1.0)
        _wait(lambda: service.store.state(pick) == 'ok')
        fit = service.store.get(pick)
        assert fit is not None and fit.box_a == 100 and (fit.x, fit.y, fit.z) == (3.0, 2.0, 1.0)

    # test_moved_pick_is_missing_then_refit: a moved pick has no fit until re-estimated, and the old row is dropped
    def test_moved_pick_is_missing_then_refit(self, service: EstimateService) -> None:
        pick = service.session.store.add(NAME, 'yellow', 3.0, 2.0, 1.0)
        _wait(lambda: service.store.state(pick) == 'ok')
        service.session.store.move(pick.id, 4.0, 2.0)
        _wait(lambda: service.store.state(pick) == 'ok')
        assert service.store.get(pick).x == 4.0
        assert len(service.store.path.read_text().splitlines()) == 2

    # test_settings_change_makes_stale: changing the kind invalidates its fits until they are recomputed
    def test_settings_change_makes_stale(self, service: EstimateService) -> None:
        pick = service.session.store.add(NAME, 'yellow', 3.0, 2.0, 1.0)
        _wait(lambda: service.store.state(pick) == 'ok')
        service.session.project.update(kinds={**service.session.project.config.kinds, 'yellow': Kind(marker_a=100, box_a=120)})
        assert service.store.state(pick) == 'stale' and service.store.get(pick) is None
        service.request(pick)
        _wait(lambda: service.store.state(pick) == 'ok')
        assert service.store.get(pick).box_a == 120

    # test_persists: a new store reads back current fits
    def test_persists(self, service: EstimateService) -> None:
        pick = service.session.store.add(NAME, 'yellow', 3.0, 2.0, 1.0)
        _wait(lambda: service.store.state(pick) == 'ok')
        assert EstimateStore(service.session.project, service.session.store).state(pick) == 'ok'

    # test_failure_is_flagged: an estimator that fails gives a flagged fit and a message, not a retry loop
    def test_failure_is_flagged(self, service: EstimateService) -> None:
        pick = service.session.store.add(NAME, 'bad', 3.0, 2.0, 1.0)
        _wait(lambda: service.store.state(pick) == 'ok')
        assert service.store.get(pick).flag == 'error'
        assert 'KeyError' in service.last_error

    # test_request_all_covers_other_tomograms: everything needing a fit is queued
    def test_request_all(self, service: EstimateService) -> None:
        pick = service.session.store.add(NAME, 'yellow', 3.0, 2.0, 1.0)
        _wait(lambda: service.pending == 0)
        service.store._rows.clear()
        assert service.store.state(pick) == 'missing'
        service.request_all()
        _wait(lambda: service.store.state(pick) == 'ok')

    # test_after_shutdown: requests do nothing
    def test_after_shutdown(self, service: EstimateService) -> None:
        service.shutdown()
        pick = service.session.store.add(NAME, 'yellow', 3.0, 2.0, 1.0)
        time.sleep(0.1)
        assert service.store.state(pick) == 'missing'

    # test_rename_kind_keeps_fits: a renamed kind keeps its fits instead of being estimated again
    def test_rename_kind_keeps_fits(self, service: EstimateService) -> None:
        pick = service.session.store.add(NAME, 'yellow', 3.0, 2.0, 1.0)
        _wait(lambda: service.store.state(pick) == 'ok')
        service.session.project.update(kinds={'gold': Kind(marker_a=100, box_a=100)})
        service.store.rename_kind('yellow', 'gold')
        service.session.store.rename_kind('yellow', 'gold')
        assert pick.kind == 'gold' and service.store.get(pick) is not None and service.pending == 0

    # test_order: pick's own box, then fit's, then kind's, then marker's
    def test_order(self) -> None:
        fit = Fit(x=0, y=0, z=0, radius_a=10, box_a=30.0, snr=1, z_lo=0, z_hi=0)
        own, plain = Pick(1, NAME, 'k', 0, 0, 0, box_a=45.0), Pick(2, NAME, 'k', 0, 0, 0)
        kind = Kind(marker_a=20, box_a=50.0)
        assert effective_box_a(own, kind, fit) == 45.0
        assert effective_box_a(plain, kind, fit) == 30.0
        assert effective_box_a(plain, kind, None) == 50.0
        assert effective_box_a(plain, Kind(marker_a=20), None) == 20.0
        assert effective_box_a(plain, Kind(marker_a=20), fit.model_copy(update={'box_a': 0.0})) == 20.0

    # test_store_get_applies_pick_box: stored fit comes back with pick's box edge, and stored row is unchanged
    def test_store_get_applies_pick_box(self, service: EstimateService) -> None:
        pick = service.session.store.add(NAME, 'yellow', 3.0, 2.0, 1.0, box_a=250.0)
        _wait(lambda: service.store.state(pick) == 'ok')
        assert service.store.get(pick).box_a == 250.0
        service.session.store.set_box(pick.id, None)
        assert service.store.get(pick).box_a == 100

    # test_order: pick's own box, then fit's, then kind's, then marker's
    def test_order(self) -> None:
        fit = Fit(x=0, y=0, z=0, radius_a=10, box_a=30.0, snr=1, z_lo=0, z_hi=0)
        own, plain = Pick(1, NAME, 'k', 0, 0, 0, box_a=45.0), Pick(2, NAME, 'k', 0, 0, 0)
        kind = Kind(marker_a=20, box_a=50.0)
        assert effective_box_a(own, kind, fit) == 45.0
        assert effective_box_a(plain, kind, fit) == 30.0
        assert effective_box_a(plain, kind, None) == 50.0
        assert effective_box_a(plain, Kind(marker_a=20), None) == 20.0
        assert effective_box_a(plain, Kind(marker_a=20), fit.model_copy(update={'box_a': 0.0})) == 20.0

    # test_store_get_applies_pick_box: stored fit gives pick's own box edge, and stored row is unchanged
    def test_store_get_applies_pick_box(self, service: EstimateService) -> None:
        pick = service.session.store.add(NAME, 'yellow', 3.0, 2.0, 1.0, box_a=250.0)
        _wait(lambda: service.store.state(pick) == 'ok')
        assert service.store.get(pick).box_a == 250.0
        service.session.store.set_box(pick.id, None)
        assert service.store.get(pick).box_a == 100
