'''
pickmix: tests for the slice canvas
'''

# Import external dependencies
import numpy as np
from pytestqt.qtbot import QtBot
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest

# Import internal pickmix objects
from pickmix.gui.canvas import FitView, Marker, SliceCanvas

# _canvas: a shown canvas with a 40 x 30 slice at unit zoom
def _canvas(qtbot: QtBot) -> SliceCanvas:
    canvas = SliceCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(200, 200)
    canvas.show()
    canvas.set_image(np.zeros((30, 40), dtype=np.float32), 0.0, 1.0)
    return canvas

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
