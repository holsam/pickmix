'''
pickmix: tests for icon loading
'''

# Import external dependencies
import pytest
from pytestqt.qtbot import QtBot

# Import internal pickmix objects
from pickmix.gui.components.icons import ICON_DIR, icon, tinted

# STEMS: bundled icons
STEMS: list[str] = [
    'add', 'cached', 'check', 'close', 'create_new_folder', 'delete', 'edit', 'error', 'fit_screen', 'folder_open', 'fullscreen',
    'help', 'left_panel_close', 'left_panel_open', 'logout', 'refresh', 'visibility', 'visibility_off', 'warning',
]

# TestIcons: icon loading and tinting
class TestIcons:
    # test_bundled: every icon the GUI uses ships
    @pytest.mark.parametrize('stem', STEMS)
    def test_bundled(self, qtbot: QtBot, stem: str) -> None:
        assert (ICON_DIR / f'{stem}.svg').exists() and icon(stem) is not None

    # test_missing: an icon with no file is None
    def test_missing(self) -> None:
        assert icon('no_such_icon') is None and tinted('no_such_icon', '#ff0000') is None

    # test_tinted: opaque pixels take the colour asked for
    def test_tinted(self, qtbot: QtBot) -> None:
        image = tinted('check', '#2e9e44').pixmap(16, 16).toImage()
        opaque = [image.pixelColor(x, y) for x in range(16) for y in range(16) if image.pixelColor(x, y).alpha() > 200]
        assert opaque and all(c.name() == '#2e9e44' for c in opaque)
