'''
pickmix: zoomed movable crop of pick
'''

# Import external dependencies
import math, numpy as np
from dataclasses import dataclass
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QMouseEvent, QPainter, QPen, QPixmap, QResizeEvent
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsLineItem, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView

# Import internal pickmix objects
from pickmix.gui.components.images import to_image
from pickmix.gui.style import WELL_BG

# _HIT_PX: screen distance from the centre dot that counts as grabbing it
_HIT_PX: float = 8.0

# _DRAG_PX: screen distance before a press becomes a drag
_DRAG_PX: float = 3.0

# _FILL_ALPHA: opacity of the hatching inside the box, out of 255
_FILL_ALPHA: int = 110

# Patch: a crop of one slice and where pick and box sit
@dataclass(frozen=True)
class Patch:
    pixels: np.ndarray
    # voxel (x, y) of the crop's top-left pixel
    origin: tuple[int, int]
    pick_id: int
    # pick position in voxels, where the dot goes
    pick: tuple[float, float]
    # box centre in voxels and box edge in pixels
    box_centre: tuple[float, float]
    box_px: float
    colour: str
    # tomogram width and height in voxels
    bounds: tuple[int, int]
    # direction of a filament in degrees from the x axis towards y, drawn through the box centre
    psi_deg: float | None = None

# PatchCanvas: a crop of a slice with pick box as translucent hatched square and pick as a small dot
class PatchCanvas(QGraphicsView):
    # move_requested: dot or box dragged and released, pick id and new voxel x, y
    move_requested = Signal(int, float, float)

    # __init__: empty scene, no scroll bars
    def __init__(self, size: int) -> None:
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap: QGraphicsPixmapItem = self._scene.addPixmap(QPixmap())
        self._box: QGraphicsRectItem | None = None
        self._dot: QGraphicsEllipseItem | None = None
        self._axis: QGraphicsLineItem | None = None
        self._patch: Patch | None = None
        self._drag: QPointF | None = None
        self._moved = False
        self._offset = QPointF(0, 0)
        self.setFixedSize(size, size)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QColor(WELL_BG))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)

    # has_patch: whether a crop is showing
    @property
    def has_patch(self) -> bool:
        return self._patch is not None

    # patch: the crop showing, None if none
    @property
    def patch(self) -> Patch | None:
        return self._patch

    # box_rect: the box in scene pixels as (x, y, width, height), None with no crop
    def box_rect(self) -> tuple[float, float, float, float] | None:
        if self._box is None:
            return None
        rect = self._box.rect().translated(self._box.pos())
        return rect.x(), rect.y(), rect.width(), rect.height()
    
    # axis_angle: the direction in degrees of the filament axis drawn, from the x axis towards y, None if there is none
    def axis_angle(self) -> float | None:
        return None if self._axis is None else math.degrees(math.atan2(self._axis.line().dy(), self._axis.line().dx())) % 180.0

    # dot_position: the dot in scene pixels, None with no crop
    def dot_position(self) -> tuple[float, float] | None:
        return None if self._dot is None else (self._dot.pos().x(), self._dot.pos().y())

    # set_patch: show a crop with box over it and pick as a dot
    def set_patch(self, patch: Patch) -> None:
        self._patch = patch
        self._drag, self._moved, self._offset = None, False, QPointF(0, 0)
        self._pixmap.setPixmap(QPixmap.fromImage(to_image(patch.pixels)))
        self._scene.setSceneRect(0, 0, patch.pixels.shape[1], patch.pixels.shape[0])
        for item in (self._box, self._dot, self._axis):
            if item is not None:
                self._scene.removeItem(item)
        self._axis = None
        colour = QColor(patch.colour)
        half = patch.box_px / 2
        self._box = QGraphicsRectItem(-half, -half, 2 * half, 2 * half)
        self._box.setBrush(QBrush(QColor(colour.red(), colour.green(), colour.blue(), _FILL_ALPHA), Qt.BrushStyle.BDiagPattern))
        pen = QPen(colour)
        pen.setCosmetic(True)
        pen.setWidth(1)
        self._box.setPen(pen)
        self._box.setZValue(1)
        self._dot = QGraphicsEllipseItem(-3, -3, 6, 6)
        self._dot.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self._dot.setBrush(QColor('white'))
        self._dot.setPen(QPen(colour))
        self._dot.setZValue(2)
        self._scene.addItem(self._box)
        self._scene.addItem(self._dot)
        if patch.psi_deg is not None:
            reach = patch.box_px / 2
            dx, dy = math.cos(math.radians(patch.psi_deg)) * reach, math.sin(math.radians(patch.psi_deg)) * reach
            self._axis = QGraphicsLineItem(-dx, -dy, dx, dy)
            axis_pen = QPen(colour)
            axis_pen.setCosmetic(True)
            axis_pen.setWidth(2)
            self._axis.setPen(axis_pen)
            self._axis.setZValue(1)
            self._scene.addItem(self._axis)
        self._place()
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    # clear: remove crop
    def clear(self) -> None:
        self._patch = None
        self._pixmap.setPixmap(QPixmap())
        for item in (self._box, self._dot, self._axis):
            if item is not None:
                self._scene.removeItem(item)
        self._box = self._dot = self._axis = None

    # mousePressEvent: grab dot or box
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._patch is not None and self._hit(self.mapToScene(event.position().toPoint())):
            self._drag, self._moved = self.mapToScene(event.position().toPoint()), False
        else:
            super().mousePressEvent(event)

    # mouseMoveEvent: carry dot and box
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag is None:
            super().mouseMoveEvent(event)
            return
        delta = self.mapToScene(event.position().toPoint()) - self._drag
        if self._moved or math.hypot(delta.x(), delta.y()) * self.transform().m11() > _DRAG_PX:
            self._moved, self._offset = True, delta
            self._place()

    # mouseReleaseEvent: a drag asks to move the pick; a press without one does nothing
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag is not None:
            patch, moved, offset = self._patch, self._moved, self._offset
            self._drag, self._moved = None, False
            if patch is not None and moved:
                w, h = patch.bounds
                x = min(max(patch.pick[0] + offset.x(), 0.0), max(w - 1, 0))
                y = min(max(patch.pick[1] + offset.y(), 0.0), max(h - 1, 0))
                self.move_requested.emit(patch.pick_id, x, y)
        else:
            super().mouseReleaseEvent(event)

    # resizeEvent: keep whole crop in view
    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._patch is not None:
            self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    # _scene_pos: where a voxel position falls in crop, with half pixel that puts a voxel's centre mid-pixel
    def _scene_pos(self, x: float, y: float) -> QPointF:
        assert self._patch is not None
        return QPointF(x - self._patch.origin[0] + 0.5, y - self._patch.origin[1] + 0.5)

    # _place: put box and dot where patch says, plus any drag in progress
    def _place(self) -> None:
        assert self._patch is not None and self._box is not None and self._dot is not None
        self._box.setPos(self._scene_pos(*self._patch.box_centre) + self._offset)
        self._dot.setPos(self._scene_pos(*self._patch.pick) + self._offset)
        if self._axis is not None:
            self._axis.setPos(self._box.pos())

    # _hit: whether a scene position is on dot or inside box
    def _hit(self, pos: QPointF) -> bool:
        assert self._box is not None and self._dot is not None
        reach = _HIT_PX / self.transform().m11()
        box = QRectF(self._box.rect()).translated(self._box.pos())
        return box.contains(pos) or math.hypot(pos.x() - self._dot.pos().x(), pos.y() - self._dot.pos().y()) <= reach
