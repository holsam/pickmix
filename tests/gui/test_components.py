'''
pickmix: tests for gui components
'''

# Import external dependencies
import numpy as np, pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QPixmap, QWheelEvent
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

# Import internal pickmix objects
from pickmix.gui.components.canvas import FitView, Marker, SliceCanvas
from pickmix.gui.components.icons import ICON_DIR, icon, tinted
from pickmix.gui.components.images import label_cells, label_image, to_image, to_pixmap
from pickmix.gui.components.range_slider import RangeSlider
from pickmix.gui.components.status import STATUS_STYLE, StatusBadge, fit_status, status_item
from pickmix.gui.components.toast import notify
from pickmix.gui.style import OK
from pickmix.gui.main_window import MainWindow

# STEMS: bundled icons
STEMS: list[str] = [
    'add', 'cached', 'check', 'close', 'create_new_folder', 'crop', 'delete', 'edit', 'error', 'download', 'fit_screen', 'folder_open', 'fullscreen',
    'help', 'left_panel_close', 'left_panel_open', 'logout', 'refresh', 'visibility', 'visibility_off', 'warning',
]

# _canvas: a shown canvas with a 40 x 30 slice at unit zoom
def _canvas(qtbot: QtBot) -> SliceCanvas:
    canvas = SliceCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(200, 200)
    canvas.show()
    canvas.set_image(np.zeros((30, 40), dtype=np.float32), 0.0, 1.0)
    return canvas

# _slider: a 200 px wide slider over 0 to 100 at 20 and 80
def _slider(qtbot: QtBot) -> RangeSlider:
    slider = RangeSlider(0, 100)
    qtbot.addWidget(slider)
    slider.resize(200, 24)
    slider.set_values(20, 80)
    return slider

# _handle_colour: colour of the pixel at a handle centre in a rendered slider
def _handle_colour(slider: RangeSlider, value: int) -> QColor:
    image = slider.grab().toImage()
    return image.pixelColor(round(slider._x(value)), slider.height() // 2)

# _view_pos: viewport position of a scene position
def _view_pos(canvas: SliceCanvas, x: float, y: float) -> QPoint:
    return canvas.mapFromScene(QPointF(x + 0.5, y + 0.5))

# TestCanvas: slice canvas tests
class TestCanvas:
    # test_image: size follows the slice
    def test_image(self, qtbot: QtBot) -> None:
        canvas = _canvas(qtbot)
        assert canvas.has_image and canvas.image_size() == (40, 30)
        canvas.clear()
        assert not canvas.has_image and canvas.marker_ids() == []

    # test_marker_opacity: solid near its slice, faint away from it
    def test_marker_opacity(self, qtbot: QtBot) -> None:
        canvas = _canvas(qtbot)
        canvas.set_markers([Marker(1, 10, 10, 50, 3.0, 'yellow')])
        canvas.set_z(50)
        assert canvas.opacity(1) == 1.0
        canvas.set_z(10)
        assert canvas.opacity(1) < 1.0

    # test_click_empty_adds: pressing on empty image requests a pick at that voxel
    def test_click_empty_adds(self, qtbot: QtBot) -> None:
        canvas = _canvas(qtbot)
        with qtbot.waitSignal(canvas.add_requested) as blocker:
            QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=_view_pos(canvas, 20, 15))
        x, y = blocker.args
        assert abs(x - 20) < 1.5 and abs(y - 15) < 1.5

    # test_click_marker_selects: pressing a marker's core selects it and does not add
    def test_click_marker_selects(self, qtbot: QtBot) -> None:
        canvas = _canvas(qtbot)
        canvas.set_markers([Marker(7, 20, 15, 0, 12.0, 'yellow')])
        added: list[tuple[float, float]] = []
        canvas.add_requested.connect(lambda x, y: added.append((x, y)))
        with qtbot.waitSignal(canvas.marker_clicked) as blocker:
            QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=_view_pos(canvas, 20, 15))
        assert blocker.args == [7] and canvas.selected_id == 7 and added == []

    # test_inside_large_marker_adds: away from the centre, inside the disc, a click still adds
    def test_inside_large_marker_adds(self, qtbot: QtBot) -> None:
        canvas = _canvas(qtbot)
        canvas.set_markers([Marker(7, 20, 15, 0, 12.0, 'yellow')])
        with qtbot.waitSignal(canvas.add_requested):
            QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=_view_pos(canvas, 28, 15))

    # test_drag_moves: press, drag and release on a marker requests a move by the dragged distance
    def test_drag_moves(self, qtbot: QtBot) -> None:
        canvas = _canvas(qtbot)
        canvas.set_markers([Marker(3, 20, 15, 0, 4.0, 'yellow')])
        start, end = _view_pos(canvas, 20, 15), _view_pos(canvas, 25, 12)
        QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas.viewport(), end)
        with qtbot.waitSignal(canvas.move_requested) as blocker:
            QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)
        pick_id, x, y = blocker.args
        assert pick_id == 3 and abs(x - 25) < 1.5 and abs(y - 12) < 1.5

    # test_wheel_scrolls_z: a wheel notch emits one z step
    def test_wheel_scrolls_z(self, qtbot: QtBot) -> None:
        canvas = _canvas(qtbot)
        event = QWheelEvent(
            QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, 120), Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False,
        )
        with qtbot.waitSignal(canvas.z_scrolled) as blocker:
            canvas.wheelEvent(event)
        assert blocker.args == [1]

    # test_select_unknown: selecting a marker that is not drawn clears the selection
    def test_select_unknown(self, qtbot: QtBot) -> None:
        canvas = _canvas(qtbot)
        canvas.set_markers([Marker(1, 5, 5, 0, 3.0, 'yellow')])
        canvas.select(1)
        assert canvas.selected_id == 1
        canvas.select(99)
        assert canvas.selected_id is None

    # test_fit_overlay: the ring shows within the fit's slab, the box within half its width of the fit's slice, and both can be switched off
    def test_fit_overlay(self, qtbot: QtBot) -> None:
        canvas = _canvas(qtbot)
        fit = FitView(cx=20, cy=15, cz=50, ring_px=8.0, box_px=12.0, z_lo=45, z_hi=55)
        canvas.set_markers([Marker(1, 20, 15, 50, 3.0, 'yellow', fit=fit)])
        canvas.set_z(50)
        assert canvas.overlay_visible(1) == (True, True)
        canvas.set_z(58)
        assert canvas.overlay_visible(1) == (False, False)
        canvas.set_z(53)
        assert canvas.overlay_visible(1) == (True, True)
        canvas.set_overlay(rings=False, boxes=True)
        assert canvas.overlay_visible(1) == (False, True)
        assert canvas.overlay_visible(99) == (False, False)

    # test_normal_arrow: a marker with a normal gets an arrow that the overlay switch hides
    def test_normal_arrow(self, qtbot: QtBot) -> None:
        canvas = _canvas(qtbot)
        canvas.set_markers([Marker(1, 20, 15, 0, 4.0, 'lime', normal=(1.0, 0.0)), Marker(2, 10, 10, 0, 4.0, 'lime')])
        assert canvas.normal_visible(1) and not canvas.normal_visible(2)
        canvas.set_overlay(rings=True, boxes=True, normals=False)
        assert not canvas.normal_visible(1)

    # test_fill_covers_canvas: fill zooms in further than fit when the slice and canvas shapes differ
    def test_fill_covers_canvas(self, qtbot: QtBot) -> None:
        canvas = SliceCanvas()
        qtbot.addWidget(canvas)
        canvas.resize(400, 200)
        canvas.show()
        qtbot.waitExposed(canvas)
        canvas.set_image(np.zeros((6, 8), dtype=np.float32), 0.0, 1.0)
        canvas.fit()
        fit_scale = canvas.transform().m11()
        canvas.fill()
        assert canvas.transform().m11() > fit_scale

# TestIcons: icon loading and tinting
class TestIcons:
    # test_bundled: every icon the GUI uses ships
    @pytest.mark.parametrize('stem', STEMS)
    def test_bundled(self, qtbot: QtBot, stem: str) -> None:
        assert (ICON_DIR / f'{stem}.svg').exists() and icon(stem) is not None

    # test_missing: an icon with no file is None
    def test_missing(self) -> None:
        assert icon('no_such_icon') is None and tinted('no_such_icon', '#ff0000') is None

    # test_tinted: opaque pixels take the colour asked for, give or take rounding at the antialiased edge
    def test_tinted(self, qtbot: QtBot) -> None:
        want = QColor(OK).getRgb()[:3]
        image = tinted('check', OK).pixmap(16, 16).toImage()
        opaque = [image.pixelColor(x, y) for x in range(16) for y in range(16) if image.pixelColor(x, y).alpha() > 200]
        assert opaque and all(max(abs(a - b) for a, b in zip(c.getRgb()[:3], want)) <= 4 for c in opaque)

# TestImages: image helpers
class TestImages:
    # test_to_image_stretches: the 1st to 99th percentile fills the 8-bit range
    def test_to_image_stretches(self, qtbot: QtBot) -> None:
        arr = np.linspace(0.0, 1.0, 64 * 64).reshape(64, 64)
        image = to_image(arr)
        assert image.width() == 64 and image.height() == 64 and image.pixelColor(0, 0).red() == 0 and image.pixelColor(63, 63).red() == 255

    # test_to_pixmap_fits: the pixmap fits the square and keeps the aspect
    def test_to_pixmap_fits(self, qtbot: QtBot) -> None:
        pixmap = to_pixmap(np.random.default_rng(0).random((20, 40)), 100)
        assert pixmap.width() == 100 and pixmap.height() == 50

    # test_label_cells_marks_each_cell: each cell's top-left corner is darkened, the cell centre is untouched
    def test_label_cells_marks_each_cell(self, qtbot: QtBot) -> None:
        grid, box, pad = 2, 40, 2
        size = grid * (box + pad) + pad
        base = to_image(np.full((size, size), 200.0) + np.random.default_rng(1).random((size, size)))
        out = label_cells(base, ['1/1', '1/2', '2/1', '2/2'], grid, pad)
        assert out.size() == base.size()
        for row in range(grid):
            for col in range(grid):
                x, y = pad + col * (box + pad), pad + row * (box + pad)
                assert out.pixelColor(x + 1, y + 1).red() < base.pixelColor(x + 1, y + 1).red()
                assert out.pixelColor(x + box - 2, y + box - 2) == base.pixelColor(x + box - 2, y + box - 2).toRgb()

    # test_label_cells_stay_in_their_cell: a long label is clipped inside its own cell, never spilling into the padding or the next cell
    def test_label_cells_stay_in_their_cell(self, qtbot: QtBot) -> None:
        grid, box, pad = 2, 60, 2
        size = grid * (box + pad) + pad
        base = to_image(np.full((size, size), 200.0) + np.random.default_rng(1).random((size, size)))
        out = label_cells(base, ['12 (a_very_long_tomogram_name_indeed)'] * 4, grid, pad)
        for row in range(grid):
            for col in range(grid):
                x, y = pad + col * (box + pad), pad + row * (box + pad)
                # a label drawn in, then the padding column just right of the cell is untouched
                assert out.pixelColor(x + 1, y + 1).red() < base.pixelColor(x + 1, y + 1).red()
                for dy in range(0, 10):
                    assert out.pixelColor(x + box, y + dy) == base.pixelColor(x + box, y + dy).toRgb()

# TestRangeSlider: two-handle slider
class TestRangeSlider:
    # test_solid_handles: an unfocused handle is filled with the highlight colour, like the span
    def test_solid_handles(self, qtbot: QtBot) -> None:
        slider = _slider(qtbot)
        slider.show()
        want = slider.palette().highlight().color()
        got = _handle_colour(slider, 20)
        assert all(abs(a - b) <= 2 for a, b in zip((got.red(), got.green(), got.blue()), (want.red(), want.green(), want.blue())))

    # test_clamps: values stay inside the range and low never passes high
    def test_clamps(self, qtbot: QtBot) -> None:
        slider = _slider(qtbot)
        slider.set_values(-5, 500)
        assert slider.values() == (0, 100)
        slider.set_values(70, 30)
        assert slider.values() == (70, 70)

    # test_silent_by_default: set_values only announces when asked
    def test_silent_by_default(self, qtbot: QtBot) -> None:
        slider = _slider(qtbot)
        with qtbot.assertNotEmitted(slider.valueChanged):
            slider.set_values(10, 90)
        with qtbot.waitSignal(slider.valueChanged) as blocker:
            slider.set_values(30, 90, emit=True)
        assert blocker.args == [30, 90]

    # test_keys: arrows move the active handle, Up and Down switch handle
    def test_keys(self, qtbot: QtBot) -> None:
        slider = _slider(qtbot)
        QTest.keyClick(slider, Qt.Key.Key_Right)
        assert slider.values() == (21, 80)
        QTest.keyClick(slider, Qt.Key.Key_Up)
        QTest.keyClick(slider, Qt.Key.Key_PageDown)
        assert slider.values() == (21, 70)

    # test_mouse_grabs_nearest_handle: pressing near a handle moves that one
    def test_mouse_grabs_nearest_handle(self, qtbot: QtBot) -> None:
        slider = _slider(qtbot)
        QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=QPoint(round(slider._x(75)), 12))
        QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=QPoint(round(slider._x(75)), 12))
        low, high = slider.values()
        assert low == 20 and abs(high - 75) <= 1

# TestStatus: status cells and badges
class TestStatus:
    # test_item_icons: each status gives a cell with an icon and its tip, None gives an empty cell
    @pytest.mark.parametrize('status', list(STATUS_STYLE))
    def test_item_icons(self, qtbot: QtBot, status: str) -> None:
        item = status_item(status, 'why')
        assert not item.icon().isNull() and item.toolTip() == 'why' and item.text() == ''
        blank = status_item(None)
        assert blank.icon().isNull() and blank.text() == ''

    # test_item_falls_back: without the icon file the cell shows a glyph
    def test_item_falls_back(self, qtbot: QtBot, monkeypatch) -> None:
        monkeypatch.setattr('pickmix.gui.components.status.tinted', lambda stem, colour, size=16: None)
        assert status_item('ok').text() == '✓' and status_item('error').text() == '✖'

    # test_badge_spins_only_when_running: the timer runs for running and stops for anything else
    def test_badge_spins_only_when_running(self, qtbot: QtBot) -> None:
        badge = StatusBadge()
        qtbot.addWidget(badge)
        badge.set_status('running')
        assert badge._timer.isActive()
        first = badge.pixmap().toImage()
        qtbot.waitUntil(lambda: badge.pixmap().toImage() != first, timeout=2000)
        badge.set_status('ok', 'fine')
        assert not badge._timer.isActive() and badge.toolTip() == 'fine'
        badge.set_status(None)
        assert badge.pixmap().isNull() and badge.text() == ''

    # test_fit_status: no current fit runs, an error flag errors, any other flag warns, none is ok
    def test_fit_status(self) -> None:
        assert fit_status('missing', '') == 'running' and fit_status('stale', 'x') == 'running'
        assert fit_status('ok', 'error') == 'error' and fit_status('ok', 'noparent,error') == 'error'
        assert fit_status('ok', 'noparent') == 'warn' and fit_status('ok', '') == 'ok'

# TestLabelImage: single image labels
class TestLabelImage:
    # test_corner_only: the label changes the top-left corner and leaves the opposite corner alone, whatever its length
    def test_corner_only(self, qtbot: QtBot) -> None:
        base = QPixmap(100, 100)
        base.fill(QColor('white'))
        for text in ('XY', 'a very long label that cannot fit in the image at all'):
            out = label_image(base, text).toImage()
            assert out.size() == base.size() and out.pixelColor(6, 6) != QColor('white') and out.pixelColor(95, 95) == QColor('white')

# TestToast: toast and notify
class TestToast:
    # test_notify_prints_and_shows: the message goes to stdout and the toast
    def test_notify_prints_and_shows(self, qtbot: QtBot, capsys) -> None:
        window = MainWindow()
        qtbot.addWidget(window)
        window.show()
        notify('Saved 3 files')
        assert 'Saved 3 files' in capsys.readouterr().out
        assert window.toast.isVisible() and window.toast.text() == 'Saved 3 files'

    # test_long_message_cut: only the first lines show, stdout has them all
    def test_long_message_cut(self, qtbot: QtBot, capsys) -> None:
        window = MainWindow()
        qtbot.addWidget(window)
        window.show()
        notify('\n'.join(f'line {i}' for i in range(6)))
        assert window.toast.text() == 'line 0\nline 1\nline 2\n...'
        assert 'line 5' in capsys.readouterr().out

    # test_saved_gets_a_tick: a saved message starts with a green tick and is escaped, a plain one has no tick, and stdout never has it
    def test_saved_gets_a_tick(self, qtbot: QtBot, capsys) -> None:
        window = MainWindow()
        qtbot.addWidget(window)
        window.show()
        notify('<b>x</b>', saved=True)
        assert '✓' in window.toast.text() and '&lt;b&gt;' in window.toast.text() and OK in window.toast.text()
        notify('<b>x</b>')
        assert window.toast.text() == '<b>x</b>'
        assert '✓' not in capsys.readouterr().out

    # test_hides_itself: the toast goes away after its time
    def test_hides_itself(self, qtbot: QtBot) -> None:
        window = MainWindow()
        qtbot.addWidget(window)
        window.show()
        window.toast.show_message('bye', ms=50)
        qtbot.waitUntil(lambda: not window.toast.isVisible(), timeout=2000)

    # test_without_window: notify only prints when no toast exists
    def test_without_window(self, capsys) -> None:
        import pickmix.gui.components.toast as toast
        toast._toast = None
        notify('plain')
        assert 'plain' in capsys.readouterr().out
