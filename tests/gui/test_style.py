'''
pickmix: tests for shared GUI styling
'''

# Import external dependencies
import pytest
from pytestqt.qtbot import QtBot
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

# Import internal pickmix objects
from pickmix.gui.kinds_tab import KindsTab
from pickmix.gui.pick_tab import PickTab
from pickmix.gui.project_tab import ProjectTab
from pickmix.gui.review_tab import ReviewTab
from pickmix.gui.style import MARGIN, SPACING, body_pt, form_label, heading, help_marker, hint, icon, standardise, tidy, title

# TestStyle: shared text levels and spacing
class TestStyle:
    # test_levels: title is larger than heading, heading larger than body, body larger than hint
    def test_levels(self, qtbot: QtBot) -> None:
        body = QLabel('x')
        sizes = [w.font().pointSizeF() for w in (title('x'), heading('x'), body, hint('x'))]
        assert sizes == sorted(sizes, reverse=True) and len(set(sizes)) == 4
        assert title('x').font().bold() and not hint('x').font().bold()

    # test_tidy: margins and spacing come from the constants
    def test_tidy(self, qtbot: QtBot) -> None:
        layout = QVBoxLayout()
        tidy(layout)
        assert layout.contentsMargins().left() == MARGIN and layout.spacing() == SPACING

    # test_form_label: a label column entry is the title, a marker and a colon, with the tip on the title and the marker
    def test_form_label(self, qtbot: QtBot) -> None:
        head = form_label('Radius (Å)', 'How big.')
        qtbot.addWidget(head)
        labels = head.findChildren(QLabel)
        assert labels[0].text() == 'Radius (Å)' and labels[0].toolTip() == 'How big.'
        assert labels[1].toolTip() == 'How big.' and labels[-1].text() == ':'

    # test_help_marker_falls_back: without the icon file the marker reads (?)
    def test_help_marker_falls_back(self, qtbot: QtBot, monkeypatch) -> None:
        monkeypatch.setattr('pickmix.gui.style.icon', lambda stem: None)
        marker = help_marker('tip')
        assert marker.text() == '(?)' and marker.toolTip() == 'tip'

    # test_icon_missing: an icon with no file is None so callers can fall back to text
    def test_icon_missing(self) -> None:
        assert icon('no_such_icon') is None

    # test_standardise: widgets with a smaller native font are given the body size
    def test_standardise(self, qtbot: QtBot) -> None:
        app = QApplication.instance()
        standardise(app)
        try:
            sheet = app.styleSheet()
            assert all(name in sheet for name in ('QGroupBox', 'QToolButton', 'QHeaderView'))
            assert f'font-size: {body_pt()}pt' in sheet
        finally:
            app.setStyleSheet('')

    # test_tabs_use_shared_spacing: every tab's top-level layout uses the shared margin and spacing
    @pytest.mark.parametrize('cls', [ProjectTab, KindsTab, PickTab, ReviewTab])
    def test_tabs_use_shared_spacing(self, qtbot: QtBot, cls: type[QWidget]) -> None:
        tab = cls()
        qtbot.addWidget(tab)
        layout = tab.layout()
        assert layout.contentsMargins().left() == MARGIN and layout.spacing() == SPACING
