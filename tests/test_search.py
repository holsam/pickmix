'''
pickmix: tests for candidate search and command line
'''

# Import external dependencies
import pytest

# Import internal pickmix objects
from pickmix.candidates import CandidateStore
from pickmix.model import Session
from pickmix.project import open_project
from pickmix.search import search
from test_matcher import blobs  # noqa: F401, fixture

class TestSearch:
    # test_finds_blobs_without_touching_progress: picks in A give candidates at planted blobs of B, and search does not mark anything visited
    def test_finds_blobs_without_touching_progress(self, blobs: tuple[Session, dict]) -> None:
        session, planted = blobs
        for x, y, z in planted['A']:
            session.store.add('A', 'blob', x, y, z)
        config_path = session.project.path
        before = session.progress_path.read_text()
        result = search(config_path, workers=2)
        assert result.failed == {} and result.unusable == {} and result.total == 1
        assert result.kinds['blob'].tomograms == 1 and result.kinds['blob'].candidates >= 2
        assert session.progress_path.read_text() == before
        found = CandidateStore(open_project(config_path)).candidates('B', 'blob', min_score=0.3)
        assert len(found) == 2
        for x, y, z in planted['B']:
            assert any(max(abs(c.x - x), abs(c.y - y), abs(c.z - z)) <= 2 for c in found)

    # test_kind_without_picks_is_unusable: a kind with no picks is reported and nothing is scanned
    def test_kind_without_picks_is_unusable(self, blobs: tuple[Session, dict]) -> None:
        session, _ = blobs
        result = search(session.project.path)
        assert 'nothing to build a template from' in result.unusable['blob'] and result.kinds == {}

    # test_unknown_kind: a kind the project lacks is an error
    def test_unknown_kind(self, blobs: tuple[Session, dict]) -> None:
        with pytest.raises(ValueError, match='unknown kinds'):
            search(blobs[0].project.path, kinds=['nope'])
