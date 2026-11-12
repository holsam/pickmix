'''
pickmix: template matching pane
'''

# Import external dependencies
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout

# Import internal pickmix objects
from pickmix.matcher import MatchService

# _STEPS: positions on the score slider, one per hundredth
_STEPS: int = 100

# MatchPane: scan for a kind's template, set how good a match to show, and accept or reject the candidates
class MatchPane(QGroupBox):
    # scan_requested, stop_requested: the buttons
    scan_requested = Signal()
    stop_requested = Signal()
    # accept_requested, reject_requested, accept_all_requested: act on the selected candidate, or on all those shown in this tomogram
    accept_requested = Signal()
    reject_requested = Signal()
    accept_all_requested = Signal()
    # threshold_changed: the lowest score shown was changed
    threshold_changed = Signal()

    # __init__: build the controls
    def __init__(self) -> None:
        super().__init__('Match')
        self.matcher: MatchService | None = None
        self.scan_button = QPushButton('Scan')
        self.stop_button = QPushButton('Stop')
        self.score_slider = QSlider(Qt.Orientation.Horizontal)
        self.score_slider.setRange(1, _STEPS - 1)
        self.score_label = QLabel()
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.accept_button = QPushButton('Accept (A)')
        self.reject_button = QPushButton('Reject')
        self.accept_all_button = QPushButton('Accept all shown')
        for button in (self.scan_button, self.stop_button, self.accept_button, self.reject_button, self.accept_all_button):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.score_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.scan_button.setToolTip("Average this kind's picks into a template and look for it in every tomogram")
        self.accept_button.setToolTip('Turn the selected candidate into a pick')
        self.reject_button.setToolTip('Hide the selected candidate; later scans will not offer it again (Delete)')
        self.accept_all_button.setToolTip('Turn every candidate shown in this tomogram into a pick')
        self.score_slider.setToolTip('Lowest correlation score shown')
        scan_row = QHBoxLayout()
        scan_row.addWidget(self.scan_button)
        scan_row.addWidget(self.stop_button)
        pick_row = QHBoxLayout()
        pick_row.addWidget(self.accept_button)
        pick_row.addWidget(self.reject_button)
        layout = QVBoxLayout(self)
        layout.addLayout(scan_row)
        layout.addWidget(self.status)
        layout.addWidget(self.score_label)
        layout.addWidget(self.score_slider)
        layout.addLayout(pick_row)
        layout.addWidget(self.accept_all_button)
        self.scan_button.clicked.connect(self.scan_requested)
        self.stop_button.clicked.connect(self.stop_requested)
        self.accept_button.clicked.connect(self.accept_requested)
        self.reject_button.clicked.connect(self.reject_requested)
        self.accept_all_button.clicked.connect(self.accept_all_requested)
        self.score_slider.valueChanged.connect(self._moved)
        self.set_matcher(None, 0.2)

    # set_matcher: use a scan service and start the score slider at its minimum, or none
    def set_matcher(self, matcher: MatchService | None, min_score: float) -> None:
        self.matcher = matcher
        self.score_slider.blockSignals(True)
        self.score_slider.setValue(round(min_score * _STEPS))
        self.score_slider.blockSignals(False)
        self.refresh(kind=None, picks=0, shown=0, total=0, selected=False)

    # min_score: the lowest score shown
    def min_score(self) -> float:
        return self.score_slider.value() / _STEPS

    # refresh: enable what applies and say what the scan is doing; shown and total count the kind's candidates in this tomogram and everywhere, picks the kind's picks
    def refresh(self, *, kind: str | None, picks: int, shown: int, total: int, selected: bool) -> None:
        busy = self.matcher is not None and self.matcher.busy
        self.score_label.setText(f'Score at least {self.min_score():.2f}')
        self.scan_button.setText(f'Scan {kind}' if kind and not busy else 'Scan')
        self.scan_button.setEnabled(self.matcher is not None and kind is not None and picks > 0 and not busy)
        self.stop_button.setEnabled(busy)
        self.accept_button.setEnabled(selected)
        self.reject_button.setEnabled(selected)
        self.accept_all_button.setEnabled(shown > 0)
        self.status.setText(self._status(kind, picks, shown, total, busy))

    # _status: status (under buttons)
    def _status(self, kind: str | None, picks: int, shown: int, total: int, busy: bool) -> str:
        matcher = self.matcher
        if matcher is None or kind is None:
            return ''
        if busy:
            return f'Scanning {matcher.kind}: {matcher.done} of {matcher.total} tomograms'
        if matcher.last_error:
            return f'Scan failed: {matcher.last_error}'
        if picks == 0:
            return f'Pick some {kind} to make a template'
        note = f' ({len(matcher.skipped)} skipped, other pixel size)' if matcher.skipped else ''
        return f'{shown} shown here, {total} in all{note}'

    # _moved: the slider moved
    def _moved(self, _value: int) -> None:
        self.score_label.setText(f'Score at least {self.min_score():.2f}')
        self.threshold_changed.emit()
