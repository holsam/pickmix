'''
pickmix: tests for the Export tab
'''

# Import external dependencies
import csv, pytest
from collections.abc import Callable, Iterator
from pathlib import Path
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

# Import internal pickmix objects
from pickmix.config import Kind
from pickmix.estimate.registry import Fit
from pickmix.estimates import EstimateService
from pickmix.gui.style import MUTED
from pickmix.gui.tabs.export_tab import ExportTab
from pickmix.loader import Loader
from pickmix.model import Session
from pickmix.project import open_project
from pickmix.utils.star import read_star_loop

# NAME: the single tomogram of the fixture project
NAME: str = 'Position_1_2'

# Setup: an export tab over a session with a passthrough kind and a failing kind, shut down after the test
@pytest.fixture
def setup(qtbot: QtBot, make_config: Callable[..., Path]) -> Iterator[Callable[[], tuple[ExportTab, Session, EstimateService]]]:
    closers: list[Callable[[], None]] = []

    # build: the tab and its parts
    def build() -> tuple[ExportTab, Session, EstimateService]:
        project = open_project(make_config())
        project.update(kinds={'yellow': Kind(marker_a=20, box_a=21.44), 'bad': Kind(marker_a=20, box_a=21.44, estimator='missing')})
        session, loader = Session(project), Loader(project)
        service = EstimateService(session, loader)
        closers.extend([service.shutdown, loader.shutdown])
        tab = ExportTab()
        qtbot.addWidget(tab)
        tab.set_session(session, loader, service)
        return tab, session, service

    yield build
    for close in closers:
        close()

# parent_setup: an export tab over a session with a cage kind and a green kind whose parent is the cage
@pytest.fixture
def parent_setup(qtbot: QtBot, make_config: Callable[..., Path]) -> Iterator[tuple[ExportTab, Session, EstimateService]]:
    project = open_project(make_config())
    project.update(kinds={
        'cage': Kind(marker_a=600, box_a=700),
        'green': Kind(marker_a=40, box_a=200, parent='cage', tilt_prior_deg=0.0),
    })
    session, loader = Session(project), Loader(project)
    service = EstimateService(session, loader)
    tab = ExportTab()
    qtbot.addWidget(tab)
    tab.set_session(session, loader, service)
    yield tab, session, service
    service.shutdown()
    loader.shutdown()

# TestExportTab: Export tab
class TestExportTab:
    # test_kind_numbers: per-kind counts and box in the export table
    def test_kind_numbers(self, qtbot: QtBot, setup: Callable[[], tuple[ExportTab, Session, EstimateService]]) -> None:
        tab, session, service = setup()
        pick = session.store.add(NAME, 'yellow', 4.0, 3.0, 2.0)
        qtbot.waitUntil(lambda: service.store.state(pick) == 'ok', timeout=5000)
        tab.refresh()
        assert [tab.kinds_table.item(0, c).text() for c in range(6)] == ['yellow', '1', '1', '0', '21', '4']

    # test_average_pane_wired: the Average pane lists the project's kinds
    def test_average_pane_wired(self, setup: Callable[[], tuple[ExportTab, Session, EstimateService]]) -> None:
        tab, _, _ = setup()
        assert tab.average.kind_box.count() == 2

    # test_quiet_table: the kinds table has the shared quiet look
    def test_quiet_table(self, setup: Callable[[], tuple[ExportTab, Session, EstimateService]]) -> None:
        tab, _, _ = setup()
        assert tab.kinds_table.verticalHeader().isHidden() and not tab.kinds_table.showGrid()

    # test_export_and_extract: both write their files and report skipped picks
    def test_export_and_extract(self, qtbot: QtBot, setup: Callable[[], tuple[ExportTab, Session, EstimateService]]) -> None:
        tab, session, service = setup()
        pick = session.store.add(NAME, 'yellow', 4.0, 3.0, 2.0)
        qtbot.waitUntil(lambda: service.store.state(pick) == 'ok', timeout=5000)
        out = session.project.config.out_dir
        lines = tab.export_all()
        assert any(l.startswith('yellow: wrote 1 particles') for l in lines) and 'bad: nothing to export' in lines
        assert read_star_loop(out / 'relion' / 'yellow' / 'particles.star')[0]['rlnCenteredCoordinateXAngst'] == '0.00'
        lines = tab.extract_all()
        assert any(l.startswith('yellow: wrote 1 boxes of 4 px') for l in lines)
        assert (out / 'particles' / 'yellow' / NAME / f'{NAME}_000.mrc').exists()
        service.shutdown()
        session.store.add(NAME, 'yellow', 1.0, 1.0, 1.0)
        assert any('no current estimate' in l for l in tab.export_all())

    # test_unmatched_skipped: a pick off its parent's surface is reported and left out of the star file
    def test_unmatched_skipped(self, qtbot: QtBot, parent_setup: tuple[ExportTab, Session, EstimateService]) -> None:
        tab, session, service = parent_setup
        session.store.add(NAME, 'cage', 10.0, 10.0, 10.0)
        session.store.add(NAME, 'green', 10.0 + 56.0, 10.0, 10.0)
        session.store.add(NAME, 'green', 10.0 + 20.0, 10.0, 10.0)
        qtbot.waitUntil(lambda: all(service.store.state(p) == 'ok' for p in session.store.all()), timeout=5000)
        lines = tab.export_all()
        assert any('green: 1 picks have no cage within 100 A' in l for l in lines)
        [row] = read_star_loop(session.project.config.out_dir / 'relion' / 'green' / 'particles.star')
        assert (row['rlnTomoSubtomogramTilt'], row['rlnAngleTiltPrior']) == ('90.0000', '0.0000')

    # test_no_console: the log box is gone and messages go to stdout
    def test_no_console(self, qtbot: QtBot, setup: Callable[[], tuple[ExportTab, Session, EstimateService]], capsys) -> None:
        tab, _, _ = setup()
        assert not hasattr(tab, 'log') and not hasattr(tab, 'status')
        tab._logged(['yellow: wrote 1 particles'])
        assert 'yellow: wrote 1 particles' in capsys.readouterr().out and tab.spinner.status is None

    # test_export_formats: star only and csv only write only that format, both write both
    def test_export_formats(self, qtbot: QtBot, setup: Callable[[], tuple[ExportTab, Session, EstimateService]]) -> None:
        tab, session, service = setup()
        pick = session.store.add(NAME, 'yellow', 4.0, 3.0, 2.0)
        qtbot.waitUntil(lambda: service.store.state(pick) == 'ok', timeout=5000)
        out = session.project.config.out_dir
        tab.export_all(formats=frozenset({'csv'}))
        assert (out / 'csv' / 'yellow.csv').exists() and not (out / 'relion' / 'yellow').exists()
        tab.export_all(formats=frozenset({'star'}))
        assert (out / 'relion' / 'yellow' / 'particles.star').exists()
        rows = list(csv.DictReader(open(out / 'csv' / 'yellow.csv')))
        assert len(rows) == 1 and rows[0]['kind'] == 'yellow'

    # test_export_button_needs_a_format: ticking neither format disables Export, and a running job disables both buttons
    def test_export_button_needs_a_format(self, setup: Callable[[], tuple[ExportTab, Session, EstimateService]]) -> None:
        tab, _, _ = setup()
        assert tab.star_box.isChecked() and tab.csv_box.isChecked() and tab.export_button.isEnabled()
        tab.star_box.setChecked(False)
        assert tab.export_button.isEnabled()
        tab.csv_box.setChecked(False)
        assert not tab.export_button.isEnabled() and tab.extract_button.isEnabled()
        tab.csv_box.setChecked(True)
        tab._running = True
        tab._sync_buttons()
        assert not tab.export_button.isEnabled() and not tab.extract_button.isEnabled()

    # test_include_flagged: flagged picks go in by default and stay out when Include flagged is cleared, in both formats
    def test_include_flagged(self, qtbot: QtBot, setup: Callable[[], tuple[ExportTab, Session, EstimateService]]) -> None:
        tab, session, service = setup()
        assert tab._includes['yellow'].isChecked() and 'Include flagged' in [tab.kinds_table.horizontalHeaderItem(c).text() for c in range(9)]
        pick = session.store.add(NAME, 'yellow', 4.0, 3.0, 2.0)
        qtbot.waitUntil(lambda: service.store.state(pick) == 'ok', timeout=5000)
        fit = service.store.get(pick)
        # the store hands back its row type, put wants a plain fit
        flagged = Fit.model_validate({**fit.model_dump(include=set(Fit.model_fields)), 'flag': 'edge'})
        service.store.put(pick, flagged, service.store.digest('yellow'))
        out = session.project.config.out_dir
        assert any(l.startswith('yellow: wrote 1 particles') for l in tab.export_all())
        tab._includes['yellow'].setChecked(False)
        lines = tab.export_all()
        assert 'yellow: nothing to export' in lines and not [l for l in lines if l.startswith('yellow: wrote')]

    # test_editable_columns_marked: Min SNR and Include flagged show the edit icon, the others are grey and plain
    def test_editable_columns_marked(self, setup: Callable[[], tuple[ExportTab, Session, EstimateService]]) -> None:
        tab, _, _ = setup()
        for c in (7, 8):
            assert not tab.kinds_table.horizontalHeaderItem(c).icon().isNull() and tab.kinds_table.horizontalHeaderItem(c).toolTip()
        for c in (0, 1, 2, 3, 4, 5, 6):
            assert tab.kinds_table.horizontalHeaderItem(c).icon().isNull()
            assert tab.kinds_table.item(0, c).foreground().color().name() == MUTED
