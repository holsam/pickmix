'''
pickmix: tests for the Kinds tab
'''

# Import external dependencies
from collections.abc import Callable
from pathlib import Path
from pytestqt.qtbot import QtBot

# Import internal pickmix objects
from pickmix.config import Kind, load_config
from pickmix.gui.dialogs.kind_dialog import DELETED, KindDialog
from pickmix.gui.tabs.kinds_tab import KindsTab
from pickmix.model import PickStore, Session
from pickmix.project import open_project

# _tab: a Kinds tab showing a fresh project; returns the tab and the config path
def _tab(qtbot: QtBot, make_config: Callable[..., Path]) -> tuple[KindsTab, Path]:
    path = make_config()
    tab = KindsTab()
    qtbot.addWidget(tab)
    tab.set_project(open_project(path))
    return tab, path

# _tab_with_picks: a tab with cage, green (child of cage) and yellow kinds, a session, and picks of every kind
def _tab_with_picks(qtbot: QtBot, make_config: Callable[..., Path]) -> tuple[KindsTab, Path, Session]:
    path = make_config()
    project = open_project(path)
    project.update(kinds={
        'cage': Kind(marker_a=600, box_a=700), 'green': Kind(marker_a=40, box_a=200, parent='cage'), 'yellow': Kind(marker_a=100, box_a=100),
    })
    session = Session(project)
    for kind in ('cage', 'cage', 'green', 'yellow'):
        session.store.add('Position_1_2', kind, 1.0, 1.0, 1.0)
    tab = KindsTab()
    qtbot.addWidget(tab)
    tab.set_project(project)
    tab.set_session(session, None)
    return tab, path, session

# TestKindsTab: kinds tab
class TestKindsTab:
    # test_lists_kinds: each kind is listed with its values as plain text and an edit button
    def test_lists_kinds(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        tab, _ = _tab(qtbot, make_config)
        assert tab.kind_names() == ['cage'] and 'cage' in tab.edit_buttons
        text = tab.details['cage'].text()
        assert '<b>Marker:</b> 600 Å' in text and '<b>Box:</b> from estimator' in text and '<b>Estimator:</b> ring' in text and '<b>Parent:</b> none' in text

    # test_hotkey_defaults: keys start on the kinds in order, the rest are unused
    def test_hotkey_defaults(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        tab, _ = _tab(qtbot, make_config)
        assert [b.currentText() for b in tab.hotkey_boxes] == ['cage', *['(none)'] * 8]
        assert tab.hotkey_boxes[1].itemText(0) == '(none)' and tab.hotkey_boxes[1].count() == 2

    # test_hotkey_change_saves: choosing a kind for a key saves it and moves the kind off its old key
    def test_hotkey_change_saves(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        tab, path = _tab(qtbot, make_config)
        with qtbot.waitSignal(tab.config_saved):
            tab.hotkey_boxes[2].setCurrentText('cage')
        assert load_config(path).hotkeys == ['', '', 'cage', *[''] * 6]
        assert tab.hotkey_boxes[0].currentText() == '(none)'

    # test_add_kind: a new kind is saved after the others and takes the first free key
    def test_add_kind(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        tab, path = _tab(qtbot, make_config)
        with qtbot.waitSignal(tab.config_saved):
            tab._apply('yellow', Kind(marker_a=100, box_a=100))
        config = load_config(path)
        assert list(config.kinds) == ['cage', 'yellow'] and config.hotkeys[:3] == ['cage', 'yellow', '']
        assert tab.kind_names() == ['cage', 'yellow'] and tab.hotkey_boxes[1].currentText() == 'yellow'

    # test_edit_kind: the edit button opens the dialog on that kind and OK saves the changes
    def test_edit_kind(self, qtbot: QtBot, make_config: Callable[..., Path], monkeypatch) -> None:
        tab, path = _tab(qtbot, make_config)

        # fake_exec: change the marker size and accept
        def fake_exec(dialog: KindDialog) -> int:
            assert not dialog.adding and dialog.name_edit.text() == 'cage'
            dialog.marker_spin.setValue(700)
            return 1

        monkeypatch.setattr(KindDialog, 'exec', fake_exec)
        tab.edit_buttons['cage'].click()
        assert load_config(path).kinds['cage'].marker_a == 700
        assert '<b>Marker:</b> 700 Å' in tab.details['cage'].text()

    # test_cancel_changes_nothing: a cancelled dialog leaves the file alone
    def test_cancel_changes_nothing(self, qtbot: QtBot, make_config: Callable[..., Path], monkeypatch) -> None:
        tab, path = _tab(qtbot, make_config)
        before = path.read_text()
        monkeypatch.setattr(KindDialog, 'exec', lambda dialog: 0)
        tab.add_button.click()
        assert path.read_text() == before

    # test_dialog_check: the dialog refuses a duplicate name and a passthrough with no box before anything is saved
    def test_dialog_check(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        tab, _ = _tab(qtbot, make_config)
        assert tab._problem('cage2', Kind(marker_a=10, box_a=0, estimator='none'), None) is not None
        assert tab._problem('cage2', Kind(marker_a=10, box_a=10, parent='missing'), None) is not None
        assert tab._problem('cage2', Kind(marker_a=10, box_a=10), None) is None

    # test_delete_kind: deleting removes the kind and frees its key
    def test_delete_kind(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        tab, path = _tab(qtbot, make_config)
        tab._apply('yellow', Kind(marker_a=100, box_a=100))
        tab._delete('yellow')
        config = load_config(path)
        assert list(config.kinds) == ['cage'] and config.hotkeys == ['cage', *[''] * 8]

    # test_delete_blocked: a kind that is another's parent is not deleted, and says why
    def test_delete_blocked(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        tab, path = _tab(qtbot, make_config)
        tab._apply('green', Kind(marker_a=40, box_a=200, parent='cage'))
        before = path.read_text()
        tab._delete('cage')
        assert tab.status.text().startswith('Not deleted') and path.read_text() == before

    # test_delete_only_kind: the last kind can be deleted, leaving an empty list and unused keys
    def test_delete_only_kind(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        tab, path = _tab(qtbot, make_config)
        tab._delete('cage')
        config = load_config(path)
        assert config.kinds == {} and config.hotkeys == [''] * 9
        assert tab.kind_names() == [] and [b.currentText() for b in tab.hotkey_boxes] == ['(none)'] * 9
        tab._apply('yellow', Kind(marker_a=100, box_a=100))
        assert list(load_config(path).kinds) == ['yellow'] and tab.hotkey_boxes[0].currentText() == 'yellow'

    # test_rename_follows: a rename keeps the kind's place, hotkey, children and picks, in memory and in picks.csv
    def test_rename_follows(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        tab, path, session = _tab_with_picks(qtbot, make_config)
        tab._apply('gold', Kind(marker_a=600, box_a=700), old='cage')
        config = load_config(path)
        assert list(config.kinds) == ['gold', 'green', 'yellow'] and config.kinds['green'].parent == 'gold'
        assert config.hotkeys[:3] == ['gold', 'green', 'yellow']
        assert [p.kind for p in session.store.all()] == ['gold', 'gold', 'green', 'yellow']
        assert sorted(p.kind for p in PickStore(session.project).all()) == ['gold', 'gold', 'green', 'yellow']
        assert tab.kind_names() == ['gold', 'green', 'yellow']

    # test_edit_without_rename_keeps_picks: editing values only leaves the picks alone
    def test_edit_without_rename_keeps_picks(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        tab, path, session = _tab_with_picks(qtbot, make_config)
        tab._apply('cage', Kind(marker_a=650, box_a=700), old='cage')
        assert load_config(path).kinds['cage'].marker_a == 650 and session.store.total('cage') == 2

    # test_rename_to_existing_refused: a kind cannot take another kind's name
    def test_rename_to_existing_refused(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        tab, _, _ = _tab_with_picks(qtbot, make_config)
        assert 'already exists' in tab._problem('green', Kind(marker_a=600, box_a=700), 'cage')

    # test_delete_with_picks_asks: picks of the kind go with it after a yes, and stay with a no
    def test_delete_with_picks_asks(self, qtbot: QtBot, make_config: Callable[..., Path], monkeypatch) -> None:
        tab, path, session = _tab_with_picks(qtbot, make_config)
        asked: list[str] = []
        monkeypatch.setattr(KindsTab, '_confirm', lambda self, text: asked.append(text) or False)
        tab._delete('yellow')
        assert 'yellow' in asked[0] and '1 picks' in asked[0] and 'yellow' in load_config(path).kinds and session.store.total('yellow') == 1
        monkeypatch.setattr(KindsTab, '_confirm', lambda self, text: True)
        tab._delete('yellow')
        assert 'yellow' not in load_config(path).kinds and session.store.total('yellow') == 0
        assert sorted(p.kind for p in PickStore(session.project).all()) == ['cage', 'cage', 'green']

    # test_delete_without_picks_does_not_ask: an empty kind is deleted without a question
    def test_delete_without_picks_does_not_ask(self, qtbot: QtBot, make_config: Callable[..., Path], monkeypatch) -> None:
        tab, path, session = _tab_with_picks(qtbot, make_config)
        session.store.remove_kind('yellow')

        # fail: asking is a bug here
        def fail(self: KindsTab, text: str) -> bool:
            raise AssertionError(text)

        monkeypatch.setattr(KindsTab, '_confirm', fail)
        tab._delete('yellow')
        assert 'yellow' not in load_config(path).kinds

    # test_refused_delete_keeps_picks: a delete the config refuses neither asks nor touches the picks
    def test_refused_delete_keeps_picks(self, qtbot: QtBot, make_config: Callable[..., Path], monkeypatch) -> None:
        tab, path, session = _tab_with_picks(qtbot, make_config)
        monkeypatch.setattr(KindsTab, '_confirm', lambda self, text: (_ for _ in ()).throw(AssertionError(text)))
        tab._delete('cage')
        assert tab.status.text().startswith('Not deleted') and session.store.total('cage') == 2

    # test_details_are_a_vertical_list_with_bold_keys: one key per line, each key bold
    def test_details_are_a_vertical_list_with_bold_keys(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        tab, _ = _tab(qtbot, make_config)
        lines = tab.details['cage'].text().split('<br>')
        assert len(lines) == 7 and all(line.startswith('<b>') and ':</b> ' in line for line in lines)

    # test_kinds_flow_into_columns: a wide block gives one column, a narrow one gives several, filling across then down
    def test_kinds_flow_into_columns(self, qtbot: QtBot, make_config: Callable[..., Path], monkeypatch) -> None:
        tab, _, _ = _tab_with_picks(qtbot, make_config)
        tab.resize(900, 600)
        tab.show()
        position = lambda i: tab.grid.getItemPosition(tab.grid.indexOf(tab.cards[i]))[:2]
        monkeypatch.setattr('pickmix.gui.tabs.kinds_tab._CARD_WIDTH', 10000)
        tab._columns = 0
        tab._reflow()
        assert tab._columns == 1 and [position(i) for i in range(3)] == [(0, 0), (1, 0), (2, 0)]
        monkeypatch.setattr('pickmix.gui.tabs.kinds_tab._CARD_WIDTH', 100)
        tab._reflow()
        assert tab._columns >= 3 and [position(i) for i in range(3)] == [(0, 0), (0, 1), (0, 2)]

    # test_add_button_is_on_the_right: the Add button sits after the heading's stretch
    def test_add_button_is_on_the_right(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        tab, _ = _tab(qtbot, make_config)
        tab.resize(900, 600)
        tab.show()
        qtbot.waitUntil(lambda: tab.add_button.isVisible())
        assert tab.add_button.mapTo(tab, tab.add_button.rect().topRight()).x() > tab.scroll.mapTo(tab, tab.scroll.rect().center()).x()
