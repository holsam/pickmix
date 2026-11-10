'''
pickmix: tests for schemas
'''

# Import external dependencies
from collections.abc import Callable
from pathlib import Path

# Import internal pickmix objects
from pickmix.model import PickStore, Session
from pickmix.project import open_project

# _store: a store over a fresh project
def _store(make_config: Callable[..., Path]) -> PickStore:
    return PickStore(open_project(make_config()))

# THREE: three tomograms for navigation tests
THREE: tuple[str, ...] = ('Position_1_2', 'Position_1_3', 'Other_9')

# TestModel: pick store/tomogram navigation/progress schema
class TestModel:
    # test_add_move_remove: edits are reflected in queries and listeners hear each one
    def test_add_move_remove(self, make_config: Callable[..., Path]) -> None:
        store = _store(make_config)
        heard: list[int] = []
        store.listeners.append(lambda: heard.append(1))
        a = store.add('Position_1_2', 'cage', 1.0, 2.0, 3.0)
        b = store.add('Position_1_2', 'yellow', 4.0, 5.0, 6.0)
        assert store.count('Position_1_2') == 2 and store.count('Position_1_2', 'cage') == 1
        store.move(a.id, 10.0, 20.0)
        assert (store.get(a.id).x, store.get(a.id).y, store.get(a.id).z) == (10.0, 20.0, 3.0)
        store.remove(b.id)
        assert store.total() == 1 and store.total('yellow') == 0
        assert len(heard) == 4

    # test_autosave_reload: a new store reads back what the last edit saved
    def test_autosave_reload(self, make_config: Callable[..., Path]) -> None:
        path = make_config()
        store = PickStore(open_project(path))
        store.add('Position_1_2', 'yellow', 1.5, 2.5, 3.5)
        again = PickStore(open_project(path))
        [pick] = again.all()
        assert (pick.tomogram, pick.kind, pick.x, pick.y, pick.z) == ('Position_1_2', 'yellow', 1.5, 2.5, 3.5)

    # test_cave_csv: a CaVe file with no kind column reads as cages
    def test_cave_csv(self, make_config: Callable[..., Path]) -> None:
        project = open_project(make_config())
        out = project.config.out_dir
        out.mkdir(parents=True)
        (out / 'picks.csv').write_text('tomogram,x,y,z,pixel_size_a\nPosition_1_2,1.0,2.0,3.0,5.36\n')
        [pick] = PickStore(project).all()
        assert pick.kind == 'cage'

    # test_unknown_kind_kept: a pick of a kind not in the config survives a save
    def test_unknown_kind_kept(self, make_config: Callable[..., Path]) -> None:
        project = open_project(make_config())
        out = project.config.out_dir
        out.mkdir(parents=True)
        (out / 'picks.csv').write_text('tomogram,kind,x,y,z,pixel_size_a\nPosition_1_2,gone,1.0,2.0,3.0,5.36\n')
        store = PickStore(project)
        store.add('Position_1_2', 'cage', 0.0, 0.0, 0.0)
        assert sorted(p.kind for p in PickStore(project).all()) == ['cage', 'gone']

    # test_box_round_trip: a pick's own box edge survives a save, and picks without one stay without
    def test_box_round_trip(self, make_config: Callable[..., Path]) -> None:
        path = make_config()
        store = PickStore(open_project(path))
        store.add('Position_1_2', 'cage', 1.0, 2.0, 3.0, box_a=412.5)
        store.add('Position_1_2', 'cage', 4.0, 5.0, 6.0)
        assert [p.box_a for p in PickStore(open_project(path)).all()] == [412.5, None]

    # test_old_csv_has_no_box: a picks.csv written before boxes existed loads with none
    def test_old_csv_has_no_box(self, make_config: Callable[..., Path]) -> None:
        project = open_project(make_config())
        out = project.config.out_dir
        out.mkdir(parents=True)
        (out / 'picks.csv').write_text('tomogram,kind,x,y,z,pixel_size_a\nPosition_1_2,cage,1.0,2.0,3.0,5.36\n')
        [pick] = PickStore(project).all()
        assert pick.box_a is None

    # test_set_box_and_move: set_box edits the box and notifies; moving a pick keeps its box
    def test_set_box_and_move(self, make_config: Callable[..., Path]) -> None:
        store = _store(make_config)
        heard: list[int] = []
        pick = store.add('Position_1_2', 'cage', 1.0, 2.0, 3.0)
        store.listeners.append(lambda: heard.append(1))
        store.set_box(pick.id, 300.0)
        store.move(pick.id, 5.0, 6.0)
        assert store.get(pick.id).box_a == 300.0 and len(heard) == 2
        store.set_box(pick.id, None)
        assert store.get(pick.id).box_a is None

    # test_navigation_clamps: stepping stops at both ends
    def test_navigation_clamps(self, make_config: Callable[..., Path]) -> None:
        session = Session(open_project(make_config(names=THREE)))
        assert session.names == ['Position_1_2', 'Position_1_3', 'Other_9']
        session.step(-1)
        assert session.index == 0
        session.step(1)
        session.step(1)
        session.step(1)
        assert session.index == 2

    # test_jump: number, exact name, then first containing the text
    def test_jump(self, make_config: Callable[..., Path]) -> None:
        session = Session(open_project(make_config(names=THREE)))
        assert session.jump('3') and session.current == 'Other_9'
        assert session.jump('position_1_2') and session.current == 'Position_1_2'
        assert session.jump('1_3') and session.current == 'Position_1_3'
        assert session.jump('position') and session.current == 'Position_1_2'
        assert not session.jump('9x') and not session.jump('0') and not session.jump('4') and not session.jump('')
        assert session.current == 'Position_1_2'

    # test_resume: a new session opens at the last tomogram and remembers the visited ones
    def test_resume(self, make_config: Callable[..., Path]) -> None:
        path = make_config(names=THREE)
        session = Session(open_project(path))
        session.go(2)
        again = Session(open_project(path))
        assert again.current == 'Other_9'
        assert again.visited == {'Position_1_2', 'Other_9'}

    # test_rows_and_counts: the list marks current and visited and counts picks
    def test_rows_and_counts(self, make_config: Callable[..., Path]) -> None:
        session = Session(open_project(make_config(names=THREE)))
        session.store.add('Position_1_3', 'cage', 1.0, 1.0, 1.0)
        session.go(1)
        rows = session.rows()
        assert [(r.name, r.count, r.current, r.visited) for r in rows] == [
            ('Position_1_2', 0, False, True), ('Position_1_3', 1, True, True), ('Other_9', 0, False, False),
        ]

    # test_goto_listener: listeners hear navigation
    def test_goto_listener(self, make_config: Callable[..., Path]) -> None:
        session = Session(open_project(make_config(names=THREE)))
        heard: list[str] = []
        session.goto_listeners.append(lambda: heard.append(session.current))
        session.step(1)
        assert heard == ['Position_1_3']

    # test_rename_kind: every pick of a kind moves to the new name, is saved once and is heard once
    def test_rename_kind(self, make_config: Callable[..., Path]) -> None:
        store = _store(make_config)
        store.add('Position_1_2', 'cage', 1.0, 1.0, 1.0)
        store.add('Position_1_2', 'cage', 2.0, 1.0, 1.0)
        store.add('Position_1_2', 'other', 3.0, 1.0, 1.0)
        heard: list[int] = []
        store.listeners.append(lambda: heard.append(1))
        assert store.rename_kind('cage', 'ring') == 2 and store.rename_kind('nothing', 'x') == 0
        assert [p.kind for p in store.all()] == ['ring', 'ring', 'other'] and heard == [1]
        assert sorted(p.kind for p in PickStore(store.project).all()) == ['other', 'ring', 'ring']

    # test_remove_kind: every pick of a kind goes, the rest stay, and the file follows
    def test_remove_kind(self, make_config: Callable[..., Path]) -> None:
        store = _store(make_config)
        store.add('Position_1_2', 'cage', 1.0, 1.0, 1.0)
        store.add('Position_1_2', 'other', 3.0, 1.0, 1.0)
        assert store.remove_kind('cage') == 1 and store.remove_kind('cage') == 0
        assert [p.kind for p in PickStore(store.project).all()] == ['other']

    # test_find: a number or name finds a tomogram's index without moving to it
    def test_find(self, make_config) -> None:
        from pickmix.model import Session
        from pickmix.project import open_project
        session = Session(open_project(make_config(names=('Position_1_2', 'Position_1_3', 'Other_9'))))
        assert session.find('2') == 1 and session.find('other') == 2 and session.find('Position_1_3') == 1
        assert session.find('position') == 0 and session.find('zzz') is None and session.find('') is None and session.find('9') is None
        assert session.index == 0 and session.jump('3') and session.index == 2
