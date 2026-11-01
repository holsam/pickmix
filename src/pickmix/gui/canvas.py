'''
pickmix: CPU-rendered slice canvas with pick markers
'''

# Import external dependencies
import math, numpy as np
from dataclasses import dataclass
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsScene, QGraphicsView

# _HIT_PX: screen distance from a marker centre that counts as clicking it
_HIT_PX: float = 6.0

# _FAINT: opacity of a marker away from its own slice
_FAINT: float = 0.3

# _DRAG_PX: screen distance before a press on a marker becomes a drag
_DRAG_PX: float = 3.0

# Marker: a pick as the canvas draws it; x, y in voxels, z the slice it was picked on
@dataclass(frozen=True)
class Marker:
    id: int
    x: float
    y: float
    z: float
    radius_px: float
    colour: str

# SliceCanvas: one slice plus markers; emits requests, never edits picks itself
class SliceCanvas(QGraphicsView):
    # add_requested: left click on empty image, in voxel x, y
    add_requested = Signal(float, float)
    # move_requested: marker dragged and released, pick id and new voxel x, y
    move_requested = Signal(int, float, float)
    # marker_clicked: marker pressed and released without moving
    marker_clicked = Signal(int)
    # z_scrolled: wheel steps, positive is up
    z_scrolled = Signal(int)

    # __init__: empty scene
    def __init__(self) -> None:
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap = self._scene.addPixmap(QPixmap())
        self._slice: np.ndarray | None = None
        self._window = (0.0, 1.0)
        self._invert = False
        self._z = 0.0
        self._markers: dict[int, Marker] = {}
        self._items: dict[int, QGraphicsEllipseItem] = {}
        self.selected_id: int | None = None
        self._drag: tuple[int, QPointF] | None = None
        self._drag_moved = False
        self._pan: QPointF | None = None
        self._wheel = 0
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QColor(20, 20, 20))
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

    # has_image: whether a slice is showing
    @property
    def has_image(self) -> bool:
        return self._slice is not None

    # image_size: (width, height) of the slice in pixels, (0, 0) if none
    def image_size(self) -> tuple[int, int]:
        return (0, 0) if self._slice is None else (self._slice.shape[1], self._slice.shape[0])

    # marker_ids: ids of the markers drawn
    def marker_ids(self) -> list[int]:
        return sorted(self._markers)

    # opacity: the opacity a marker is drawn with
    def opacity(self, marker_id: int) -> float:
        return self._items[marker_id].opacity()

    # set_image: show a slice windowed between lo and hi
    def set_image(self, arr: np.ndarray, lo: float, hi: float, *, invert: bool = False) -> None:
        self._slice = arr
        self._window = (lo, hi)
        self._invert = invert
        self._render()

    # set_window: change the window of the slice already showing
    def set_window(self, lo: float, hi: float, *, invert: bool = False) -> None:
        self._window = (lo, hi)
        self._invert = invert
        if self._slice is not None:
            self._render()

    # set_z: slice number shown, which sets how solid each marker is
    def set_z(self, z: float) -> None:
        self._z = z
        self._restyle()

    # set_markers: replace all markers
    def set_markers(self, markers: list[Marker]) -> None:
        for item in self._items.values():
            self._scene.removeItem(item)
        self._markers = {m.id: m for m in markers}
        self._items = {}
        for m in markers:
            ring = QGraphicsEllipseItem(-m.radius_px, -m.radius_px, 2 * m.radius_px, 2 * m.radius_px)
            ring.setPos(m.x + 0.5, m.y + 0.5)
            ring.setZValue(1)
            dot = QGraphicsEllipseItem(-2, -2, 4, 4, ring)
            dot.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIgnoresTransformations)
            dot.setBrush(QColor(m.colour))
            dot.setPen(QPen(Qt.PenStyle.NoPen))
            self._scene.addItem(ring)
            self._items[m.id] = ring
        if self.selected_id not in self._markers:
            self.selected_id = None
        self._restyle()

    # select: highlight one marker, or none
    def select(self, marker_id: int | None) -> None:
        self.selected_id = marker_id if marker_id in self._markers else None
        self._restyle()

    # clear: remove the slice and every marker, for a tomogram change
    def clear(self) -> None:
        self._slice = None
        self._pixmap.setPixmap(QPixmap())
        self.set_markers([])

    # fit: zoom to show the whole slice
    def fit(self) -> None:
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    # mousePressEvent: pan, select or drag a marker, or request a new pick
    def mousePressEvent(self, event: QMouseEvent) -> None:
        pos = self.mapToScene(event.position().toPoint())
        if event.button() == Qt.MouseButton.RightButton:
            self._pan = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif event.button() == Qt.MouseButton.LeftButton:
            hit = self._marker_at(pos)
            if hit is not None:
                self.select(hit)
                self._drag, self._drag_moved = (hit, pos), False
            elif self._slice is not None and self._inside(pos):
                self.add_requested.emit(pos.x() - 0.5, pos.y() - 0.5)
        else:
            super().mousePressEvent(event)

    # mouseMoveEvent: pan, or drag the pressed marker
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._pan is not None:
            delta = event.position() - self._pan
            self._pan = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
        elif self._drag is not None:
            pick_id, start = self._drag
            pos = self.mapToScene(event.position().toPoint())
            delta = pos - start
            if self._drag_moved or math.hypot(delta.x(), delta.y()) * self.transform().m11() > _DRAG_PX:
                self._drag_moved = True
                m = self._markers[pick_id]
                self._items[pick_id].setPos(m.x + 0.5 + delta.x(), m.y + 0.5 + delta.y())
        else:
            super().mouseMoveEvent(event)

    # mouseReleaseEvent: finish a pan, or finish a marker press as a click or a move
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton and self._pan is not None:
            self._pan = None
            self.unsetCursor()
        elif event.button() == Qt.MouseButton.LeftButton and self._drag is not None:
            pick_id, start = self._drag
            self._drag = None
            pos = self.mapToScene(event.position().toPoint())
            if self._drag_moved:
                m = self._markers[pick_id]
                w, h = self.image_size()
                x = min(max(m.x + pos.x() - start.x(), 0.0), max(w - 1, 0))
                y = min(max(m.y + pos.y() - start.y(), 0.0), max(h - 1, 0))
                self.move_requested.emit(pick_id, x, y)
            else:
                self.marker_clicked.emit(pick_id)
        else:
            super().mouseReleaseEvent(event)

    # wheelEvent: zoom with Ctrl or Cmd, else scroll z
    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
            factor = 1.25 ** (event.angleDelta().y() / 120)
            self.scale(factor, factor)
            return
        self._wheel += event.angleDelta().y()
        steps = int(self._wheel / 120)
        if steps:
            self._wheel -= steps * 120
            self.z_scrolled.emit(steps)

    # _render: window the slice to 8 bits and show it
    def _render(self) -> None:
        lo, hi = self._window
        scaled = np.clip((self._slice - lo) * (255.0 / max(hi - lo, 1e-6)), 0, 255).astype(np.uint8)
        if self._invert:
            scaled = 255 - scaled
        scaled = np.ascontiguousarray(scaled)
        h, w = scaled.shape
        self._pixmap.setPixmap(QPixmap.fromImage(QImage(scaled.data, w, h, w, QImage.Format.Format_Grayscale8)))
        self._scene.setSceneRect(0, 0, w, h)

    # _restyle: solid within the marker's radius of the current slice, faint elsewhere, white when selected
    def _restyle(self) -> None:
        for marker_id, item in self._items.items():
            m = self._markers[marker_id]
            item.setOpacity(1.0 if abs(self._z - m.z) <= max(2.0, m.radius_px) else _FAINT)
            pen = QPen(QColor('white') if marker_id == self.selected_id else QColor(m.colour))
            pen.setCosmetic(True)
            pen.setWidth(3 if marker_id == self.selected_id else 2)
            item.setPen(pen)

    # _inside: whether a scene position is on the image
    def _inside(self, pos: QPointF) -> bool:
        w, h = self.image_size()
        return 0 <= pos.x() < w and 0 <= pos.y() < h

    # _marker_at: the marker whose centre is nearest the position and within the hit distance, if any
    def _marker_at(self, pos: QPointF) -> int | None:
        reach = _HIT_PX / self.transform().m11()
        best: tuple[float, int] | None = None
        for marker_id, m in self._markers.items():
            d = math.hypot(m.x + 0.5 - pos.x(), m.y + 0.5 - pos.y())
            if d <= reach and (best is None or d < best[0]):
                best = (d, marker_id)
        return best[1] if best else None
