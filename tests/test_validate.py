'''
pickmix: tests for running kind validation
'''

# Import external dependencies
import numpy as np, pytest
from collections.abc import Callable, Iterator
from pathlib import Path
from pytestqt.qtbot import QtBot

# Import internal pickmix objects
from pickmix.config import Kind
from pickmix.estimates import EstimateService, _key
from pickmix.items import items
from pickmix.loader import Loader
from pickmix.model import Session
from pickmix.project import open_project
from pickmix.validate import validate_kind

# NAME: the single tomogram of the fixture project
NAME: str = 'Position_1_2'

# SIZE: edge in pixels of the crafted box images
SIZE: int = 24

# parts: a session over a yellow kind, with its service, shut down afterwards
@pytest.fixture
def parts(make_config: Callable[..., Path]) -> Iterator[tuple[Session, EstimateService]]:
    project = open_project(make_config())
    project.update(kinds={'yellow': Kind(marker_a=100, box_a=100)})
    session, loader = Session(project), Loader(project)
    service = EstimateService(session, loader)
    yield session, service
    service.shutdown()
    loader.shutdown()

# _picks: n picks of kind yellow in the one tomogram, waited for until every one has a current fit
def _picks(qtbot: QtBot, session: Session, service: EstimateService, n: int) -> None:
    for i in range(n):
        session.store.add(NAME, 'yellow', float(i % 8), float(i % 6), float(i % 4))
    qtbot.waitUntil(lambda: all(service.store.state(p) == 'ok' for p in session.store.all()), timeout=5000)

# _crafted: box_images standing in for the real one: n images of a gaussian blob with noise, the last `bad` of them noise only
def _crafted(n: int, bad: int) -> Callable[..., tuple[list, int]]:
    def box_images(name: str, kind: Kind, got: list, tomos: dict, config: object, *, log: Callable[[str], None] = lambda _: None) -> tuple[list, int]:
        rng = np.random.default_rng(8)
        yy, xx = np.mgrid[:SIZE, :SIZE]
        blob = np.exp(-0.5 * (np.hypot(yy - SIZE // 2, xx - SIZE // 2) / 3.0) ** 2)
        out = []
        for i, (pick, _) in enumerate(got):
            img = rng.normal(0.0, 1.0, (SIZE, SIZE)) if i >= n - bad else blob + rng.normal(0.0, 0.3, (SIZE, SIZE))
            out.append((pick, ((img - img.mean()) / img.std()).astype(np.float32)))
        return out, SIZE
    return box_images

# TestValidate: validating a kind
class TestValidate:
    # test_scores_stored_and_flagged: outliers among the images are flagged lowcc in the items, and every scored pick has a current score
    def test_scores_stored_and_flagged(self, qtbot: QtBot, parts: tuple[Session, EstimateService], monkeypatch: pytest.MonkeyPatch) -> None:
        session, service = parts
        _picks(qtbot, session, service, 20)
        monkeypatch.setattr('pickmix.validate.box_images', _crafted(20, 2))
        summary = validate_kind('yellow', session, service)
        assert (summary.scored, summary.flagged, summary.skipped) == (20, 2, 0) and 0.0 < summary.median < 1.0
        assert all(service.validation.state(p) == 'ok' for p in session.store.all())
        flagged = [p.id for p, f in items(session, service, 'yellow') if 'lowcc' in f.flag]
        assert len(flagged) == 2 and flagged == [p.id for p in session.store.all()][-2:]

    # test_runs_on_real_boxes: with nothing mocked, boxes are cut from the tomogram and every pick gets a score
    def test_runs_on_real_boxes(self, qtbot: QtBot, parts: tuple[Session, EstimateService]) -> None:
        session, service = parts
        _picks(qtbot, session, service, 12)
        summary = validate_kind('yellow', session, service)
        assert summary.scored == 12
        assert all(np.isfinite(service.validation.score(p)) for p in session.store.all())

    # test_too_few_picks_says_which_kind: fewer picks than the setting is a ValueError naming the kind
    def test_too_few_picks_says_which_kind(self, qtbot: QtBot, parts: tuple[Session, EstimateService]) -> None:
        session, service = parts
        _picks(qtbot, session, service, 5)
        with pytest.raises(ValueError, match="kind 'yellow': needs at least 10 picks to validate, has 5"):
            validate_kind('yellow', session, service)

    # test_picks_without_fit_skipped: a pick with no current fit has no box to cut, is counted as skipped and gets no score
    def test_picks_without_fit_skipped(self, qtbot: QtBot, parts: tuple[Session, EstimateService], monkeypatch: pytest.MonkeyPatch) -> None:
        session, service = parts
        _picks(qtbot, session, service, 14)
        service.shutdown()
        lost = session.store.all()[:2]
        for p in lost:
            service.store._rows.pop(_key(p.tomogram, p.kind, p.x, p.y, p.z))
        monkeypatch.setattr('pickmix.validate.box_images', _crafted(12, 0))
        summary = validate_kind('yellow', session, service)
        assert (summary.scored, summary.skipped) == (12, 2)
        assert all(service.validation.score(p) is None for p in lost)
