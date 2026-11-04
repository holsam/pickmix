'''
pickmix: Export tab, averages of each kind and RELION export and box extraction per kind
'''

# Import external dependencies
import numpy as np
from collections.abc import Callable
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QGroupBox, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

# Import internal pickmix objects
from pickmix.estimates import EstimateService
from pickmix.export import Item, export_csv, export_kind, recommend_box
from pickmix.extract import extract_kind
from pickmix.geometry import Parent
from pickmix.gui.components.icons import icon
from pickmix.gui.components.status import StatusBadge
from pickmix.gui.components.toast import notify
from pickmix.gui.panes.average_pane import AveragePane
from pickmix.gui.style import MUTED, quiet_table, tidy
from pickmix.gui.workers import post, run_in_background
from pickmix.items import items, matched
from pickmix.loader import Loader
from pickmix.model import Session

# _KIND_COLUMNS: per-kind export table headings
_KIND_COLUMNS: list[str] = ['Kind', 'Picks', 'Estimated', 'Flagged', 'Box (A)', 'Box (px)', 'Extract A/px', 'Min SNR', 'Include flagged']

# _EDITABLE: the columns you can change; the rest are read-only
_EDITABLE: tuple[int, ...] = (7, 8)

# _ANY_SNR: minimum of the SNR filter, shown as "any"
_ANY_SNR: float = -1000.0

# Settings: per kind, the minimum SNR and whether flagged picks are included
type Settings = dict[str, tuple[float, bool]]

# ExportTab: the Average pane above the per-kind export and extraction table
class ExportTab(QWidget):
    # __init__: build the layout
    def __init__(self) -> None:
        super().__init__()
        self.session: Session | None = None
        self.loader: Loader | None = None
        self.service: EstimateService | None = None
        self._running = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.refresh)
        self.average = AveragePane()
        self.kinds_table = QTableWidget(0, len(_KIND_COLUMNS))
        self.kinds_table.setHorizontalHeaderLabels(_KIND_COLUMNS)
        quiet_table(self.kinds_table)
        self.kinds_table.setMaximumHeight(160)
        # editable columns say so in their headers; read-only ones are greyed below
        pencil = icon('edit')
        for c in _EDITABLE:
            header = self.kinds_table.horizontalHeaderItem(c)
            header.setToolTip('Editable: this setting applies to the export and extraction')
            if pencil is not None:
                header.setIcon(pencil)
        self._spins: dict[str, QDoubleSpinBox] = {}
        self._includes: dict[str, QCheckBox] = {}
        self.star_box = QCheckBox('.star')
        self.csv_box = QCheckBox('.csv')
        for box in (self.star_box, self.csv_box):
            box.setChecked(True)
        self.star_box.setToolTip('RELION particles.star and one coordinates file per tomogram, in out/relion/<kind>')
        self.csv_box.setToolTip('One picks and fits table per kind, in out/csv')
        self.export_button = QPushButton('Export')
        self.extract_button = QPushButton('Extract boxes')
        self.extract_button.setToolTip('Cut the boxes as MRC files, in out/particles/<kind>')
        self.spinner = StatusBadge()
        buttons = QHBoxLayout()
        buttons.addWidget(self.export_button)
        buttons.addWidget(self.star_box)
        buttons.addWidget(self.csv_box)
        buttons.addSpacing(24)
        buttons.addWidget(self.extract_button)
        buttons.addWidget(self.spinner)
        buttons.addStretch()
        export = QGroupBox('Export and extract')
        box = QVBoxLayout(export)
        box.addWidget(self.kinds_table)
        box.addLayout(buttons)
        layout = QVBoxLayout(self)
        tidy(layout)
        layout.addWidget(self.average)
        layout.addWidget(export)
        self.export_button.clicked.connect(self._export)
        self.extract_button.clicked.connect(lambda: self._run(self.extract_all, 'Extracting boxes...'))
        self.star_box.toggled.connect(self._sync_buttons)
        self.csv_box.toggled.connect(self._sync_buttons)

    # set_session: show a session and follow its picks and estimates
    def set_session(self, session: Session, loader: Loader, service: EstimateService) -> None:
        self.session, self.loader, self.service = session, loader, service
        session.store.listeners.append(self._schedule)
        service.store.listeners.append(self._schedule)
        self.average.set_session(session, service)
        self.refresh_kinds()

    # clear: no project or no session, so nothing to show
    def clear(self) -> None:
        self.session = self.loader = self.service = None
        self.average.set_session(None, None)
        self.kinds_table.setRowCount(0)
        self._spins, self._includes = {}, {}

    # refresh_kinds: rebuild the export table and the average kind list from the config
    def refresh_kinds(self) -> None:
        if self.session is None:
            return
        kinds = self.session.project.config.kinds
        self._spins, self._includes = {}, {}
        self.kinds_table.setRowCount(len(kinds))
        for r, (name, kind) in enumerate(kinds.items()):
            for c in range(len(_KIND_COLUMNS)):
                item = QTableWidgetItem()
                if c not in _EDITABLE:
                    item.setForeground(QColor(MUTED))
                self.kinds_table.setItem(r, c, item)
            self.kinds_table.item(r, 0).setText(name)
            self.kinds_table.item(r, 6).setText(f'{kind.extract_angpix:g}')
            spin = QDoubleSpinBox()
            spin.setRange(_ANY_SNR, 1000.0)
            spin.setValue(_ANY_SNR)
            spin.setSpecialValueText('any')
            include = QCheckBox()
            include.setChecked(True)
            self.kinds_table.setCellWidget(r, 7, spin)
            self.kinds_table.setCellWidget(r, 8, include)
            self._spins[name], self._includes[name] = spin, include
        self.average.refresh_kinds()
        self.refresh()
        self._sync_buttons()

    # refresh: the per-kind numbers
    def refresh(self) -> None:
        if self.session is None or self.service is None:
            return
        for r, (name, kind) in enumerate(self.session.project.config.kinds.items()):
            kind_items = self._items(name)
            box_a, box_px = recommend_box(kind, kind_items)
            for c, text in ((1, str(self.session.store.total(name))), (2, str(len(kind_items))), (3, str(sum(bool(f.flag) for _, f in kind_items))),
                            (4, f'{box_a:.0f}'), (5, str(box_px))):
                self.kinds_table.item(r, c).setText(text)

    # export_all: write the ticked formats for every kind with current estimates; returns message lines. Runs on a worker thread, so the widget settings are passed in
    def export_all(self, settings: Settings | None = None, formats: frozenset[str] | None = None) -> list[str]:
        assert self.session is not None
        settings = settings or self._settings()
        formats = self._formats() if formats is None else formats
        lines = self._preflight()
        config = self.session.project.config
        for name, kind in config.kinds.items():
            selected = self._selected(name, settings)
            if not selected:
                lines.append(f'{name}: nothing to export')
                continue
            min_snr, include = settings[name]
            if 'star' in formats:
                try:
                    s = export_kind(name, kind, selected, self.session.project.tomos, config.out_dir, min_snr=min_snr, drop_flagged=not include, parents=self._matched(name))
                except ValueError as e:
                    lines.append(str(e))
                else:
                    lines.append(
                        f'{name}: wrote {s.written} particles ({s.below_snr} below min SNR, {s.dropped_flagged} flagged dropped), '
                        f'box {s.box_a:.0f} A = {s.box_px} px at {kind.extract_angpix:g} A/px, in {str(s.folder)!r}'
                    )
            if 'csv' in formats:
                try:
                    c = export_csv(name, selected, config.out_dir, min_snr=min_snr, include_flagged=include)
                except ValueError as e:
                    lines.append(str(e))
                else:
                    lines.append(f'{name}: wrote {c.written} picks to {str(c.path)!r}')
        return lines

    # extract_all: cut boxes for every kind with current estimates; returns message lines. Runs on a worker thread
    def extract_all(self, settings: Settings | None = None) -> list[str]:
        assert self.session is not None
        settings = settings or self._settings()
        lines = self._preflight()
        config = self.session.project.config
        for name, kind in config.kinds.items():
            selected = self._selected(name, settings)
            if not selected:
                lines.append(f'{name}: nothing to extract')
                continue
            try:
                s = extract_kind(name, kind, selected, self.session.project.tomos, config, log=lines.append)
            except ValueError as e:
                lines.append(str(e))
                continue
            lines.append(f'{name}: wrote {s.written} boxes of {s.box_px} px at {s.pixel_size:.2f} A/px, in {str(s.folder)!r}')
        return lines

    # _schedule: coalesce bursts of changes, from any thread, into one refresh
    def _schedule(self) -> None:
        post(lambda: self._timer.start())

    # _items: picks of a kind that have a current fit
    def _items(self, kind: str) -> list[Item]:
        assert self.session is not None and self.service is not None
        return items(self.session, self.service, kind)

    # _matched: parent geometry for every pick of a kind, empty for a kind with no parent
    def _matched(self, kind: str) -> dict[int, Parent]:
        assert self.session is not None and self.service is not None
        return matched(self.session, self.service, kind)

    # _settings: minimum SNR and include-flagged choice per kind from the export table; read on the GUI thread
    def _settings(self) -> Settings:
        return {n: (-np.inf if s.value() <= _ANY_SNR else s.value(), self._includes[n].isChecked()) for n, s in self._spins.items()}

    # _formats: the export formats that are ticked; read on the GUI thread
    def _formats(self) -> frozenset[str]:
        return frozenset(f for f, box in (('star', self.star_box), ('csv', self.csv_box)) if box.isChecked())

    # _selected: current fits of a kind that pass its SNR and flag settings
    def _selected(self, kind: str, settings: Settings) -> list[Item]:
        min_snr, include = settings[kind]
        return [(p, f) for p, f in self._items(kind) if f.snr >= min_snr and (include or not f.flag)]

    # _preflight: warnings about picks the export will skip
    def _preflight(self) -> list[str]:
        assert self.session is not None
        lines = []
        for name, kind in self.session.project.config.kinds.items():
            kind_items = self._items(name)
            missing = self.session.store.total(name) - len(kind_items)
            if missing:
                lines.append(f'{name}: {missing} picks have no current estimate and are skipped (wait for estimating, or Re-estimate all on the Review tab)')
            orphans = sum('noparent' in f.flag for _, f in kind_items)
            if orphans:
                lines.append(f'{name}: {orphans} picks have no {kind.parent} within {kind.parent_tolerance_a:g} A and are skipped')
        return lines

    # _export: export in the ticked formats, in the background
    def _export(self) -> None:
        formats = self._formats()
        self._run(lambda settings: self.export_all(settings, formats), 'Exporting...')

    # _run: run an export or extraction job in the background; its lines go to stdout and the toast
    def _run(self, job: Callable[[Settings], list[str]], message: str) -> None:
        self._running = True
        self._sync_buttons()
        self.spinner.set_status('running', message)
        settings = self._settings()
        run_in_background(lambda: job(settings), self._logged, lambda error: self._logged([error]))

    # _logged: report job output and unblock the buttons
    def _logged(self, lines: list[str]) -> None:
        self._running = False
        self.spinner.set_status(None)
        self._sync_buttons()
        notify('\n'.join(lines))

    # _sync_buttons: nothing runs twice at once, and Export needs a format ticked
    def _sync_buttons(self) -> None:
        self.export_button.setEnabled(not self._running and bool(self._formats()))
        self.extract_button.setEnabled(not self._running)
