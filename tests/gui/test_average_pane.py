'''
pickmix: tests for the Average pane
'''

# Import external dependencies
import pytest
from collections.abc import Callable, Iterator
from pathlib import Path
from pytestqt.qtbot import QtBot

# Import internal pickmix objects
from pickmix.config import Kind
from pickmix.estimates import EstimateService
from pickmix.gui.panes.average_pane import AveragePane
from pickmix.loader import Loader
from pickmix.model import Session
from pickmix.project import open_project

# NAME: the single tomogram of the fixture project
NAME: str = 'Position_1_2'

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
