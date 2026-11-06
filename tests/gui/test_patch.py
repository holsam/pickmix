'''
pickmix: tests for the pick patch canvas
'''

# Import external dependencies
import numpy as np
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

# Import internal pickmix objects
from pickmix.gui.components.patch import Patch, PatchCanvas

# _patch: a 60 x 60 crop whose top-left pixel is voxel (100, 200), with a pick at (130, 230) and a 20 pixel box centred 2 voxels right of it
def _patch(**changes: object) -> Patch:
    base = dict(
        pixels=np.random.default_rng(0).random((60, 60)).astype(np.float32), origin=(100, 200), pick_id=7,
        pick=(130.0, 230.0), box_centre=(132.0, 230.0), box_px=20.0, colour='yellow', bounds=(500, 500),
    )
    return Patch(**{**base, **changes})

# _canvas: a shown 240 px canvas with a patch, at 4 screen pixels per voxel
def _canvas(qtbot: QtBot, patch: Patch | None = None) -> PatchCanvas:
    canvas = PatchCanvas(240)
    qtbot.addWidget(canvas)
    canvas.show()
    canvas.set_patch(patch or _patch())
    return canvas

# _view_pos: viewport position of a voxel position
def _view_pos(canvas: PatchCanvas, patch: Patch, x: float, y: float) -> QPoint:
    return canvas.mapFromScene(QPointF(x - patch.origin[0] + 0.5, y - patch.origin[1] + 0.5))

# TestPatchCanvas: patch canvas tests
class TestPatchCanvas:
    # test_geometry: box and dot sit at their voxel positions within the crop
    def test_geometry(self, qtbot: QtBot) -> None:
        canvas = _canvas(qtbot)
        assert canvas.has_patch
        assert canvas.box_rect() == (22.5, 20.5, 20.0, 20.0)
        assert canvas.dot_position() == (30.5, 30.5)

    # test_drag_dot: dragging the dot asks to move the pick by the dragged distance
    def test_drag_dot(self, qtbot: QtBot) -> None:
        patch = _patch()
        canvas = _canvas(qtbot, patch)
        start, end = _view_pos(canvas, patch, 130, 230), _view_pos(canvas, patch, 135, 227)
        QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas.viewport(), end)
        assert abs(canvas.dot_position()[0] - 35.5) < 0.5 and abs(canvas.box_rect()[0] - (37.5 - 10)) < 0.5
        with qtbot.waitSignal(canvas.move_requested) as blocker:
            QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)
        pick_id, x, y = blocker.args
        assert pick_id == 7 and abs(x - 135) < 0.5 and abs(y - 227) < 0.5

    # test_drag_box_body: a press inside the box away from the dot also drags
    def test_drag_box_body(self, qtbot: QtBot) -> None:
        patch = _patch()
        canvas = _canvas(qtbot, patch)
        start, end = _view_pos(canvas, patch, 138, 236), _view_pos(canvas, patch, 140, 240)
        QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas.viewport(), end)
        with qtbot.waitSignal(canvas.move_requested) as blocker:
            QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)
        _, x, y = blocker.args
        assert abs(x - 132) < 0.5 and abs(y - 234) < 0.5

    # test_press_outside_does_nothing: a press off the box and dot starts no drag
    def test_press_outside_does_nothing(self, qtbot: QtBot) -> None:
        patch = _patch()
        canvas = _canvas(qtbot, patch)
        start, end = _view_pos(canvas, patch, 105, 205), _view_pos(canvas, patch, 110, 210)
        with qtbot.assertNotEmitted(canvas.move_requested):
            QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(canvas.viewport(), end)
            QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)
        assert canvas.dot_position() == (30.5, 30.5)

    # test_click_without_drag: pressing and releasing on the dot asks for nothing
    def test_click_without_drag(self, qtbot: QtBot) -> None:
        patch = _patch()
        canvas = _canvas(qtbot, patch)
        pos = _view_pos(canvas, patch, 130, 230)
        with qtbot.assertNotEmitted(canvas.move_requested):
            QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=pos)

    # test_drag_clamps_to_tomogram: a drag past the tomogram edge stops at the edge
    def test_drag_clamps_to_tomogram(self, qtbot: QtBot) -> None:
        patch = _patch(origin=(0, 0), pick=(5.0, 5.0), box_centre=(5.0, 5.0), bounds=(40, 30))
        canvas = _canvas(qtbot, patch)
        start, end = _view_pos(canvas, patch, 5, 5), _view_pos(canvas, patch, -20, 55)
        QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas.viewport(), end)
        with qtbot.waitSignal(canvas.move_requested) as blocker:
            QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)
        _, x, y = blocker.args
        assert x == 0.0 and y == 29.0

    # test_new_patch_replaces_old: setting a patch again leaves one box and one dot, and a drag in progress is dropped
    def test_new_patch_replaces_old(self, qtbot: QtBot) -> None:
        patch = _patch()
        canvas = _canvas(qtbot, patch)
        QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=_view_pos(canvas, patch, 130, 230))
        QTest.mouseMove(canvas.viewport(), _view_pos(canvas, patch, 140, 240))
        canvas.set_patch(_patch(box_px=30.0))
        assert canvas.box_rect()[2] == 30.0 and canvas.dot_position() == (30.5, 30.5)
        assert len(canvas.scene().items()) == 3

    # test_clear: clearing removes the box and dot and stops drags
    def test_clear(self, qtbot: QtBot) -> None:
        canvas = _canvas(qtbot)
        canvas.clear()
        assert not canvas.has_patch and canvas.box_rect() is None and canvas.dot_position() is None
        QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
