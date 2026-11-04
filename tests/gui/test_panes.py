'''
pickmix: tests for gui panes
'''

# Import external dependencies
import pytest
from collections.abc import Callable, Iterator
from pathlib import Path
from PySide6.QtGui import QShortcut
from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot

# Import internal pickmix objects
from pickmix import __version__
from pickmix.config import Kind
from pickmix.estimates import EstimateService
from pickmix.gui.panes.average_pane import AveragePane
from pickmix.gui.panes.tomo_pane import COLOUR_CURRENT, COLOUR_PENDING, COLOUR_VISITED, TomoPane
from pickmix.gui.panes.welcome_pane import WelcomePane
from pickmix.loader import Loader
from pickmix.model import Session
from pickmix.project import open_project

# NAME: the single tomogram of the fixture project
NAME: str = 'Position_1_2'

# THREE: tomograms for the dock tests
THREE: tuple[str, ...] = ('Position_1_2', 'Position_1_3', 'Other_9')

# _pane: a pane over a three-tomogram session
def _pane(qtbot: QtBot, make_config: Callable[..., Path]) -> tuple[TomoPane, Session]:
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

    # test_run_shows_images: running averages the picks and shows the mean and montage
    def test_run_shows_images(self, qtbot: QtBot, pane: tuple[AveragePane, Session, EstimateService]) -> None:
        widget, session, service = pane
        pick = session.store.add(NAME, 'yellow', 4.0, 3.0, 2.0)
        qtbot.waitUntil(lambda: service.store.state(pick) == 'ok', timeout=5000)
        widget.refresh_kinds()
        widget.run()
        qtbot.waitUntil(lambda: widget.result is not None, timeout=5000)
        assert widget.results_list.count() == 2 and not widget.mean_label.pixmap().isNull() and not widget.montage_label.pixmap().isNull()
        assert (session.project.config.out_dir / 'average' / 'yellow' / 'overall_mean.png').exists()

    # test_run_without_estimates: nothing to average is said, not raised
    def test_run_without_estimates(self, pane: tuple[AveragePane, Session, EstimateService]) -> None:
        widget, _, _ = pane
        widget.run()
        assert 'No picks' in widget.status.text()

# TestTomoPane: tomogram dock
class TestTomoPane:
    # test_lines: number, name and picks, no markers
    def test_lines(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, session = _pane(qtbot, make_config)
        session.store.add('Position_1_2', 'cage', 1.0, 1.0, 1.0)
        assert pane.list.item(0).text().split() == ['1', 'Position_1_2', '1']
        assert pane.list.item(1).text().split() == ['2', 'Position_1_3', '0']

    # test_state_colours: current blue and bold, opened green, not yet opened orange
    def test_state_colours(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, session = _pane(qtbot, make_config)
        assert pane.list.item(0).foreground().color() == COLOUR_CURRENT and pane.list.item(0).font().bold()
        assert pane.list.item(1).foreground().color() == COLOUR_PENDING and not pane.list.item(1).font().bold()
        pane._clicked(pane.list.item(2))
        assert session.current == 'Other_9'
        assert pane.list.item(2).foreground().color() == COLOUR_CURRENT
        assert pane.list.item(0).foreground().color() == COLOUR_VISITED and not pane.list.item(0).font().bold()
        assert pane.list.item(1).foreground().color() == COLOUR_PENDING

    # test_visited_label: visited count sits above the search box, with no per-kind totals
    def test_visited_label(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, session = _pane(qtbot, make_config)
        assert pane.visited.text() == 'Visited 1/3'
        session.go(1)
        assert pane.visited.text() == 'Visited 2/3'
        assert not hasattr(pane, 'totals')

    # test_jump_box: a name jumps and clears the box, no match keeps the text
    def test_jump_box(self, qtbot: QtBot, make_config: Callable[..., Path]) -> None:
        pane, session = _pane(qtbot, make_config)
        pane.jump_edit.setText('other')
        pane.jump_edit.returnPressed.emit()
        assert session.current == 'Other_9' and pane.jump_edit.text() == ''
        pane.jump_edit.setText('zzz')
        pane.jump_edit.returnPressed.emit()
        assert session.current == 'Other_9' and pane.jump_edit.text() == 'zzz'

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
        monkeypatch.setattr('pickmix.gui.panes.welcome_pane.tinted', lambda stem, **kwargs: None)
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
