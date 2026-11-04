'''
pickmix: tests for gui panes
'''

# Import external dependencies
import numpy as np, pytest
from collections.abc import Callable, Iterator
from pathlib import Path
from PySide6.QtGui import QImage, QShortcut
from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot

# Import internal pickmix objects
from pickmix import __version__
from pickmix.config import Kind, load_config
from pickmix.estimates import EstimateService
from pickmix.gui.dialogs.kind_dialog import DELETED, KindDialog
from pickmix.gui.panes.average_pane import AveragePane
from pickmix.gui.panes.kinds_pane import KindsPane
from pickmix.gui.panes.settings_pane import NO_KIND, SettingsPane
from pickmix.gui.panes.tomo_pane import COLOUR_CURRENT, COLOUR_PENDING, COLOUR_VISITED, TomoPane
from pickmix.gui.panes.tomograms_pane import TomogramsPane, tomogram_status
from pickmix.gui.panes.welcome_pane import WelcomePane
from pickmix.loader import Loader
from pickmix.model import PickStore, Session
from pickmix.project import open_project

# NAME: the single tomogram of the fixture project
NAME: str = 'Position_1_2'

# THREE: tomograms for the dock tests
THREE: tuple[str, ...] = ('Position_1_2', 'Position_1_3', 'Other_9')

# _kinds_pane: a Kinds pane showing a fresh project; returns the pane and the config path
def _kinds_pane(qtbot: QtBot, make_config: Callable[..., Path]) -> tuple[KindsPane, Path]:
    path = make_config()
    pane = KindsPane()
    qtbot.addWidget(pane)
    pane.set_project(open_project(path))
    return pane, path

# _kinds_pane_with_picks: a pane with cage, green (child of cage) and yellow kinds, a session, and picks of every kind
def _kinds_pane_with_picks(qtbot: QtBot, make_config: Callable[..., Path]) -> tuple[KindsPane, Path, Session]:
    path = make_config()
    project = open_project(path)
    project.update(kinds={
        'cage': Kind(marker_a=600, box_a=700), 'green': Kind(marker_a=40, box_a=200, parent='cage'), 'yellow': Kind(marker_a=100, box_a=100),
    })
    session = Session(project)
    for kind in ('cage', 'cage', 'green', 'yellow'):
        session.store.add('Position_1_2', kind, 1.0, 1.0, 1.0)
    pane = KindsPane()
    qtbot.addWidget(pane)
    pane.set_project(project)
    pane.set_session(session, None)
    return pane, path, session

# _settings_pane: a settings pane showing a fresh project; returns the pane and the config path
def _settings_pane(qtbot: QtBot, make_config: Callable[..., Path]) -> tuple[SettingsPane, Path]:
    path = make_config()
    pane = SettingsPane()
    qtbot.addWidget(pane)
    pane.set_project(open_project(path))
    return pane, path

# _tomo_pane: a pane over a three-tomogram session
def _tomo_pane(qtbot: QtBot, make_config: Callable[..., Path]) -> tuple[TomoPane, Session]:
    session = Session(open_project(make_config(names=THREE)))
    pane = TomoPane()
    qtbot.addWidget(pane)
    pane.set_session(session)
    return pane, session

# pane: a pane over a session with a passthrough kind, shut down afterwards
@pytest.fixture
def pane(qtbot: QtBot, make_config: Callable[..., Path]) -> Iterator[tuple[AveragePane, Session, EstimateService]]:
    project = open_project(make_config())
    project.update(kinds={'yellow': Kind(marker_a=20, box_a=21.44)})
    session, loader = Session(project), Loader(project)
    service = EstimateService(session, loader)
    widget = AveragePane()
    qtbot.addWidget(widget)
    widget.set_session(session, service)
    yield widget, session, service
    service.shutdown()
    loader.shutdown()

# TestAveragePane: Average pane
class TestAveragePane:
    # test_summary: picks, tomograms and picks per tomogram for the chosen kind
    def test_summary(self, pane: tuple[AveragePane, Session, EstimateService]) -> None:
        widget, session, _ = pane
        assert widget.summary.text() == 'No picks of this kind'
        session.store.add(NAME, 'yellow', 4.0, 3.0, 2.0)
        session.store.add(NAME, 'yellow', 5.0, 3.0, 2.0)
        widget.refresh_kinds()
        assert widget.summary.text() == '2 picks in 1 tomograms (2.0 per tomogram)'

    # test_run_shows_images: running averages the picks and shows the labelled montage and the mean
    def test_run_shows_images(self, qtbot: QtBot, pane: tuple[AveragePane, Session, EstimateService]) -> None:
        widget, session, service = pane
        pick = session.store.add(NAME, 'yellow', 4.0, 3.0, 2.0)
        qtbot.waitUntil(lambda: service.store.state(pick) == 'ok', timeout=5000)
        widget.refresh_kinds()
        widget.run()
        assert widget.spinner.status == 'running' and not widget.run_button.isEnabled()
        qtbot.waitUntil(lambda: widget.result is not None, timeout=5000)
        assert widget.results_table.rowCount() == 2 and not widget.mean_label.pixmap().isNull() and not widget.montage_label.pixmap().isNull()
        assert widget.spinner.status is None and widget.run_button.isEnabled() and widget.save_button.isEnabled()
        # averaging alone writes nothing
        assert not (session.project.config.out_dir / 'average' / 'yellow' / 'overall_mean.png').exists()

    # test_run_without_estimates: nothing to average is said in a message, not raised
    def test_run_without_estimates(self, pane: tuple[AveragePane, Session, EstimateService], capsys) -> None:
        widget, _, _ = pane
        widget.run()
        assert 'No picks' in capsys.readouterr().out and widget.spinner.status is None

    # _ran: a pane that has averaged one pick
    def _ran(self, qtbot: QtBot, pane: tuple[AveragePane, Session, EstimateService]) -> AveragePane:
        widget, session, service = pane
        pick = session.store.add(NAME, 'yellow', 4.0, 3.0, 2.0)
        qtbot.waitUntil(lambda: service.store.state(pick) == 'ok', timeout=5000)
        widget.refresh_kinds()
        widget.run()
        qtbot.waitUntil(lambda: widget.result is not None, timeout=5000)
        return widget

    # test_list_shows_counts: row 0 is the overall count, each other row a tomogram with its own count, and choosing a row changes the mean
    def test_list_shows_counts(self, qtbot: QtBot, pane: tuple[AveragePane, Session, EstimateService]) -> None:
        widget = self._ran(qtbot, pane)
        r = widget.result
        assert widget.results_table.item(0, 0).text() == 'overall' and widget.results_table.item(0, 1).text() == str(r.count)
        for row, name in enumerate(r.per_tomogram, start=1):
            assert widget.results_table.item(row, 0).text() == name and widget.results_table.item(row, 1).text() == str(r.counts[name])
        overall = widget.mean_label.pixmap().toImage()
        widget.results_table.selectRow(1)
        assert not widget.mean_label.pixmap().isNull()
        assert overall.size() == widget.mean_label.pixmap().toImage().size()

    # test_save_writes_on_request: nothing on disk until Save, then the mean, the montage and the labelled montage, per-tomogram means only when ticked
    def test_save_writes_on_request(self, qtbot: QtBot, pane: tuple[AveragePane, Session, EstimateService]) -> None:
        widget = self._ran(qtbot, pane)
        folder = widget.result.folder
        assert not folder.exists()
        paths = widget.save()
        assert sorted(p.name for p in folder.glob('*.png')) == ['overall_mean.png', 'overall_montage.png', 'overall_montage_labelled.png'] and len(paths) == 3
        plain, labelled = QImage(str(folder / 'overall_montage.png')), QImage(str(folder / 'overall_montage_labelled.png'))
        assert not plain.isNull() and plain.size() == labelled.size() and plain != labelled
        # saved as the square montage, whatever shape the pane shows it in
        assert plain.width() == plain.height()
        widget.per_tomogram_box.setChecked(True)
        widget.save()
        assert any(p.name.endswith('_mean.png') and p.name != 'overall_mean.png' for p in folder.glob('*.png'))

    # test_save_needs_a_result: Save is greyed and writes nothing before a run, and again after the kind changes
    def test_save_needs_a_result(self, qtbot: QtBot, pane: tuple[AveragePane, Session, EstimateService]) -> None:
        widget, _, _ = pane
        assert not widget.save_button.isEnabled() and widget.save() == []
        widget = self._ran(qtbot, pane)
        assert widget.save_button.isEnabled()
        widget.kind_box.addItem('other')
        widget.kind_box.setCurrentText('other')
        assert not widget.save_button.isEnabled() and widget.results_table.rowCount() == 0 and widget.result is None

    # test_layout: Mean and Montage have their own headings and the list sits beside the mean
    def test_layout(self, pane: tuple[AveragePane, Session, EstimateService]) -> None:
        widget, _, _ = pane
        headings = {label.text() for label in widget.findChildren(QLabel) if label.font().bold()}
        assert {'Mean', 'Montage'} <= headings
        assert not hasattr(widget, 'status')

# TestKindsPane: kinds pane
class TestKindsPane:
    # test_lists_kinds: each kind is listed with its values as plain text and an edit button
    def test_lists_kinds(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, _ = _kinds_pane(qtbot, make_config)
        assert pane.kind_names() == ['cage'] and 'cage' in pane.edit_buttons
        text = pane.details['cage'].text()
        assert '<b>Marker:</b> 600 Å' in text and '<b>Box:</b> from estimator' in text and '<b>Estimator:</b> ring' in text and '<b>Parent:</b> none' in text

    # test_add_kind: a new kind is saved after the others and takes the first free key
    def test_add_kind(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, path = _kinds_pane(qtbot, make_config)
        with qtbot.waitSignal(pane.config_saved):
            pane._apply('yellow', Kind(marker_a=100, box_a=100))
        config = load_config(path)
        assert list(config.kinds) == ['cage', 'yellow'] and config.hotkeys[:3] == ['cage', 'yellow', '']
        assert pane.kind_names() == ['cage', 'yellow']

    # test_edit_kind: the edit button opens the dialog on that kind and OK saves the changes
    def test_edit_kind(self, qtbot: QtBot, make_config: Callable[..., Path], monkeypatch) -> None:
        pane, path = _kinds_pane(qtbot, make_config)
        # fake_exec: change the marker size and accept
        def fake_exec(dialog: KindDialog) -> int:
            assert not dialog.adding and dialog.name_edit.text() == 'cage'
            dialog.marker_spin.setValue(700)
            return 1
        monkeypatch.setattr(KindDialog, 'exec', fake_exec)
        pane.edit_buttons['cage'].click()
        assert load_config(path).kinds['cage'].marker_a == 700
        assert '<b>Marker:</b> 700 Å' in pane.details['cage'].text()

    # test_cancel_changes_nothing: a cancelled dialog leaves the file alone
    def test_cancel_changes_nothing(self, qtbot: QtBot, make_config: Callable[..., Path], monkeypatch) -> None:
        pane, path = _kinds_pane(qtbot, make_config)
        before = path.read_text()
        monkeypatch.setattr(KindDialog, 'exec', lambda dialog: 0)
        pane.add_button.click()
        assert path.read_text() == before

    # test_dialog_check: the dialog refuses a duplicate name and a passthrough with no box before anything is saved
    def test_dialog_check(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, _ = _kinds_pane(qtbot, make_config)
        assert pane._problem('cage2', Kind(marker_a=10, box_a=0, estimator='none'), None) is not None
        assert pane._problem('cage2', Kind(marker_a=10, box_a=10, parent='missing'), None) is not None
        assert pane._problem('cage2', Kind(marker_a=10, box_a=10), None) is None

    # test_delete_kind: deleting removes the kind and frees its key
    def test_delete_kind(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, path = _kinds_pane(qtbot, make_config)
        pane._apply('yellow', Kind(marker_a=100, box_a=100))
        pane._delete('yellow')
        config = load_config(path)
        assert list(config.kinds) == ['cage'] and config.hotkeys == ['cage', *[''] * 8]

    # test_delete_blocked: a kind that is another's parent is not deleted, and says why
    def test_delete_blocked(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, path = _kinds_pane(qtbot, make_config)
        pane._apply('green', Kind(marker_a=40, box_a=200, parent='cage'))
        before = path.read_text()
        pane._delete('cage')
        assert pane.status.text().startswith('Not deleted') and path.read_text() == before

    # test_delete_only_kind: the last kind can be deleted, leaving an empty list and unused keys
    def test_delete_only_kind(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, path = _kinds_pane(qtbot, make_config)
        pane._delete('cage')
        config = load_config(path)
        assert config.kinds == {} and config.hotkeys == [''] * 9
        assert pane.kind_names() == []
        pane._apply('yellow', Kind(marker_a=100, box_a=100))
        assert list(load_config(path).kinds) == ['yellow'] and load_config(path).hotkeys[0] == 'yellow'

    # test_rename_follows: a rename keeps the kind's place, hotkey, children and picks, in memory and in picks.csv
    def test_rename_follows(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, path, session = _kinds_pane_with_picks(qtbot, make_config)
        pane._apply('gold', Kind(marker_a=600, box_a=700), old='cage')
        config = load_config(path)
        assert list(config.kinds) == ['gold', 'green', 'yellow'] and config.kinds['green'].parent == 'gold'
        assert config.hotkeys[:3] == ['gold', 'green', 'yellow']
        assert [p.kind for p in session.store.all()] == ['gold', 'gold', 'green', 'yellow']
        assert sorted(p.kind for p in PickStore(session.project).all()) == ['gold', 'gold', 'green', 'yellow']
        assert pane.kind_names() == ['gold', 'green', 'yellow']

    # test_edit_without_rename_keeps_picks: editing values only leaves the picks alone
    def test_edit_without_rename_keeps_picks(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, path, session = _kinds_pane_with_picks(qtbot, make_config)
        pane._apply('cage', Kind(marker_a=650, box_a=700), old='cage')
        assert load_config(path).kinds['cage'].marker_a == 650 and session.store.total('cage') == 2

    # test_rename_to_existing_refused: a kind cannot take another kind's name
    def test_rename_to_existing_refused(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, _, _ = _kinds_pane_with_picks(qtbot, make_config)
        assert 'already exists' in pane._problem('green', Kind(marker_a=600, box_a=700), 'cage')

    # test_delete_with_picks_asks: picks of the kind go with it after a yes, and stay with a no
    def test_delete_with_picks_asks(self, qtbot: QtBot, make_config: Callable[..., Path], monkeypatch) -> None:
        pane, path, session = _kinds_pane_with_picks(qtbot, make_config)
        asked: list[str] = []
        monkeypatch.setattr(KindsPane, '_confirm', lambda self, text: asked.append(text) or False)
        pane._delete('yellow')
        assert 'yellow' in asked[0] and '1 picks' in asked[0] and 'yellow' in load_config(path).kinds and session.store.total('yellow') == 1
        monkeypatch.setattr(KindsPane, '_confirm', lambda self, text: True)
        pane._delete('yellow')
        assert 'yellow' not in load_config(path).kinds and session.store.total('yellow') == 0
        assert sorted(p.kind for p in PickStore(session.project).all()) == ['cage', 'cage', 'green']

    # test_delete_without_picks_does_not_ask: an empty kind is deleted without a question
    def test_delete_without_picks_does_not_ask(self, qtbot: QtBot, make_config: Callable[..., Path], monkeypatch) -> None:
        pane, path, session = _kinds_pane_with_picks(qtbot, make_config)
        session.store.remove_kind('yellow')
        # fail: asking is a bug here
        def fail(self: KindsPane, text: str) -> bool:
            raise AssertionError(text)
        monkeypatch.setattr(KindsPane, '_confirm', fail)
        pane._delete('yellow')
        assert 'yellow' not in load_config(path).kinds

    # test_refused_delete_keeps_picks: a delete the config refuses neither asks nor touches the picks
    def test_refused_delete_keeps_picks(self, qtbot: QtBot, make_config: Callable[..., Path], monkeypatch) -> None:
        pane, path, session = _kinds_pane_with_picks(qtbot, make_config)
        monkeypatch.setattr(KindsPane, '_confirm', lambda self, text: (_ for _ in ()).throw(AssertionError(text)))
        pane._delete('cage')
        assert pane.status.text().startswith('Not deleted') and session.store.total('cage') == 2

    # test_details_are_a_vertical_list_with_bold_keys: one key per line, each key bold
    def test_details_are_a_vertical_list_with_bold_keys(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, _ = _kinds_pane(qtbot, make_config)
        lines = pane.details['cage'].text().split('<br>')
        assert len(lines) == 7 and all(line.startswith('<b>') and ':</b> ' in line for line in lines)

    # test_kinds_flow_into_columns: a wide block gives one column, a narrow one gives several, filling across then down
    def test_kinds_flow_into_columns(self, qtbot: QtBot, make_config: Callable[..., Path], monkeypatch) -> None:
        pane, _, _ = _kinds_pane_with_picks(qtbot, make_config)
        pane.resize(900, 600)
        pane.show()
        position = lambda i: pane.grid.getItemPosition(pane.grid.indexOf(pane.cards[i]))[:2]
        monkeypatch.setattr('pickmix.gui.panes.kinds_pane._CARD_WIDTH', 10000)
        pane._columns = 0
        pane._reflow()
        assert pane._columns == 1 and [position(i) for i in range(3)] == [(0, 0), (1, 0), (2, 0)]
        monkeypatch.setattr('pickmix.gui.panes.kinds_pane._CARD_WIDTH', 100)
        pane._reflow()
        assert pane._columns >= 3 and [position(i) for i in range(3)] == [(0, 0), (0, 1), (0, 2)]

    # test_add_button_is_on_the_right: the Add button sits after the heading's stretch
    def test_add_button_is_on_the_right(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, _ = _kinds_pane(qtbot, make_config)
        pane.resize(900, 600)
        pane.show()
        qtbot.waitUntil(lambda: pane.add_button.isVisible())
        assert pane.add_button.mapTo(pane, pane.add_button.rect().topRight()).x() > pane.scroll.mapTo(pane, pane.scroll.rect().center()).x()

# TestSettingsPane: settings pane
class TestSettingsPane:
    # test_shows_project: source and ring values come from the config, and showing them saves nothing
    def test_shows_project(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        path = make_config()
        before = path.read_text()
        pane = SettingsPane()
        qtbot.addWidget(pane)
        with qtbot.assertNotEmitted(pane.config_saved):
            pane.set_project(open_project(path))
        assert pane.source_box.currentText() == 'denoised' and pane.ring_form.get().radius_step_a == 25.0
        assert path.read_text() == before

    # test_source_autosaves: choosing a source writes config.toml and announces it
    def test_source_autosaves(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, path = _settings_pane(qtbot, make_config)
        with qtbot.waitSignal(pane.config_saved):
            pane.source_box.setCurrentText('raw')
        assert load_config(path).source == 'raw'

    # test_ring_value_autosaves: a committed ring value is written, the others are kept
    def test_ring_value_autosaves(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, path = _settings_pane(qtbot, make_config)
        with qtbot.waitSignal(pane.config_saved):
            pane.ring_form._boxes['radius_step_a'][0].setValue(50.0)
        config = load_config(path)
        assert config.ring.radius_step_a == 50.0 and config.ring.radius_range_a == (150.0, 500.0)

    # test_no_save_button: there is nothing to press
    def test_no_save_button(self, qtbot: QtBot) -> None:
        pane = SettingsPane()
        qtbot.addWidget(pane)
        assert not hasattr(pane, 'save_button')

    # test_hotkey_defaults: keys start on the kinds in order, the rest are unused
    def test_hotkey_defaults(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, _ = _settings_pane(qtbot, make_config)
        assert [b.currentText() for b in pane.hotkey_boxes] == ['cage', *[NO_KIND] * 8]
        assert pane.hotkey_boxes[1].itemText(0) == NO_KIND and pane.hotkey_boxes[1].count() == 2

    # test_hotkey_change_saves: choosing a kind for a key saves it and moves the kind off its old key
    def test_hotkey_change_saves(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, path = _settings_pane(qtbot, make_config)
        with qtbot.waitSignal(pane.hotkeys_saved):
            pane.hotkey_boxes[2].setCurrentText('cage')
        assert load_config(path).hotkeys == ['', '', 'cage', *[''] * 6]
        assert pane.hotkey_boxes[0].currentText() == NO_KIND

    # test_refresh_hotkeys: new kinds appear in the dropdowns after the project changes
    def test_refresh_hotkeys(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, _ = _settings_pane(qtbot, make_config)
        pane.project.update(kinds={'cage': Kind(marker_a=600, box_a=700), 'yellow': Kind(marker_a=100, box_a=100)}, hotkeys=['cage', 'yellow'])
        pane.refresh_hotkeys()
        assert pane.hotkey_boxes[1].currentText() == 'yellow' and pane.hotkey_boxes[5].count() == 3

    # test_form_labels: parameters show their title and explain themselves on hover
    def test_form_labels(self, qtbot: QtBot) -> None:
        pane = SettingsPane()
        qtbot.addWidget(pane)
        label = pane.ring_form.labels['radius_range_a']
        assert label.text() == 'Radius range (Å)' and label.toolTip()
        assert len(pane.ring_form._boxes['radius_range_a']) == 2

    # test_ring_section_collapsed: ring parameters are hidden until the section is opened
    def test_ring_section_collapsed(self, qtbot: QtBot) -> None:
        pane = SettingsPane()
        qtbot.addWidget(pane)
        assert pane.ring_form.isHidden()
        pane.ring_section.toggle.setChecked(True)
        assert not pane.ring_form.isHidden()

    # test_width_fixed: opening the ring section does not change the pane's minimum width
    def test_width_fixed(self, qtbot: QtBot) -> None:
        pane = SettingsPane()
        qtbot.addWidget(pane)
        closed = pane.minimumSizeHint().width()
        pane.ring_section.toggle.setChecked(True)
        assert pane.minimumSizeHint().width() == closed

# TestTomoPane: tomogram dock
class TestTomoPane:
    # test_lines: number, name and picks, no markers
    def test_lines(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, session = _tomo_pane(qtbot, make_config)
        session.store.add('Position_1_2', 'cage', 1.0, 1.0, 1.0)
        assert pane.list.item(0).text().split() == ['1', 'Position_1_2', '1']
        assert pane.list.item(1).text().split() == ['2', 'Position_1_3', '0']

    # test_state_colours: current blue and bold, opened green, not yet opened orange
    def test_state_colours(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, session = _tomo_pane(qtbot, make_config)
        assert pane.list.item(0).foreground().color() == COLOUR_CURRENT and pane.list.item(0).font().bold()
        assert pane.list.item(1).foreground().color() == COLOUR_PENDING and not pane.list.item(1).font().bold()
        pane._clicked(pane.list.item(2))
        assert session.current == 'Other_9'
        assert pane.list.item(2).foreground().color() == COLOUR_CURRENT
        assert pane.list.item(0).foreground().color() == COLOUR_VISITED and not pane.list.item(0).font().bold()
        assert pane.list.item(1).foreground().color() == COLOUR_PENDING

    # test_visited_label: visited count sits above the search box, with no per-kind totals
    def test_visited_label(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, session = _tomo_pane(qtbot, make_config)
        assert pane.visited.text() == 'Visited 1/3'
        session.go(1)
        assert pane.visited.text() == 'Visited 2/3'
        assert not hasattr(pane, 'totals')

    # test_enter_does_nothing: Enter in the search box changes nothing, matching is live only
    def test_enter_does_nothing(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, session = _tomo_pane(qtbot, make_config)
        before = session.current
        pane.jump_edit.setText('other')
        pane._live.stop()
        pane.jump_edit.returnPressed.emit()
        assert session.current == before and pane.jump_edit.text() == 'other'

# TestWelcomePane: welcome pane
class TestWelcomePane:
    # test_version_line: the dimmed line names the installed version
    def test_version_line(self, qtbot: QtBot) -> None:
        pane = WelcomePane()
        qtbot.addWidget(pane)
        assert pane.version.text() == f'pickmix v{__version__}'

    # test_buttons_have_icons: icon over text, both buttons
    def test_buttons_have_icons(self, qtbot: QtBot) -> None:
        pane = WelcomePane()
        qtbot.addWidget(pane)
        for button in (pane.open_button, pane.new_button):
            labels = button.findChildren(QLabel)
            assert len(labels) == 2 and not labels[0].pixmap().isNull() and labels[1].text()

    # test_text_fallback: without icon files the buttons are text only
    def test_text_fallback(self, qtbot: QtBot, monkeypatch) -> None:
        monkeypatch.setattr('pickmix.gui.style.tinted', lambda stem, **kwargs: None)
        pane = WelcomePane()
        qtbot.addWidget(pane)
        assert [label.text() for label in pane.open_button.findChildren(QLabel)] == ['Open project']

    # test_shortcuts: Ctrl+O and Ctrl+N press the buttons
    def test_shortcuts(self, qtbot: QtBot) -> None:
        pane = WelcomePane()
        qtbot.addWidget(pane)
        by_key = {s.key().toString(): s for s in pane.findChildren(QShortcut)}
        assert set(by_key) == {'Ctrl+O', 'Ctrl+N'}
        with qtbot.waitSignal(pane.open_button.clicked):
            by_key['Ctrl+O'].activated.emit()
        with qtbot.waitSignal(pane.new_button.clicked):
            by_key['Ctrl+N'].activated.emit()

    # test_shortcut_respects_disabled: a button disabled during loading ignores its shortcut
    def test_shortcut_respects_disabled(self, qtbot: QtBot) -> None:
        pane = WelcomePane()
        qtbot.addWidget(pane)
        pane.open_button.setEnabled(False)
        shortcut = next(s for s in pane.findChildren(QShortcut) if s.key().toString() == 'Ctrl+O')
        with qtbot.assertNotEmitted(pane.open_button.clicked):
            shortcut.activated.emit()

# TestTomogramsPane: tomograms pane
class TestTomogramsPane:
    # test_rows_and_summary: usable tomograms are listed, counted and unmarked
    def test_rows_and_summary(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane = TomogramsPane()
        qtbot.addWidget(pane)
        pane.set_project(open_project(make_config()))
        assert pane.table.rowCount() == 1 and pane.table.item(0, 1).text() == 'Position_1_2'
        assert pane.table.item(0, 0).icon().isNull() and pane.table.item(0, 0).text() == ''
        assert not pane.table.item(0, 4).icon().isNull()
        assert pane.summary.text() == '1 total (1 denoised), 0 rejected'

    # test_rejected_row: a rejected tomogram gets an error marker with its reason and greyed text
    def test_rejected_row(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane = TomogramsPane()
        qtbot.addWidget(pane)
        pane.set_project(open_project(make_config(shape=(4, 6, 20))))
        assert not pane.table.item(0, 0).icon().isNull() and 'shape mismatch' in pane.table.item(0, 0).toolTip()
        assert pane.table.item(0, 2).text() == '(4, 6, 20)'
        assert pane.summary.text() == '1 total (0 denoised), 1 rejected'

    # test_warning_without_denoised: a usable tomogram with no denoised pair is marked
    def test_warning_without_denoised(self, make_config: Callable[..., Path]) -> None:
        project = open_project(make_config(names=('A_1', 'B_2')))
        (project.config.denoised_dir / 'nt_raw4_B_2_stack_Vol.denoised.mrc').unlink()
        project = open_project(project.path)
        assert tomogram_status(project, 'A_1') == (None, '')
        status, tip = tomogram_status(project, 'B_2')
        assert status == 'warn' and 'denoised' in tip

    # test_marker_column_fixed: the marker column has no heading and a fixed width, so names align
    def test_marker_column_fixed(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane = TomogramsPane()
        qtbot.addWidget(pane)
        pane.set_project(open_project(make_config(names=('A_1', 'B_2'))))
        assert pane.table.horizontalHeaderItem(0).text() == '' and pane.table.columnWidth(0) == 28
        assert not pane.table.verticalHeader().isVisible() and not pane.table.showGrid()

    # test_live_search: typing a name shows that tomogram without pressing Enter, and keeps the text
    def test_live_search(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, session = _tomo_pane(qtbot, make_config)
        pane.jump_edit.setText('other')
        qtbot.waitUntil(lambda: session.current == 'Other_9', timeout=2000)
        assert pane.jump_edit.text() == 'other'

    # test_no_selection_highlight: clicking jumps but nothing is highlighted over the colours
    def test_no_selection_highlight(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, session = _tomo_pane(qtbot, make_config)
        assert pane.list.selectionMode() == pane.list.SelectionMode.NoSelection
        pane._clicked(pane.list.item(1))
        assert session.current == 'Position_1_3' and not pane.list.selectedItems()

    # test_number_left_picks_right: the number column is left-aligned and the picks column right-aligned
    def test_number_left_picks_right(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, session = _tomo_pane(qtbot, make_config)
        session.store.add('Position_1_2', 'cage', 1.0, 1.0, 1.0)
        assert pane.header.text().startswith('No.')
        assert pane.list.item(0).text().startswith('1  ') and pane.list.item(0).text().endswith('    1')
