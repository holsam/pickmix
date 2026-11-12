'''
pickmix: tests for the candidate store
'''

# Import external dependencies
from collections.abc import Callable
from pathlib import Path

# Import internal pickmix objects
from pickmix.candidates import CandidateStore
from pickmix.candidates import Hit
from pickmix.model import Session
from pickmix.project import open_project

# NAME: the single tomogram of the fixture project
NAME: str = 'Position_1_2'

# THREE: three tomograms for navigation tests
THREE: tuple[str, ...] = ('Position_1_2', 'Position_1_3', 'Other_9')

# _store: a store over a fresh project
def _store(make_config: Callable[..., Path]) -> CandidateStore:
    return CandidateStore(open_project(make_config()))

class TestCandidates:
    # test_replace_and_query: candidates come back best first, filtered by kind and score
    def test_replace_and_query(self, make_config: Callable[..., Path]) -> None:
        store = _store(make_config)
        heard: list[int] = []
        store.listeners.append(lambda: heard.append(1))
        store.replace(NAME, 'cage', [Hit(1, 1, 1, 0.3), Hit(5, 5, 1, 0.6)], reach=2)
        assert [c.score for c in store.candidates(NAME)] == [0.6, 0.3] and heard == [1]
        assert [c.score for c in store.candidates(NAME, min_score=0.5)] == [0.6]
        assert store.candidates(NAME, 'other') == [] and store.count('cage') == 2 and store.count('cage', NAME, min_score=0.5) == 1

    # test_replace_without_persist: a bulk replace changes nothing on disk until the caller saves
    def test_replace_without_persist(self, make_config: Callable[..., Path]) -> None:
        store = _store(make_config)
        heard: list[int] = []
        store.listeners.append(lambda: heard.append(1))
        store.replace(NAME, 'cage', [Hit(1, 1, 1, 0.3)], reach=2, persist=False)
        assert store.count('cage') == 1 and heard == [] and not store.path.exists()
        store.save()
        assert CandidateStore(store.project).count('cage') == 1

    # test_replace_swaps_old_for_new: a new scan replaces the old candidates of that kind and tomogram only
    def test_replace_swaps_old_for_new(self, make_config: Callable[..., Path]) -> None:
        store = _store(make_config)
        store.replace(NAME, 'cage', [Hit(1, 1, 1, 0.3)], reach=2)
        store.replace(NAME, 'yellow', [Hit(2, 2, 2, 0.4)], reach=2)
        store.replace(NAME, 'cage', [Hit(7, 7, 1, 0.5)], reach=2)
        assert [(c.kind, c.x) for c in store.candidates(NAME)] == [('cage', 7), ('yellow', 2)] or {(c.kind, c.x) for c in store.candidates(NAME)} == {('cage', 7), ('yellow', 2)}

    # test_reject_is_remembered: a rejected candidate is hidden and a later scan does not offer its place again
    def test_reject_is_remembered(self, make_config: Callable[..., Path]) -> None:
        store = _store(make_config)
        store.replace(NAME, 'cage', [Hit(1, 1, 1, 0.3), Hit(6, 6, 1, 0.4)], reach=2)
        first = store.candidates(NAME)[1]
        store.reject(first.id)
        assert [c.x for c in store.candidates(NAME)] == [6]
        store.replace(NAME, 'cage', [Hit(1.5, 1, 1, 0.35), Hit(6, 6, 1, 0.4)], reach=2)
        assert [c.x for c in store.candidates(NAME)] == [6]

    # test_save_and_load: candidates, with rejected ones, survive a restart
    def test_save_and_load(self, make_config: Callable[..., Path]) -> None:
        store = _store(make_config)
        store.replace(NAME, 'cage', [Hit(1, 1, 1, 0.3), Hit(6, 6, 1, 0.4)], reach=2)
        store.reject(store.candidates(NAME)[0].id)
        again = CandidateStore(store.project)
        assert [(c.x, c.score) for c in again.candidates(NAME)] == [(1, 0.3)]
        assert again.count('cage') == 1 and sum(c.status == 'rejected' for c in again._items.values()) == 1

    # test_rename_remove_clear: kind renames follow, kinds can be dropped and everything can be cleared
    def test_rename_remove_clear(self, make_config: Callable[..., Path]) -> None:
        store = _store(make_config)
        store.replace(NAME, 'cage', [Hit(1, 1, 1, 0.3)], reach=2)
        store.replace(NAME, 'yellow', [Hit(2, 2, 2, 0.4)], reach=2)
        store.rename_kind('cage', 'big')
        assert store.count('big') == 1 and store.count('cage') == 0
        store.remove_kind('big')
        assert store.count('big') == 0 and store.count('yellow') == 1
        store.clear()
        assert store.count('yellow') == 0

    # test_accept_makes_picks: accepted candidates become picks of their kind and leave the store
    def test_accept_makes_picks(self, make_config: Callable[..., Path]) -> None:
        session = Session(open_project(make_config()))
        session.candidates.replace(NAME, 'cage', [Hit(1, 2, 3, 0.5)], reach=2)
        (candidate,) = session.candidates.candidates(NAME)
        (pick,) = session.accept(candidate.id)
        assert (pick.tomogram, pick.kind, pick.x, pick.y, pick.z) == (NAME, 'cage', 1, 2, 3)
        assert session.candidates.count('cage') == 0 and session.store.total('cage') == 1

    # test_accept_skips_unknown_kind: a candidate whose kind has gone is dropped, not turned into a pick
    def test_accept_skips_unknown_kind(self, make_config: Callable[..., Path]) -> None:
        session = Session(open_project(make_config()))
        session.candidates.replace(NAME, 'gone', [Hit(1, 2, 3, 0.5)], reach=2)
        assert session.accept(session.candidates.candidates(NAME)[0].id) == [] and session.store.total() == 0

    # test_prune: every candidate in the given tomograms goes, rejected ones too, and listeners hear it once
    def test_prune(self, make_config: Callable[..., Path]) -> None:
        store = CandidateStore(open_project(make_config(names=THREE)))
        store.replace(THREE[0], 'cage', [Hit(1, 1, 1, 0.3), Hit(6, 6, 1, 0.4)], reach=2)
        store.reject(store.candidates(THREE[0])[0].id)
        store.replace(THREE[1], 'cage', [Hit(2, 2, 2, 0.5)], reach=2)
        heard: list[int] = []
        store.listeners.append(lambda: heard.append(1))
        store.prune([THREE[0]])
        store.prune([THREE[2]])
        assert store.candidates(THREE[0]) == [] and store.count('cage') == 1 and heard == [1]
        assert len(CandidateStore(store.project)._items) == 1

    # test_leaving_a_tomogram_prunes_it: moving on forgets the candidates of the tomogram left, and keeps the others
    def test_leaving_a_tomogram_prunes_it(self, make_config: Callable[..., Path]) -> None:
        session = Session(open_project(make_config(names=THREE)))
        session.candidates.replace(THREE[0], 'cage', [Hit(1, 1, 1, 0.3)], reach=2)
        session.candidates.replace(THREE[1], 'cage', [Hit(2, 2, 2, 0.5)], reach=2)
        session.go(1)
        assert session.candidates.candidates(THREE[0]) == [] and len(session.candidates.candidates(THREE[1])) == 1
        session.go(1)
        assert len(session.candidates.candidates(THREE[1])) == 1

    # test_visited_pruned_on_start: reopening a project forgets candidates of visited tomograms except the one resumed at
    def test_visited_pruned_on_start(self, make_config: Callable[..., Path]) -> None:
        project = open_project(make_config(names=THREE))
        first = Session(project)
        first.go(1)
        first.candidates.replace(THREE[0], 'cage', [Hit(1, 1, 1, 0.3)], reach=2)
        first.candidates.replace(THREE[1], 'cage', [Hit(2, 2, 2, 0.5)], reach=2)
        first.candidates.replace(THREE[2], 'cage', [Hit(3, 3, 3, 0.6)], reach=2)
        again = Session(project)
        assert again.current == THREE[1]
        assert [c.tomogram for c in again.candidates._items.values()] == [THREE[1], THREE[2]]
