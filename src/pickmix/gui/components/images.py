'''
pickmix: turning arrays into images and pixmaps for gui
'''

# Import external dependencies
import math, numpy as np
from collections.abc import Callable
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy

# Import internal pickmix objects
from pickmix.gui.style import LABEL_BG, OVERLAY_TEXT, WELL_BG

# TILE_GAP: pixels between the cells of a montage laid out again to fit a pane
TILE_GAP: int = 2

# FitLabel: a label that draws its image to fill all the room it has, again whenever it is resized
class FitLabel(QLabel):
    # __init__: expands to fill its space, never smaller than minimum pixels a side
    def __init__(self, text: str = '', minimum: int = 240) -> None:
        super().__init__(text)
        self._render: Callable[[int, int], QPixmap] | None = None
        self._preferred = minimum
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(minimum, minimum)

    # sizeHint: the smallest size it is happy with, so the layout hands it any spare room
    def sizeHint(self) -> QSize:
        return QSize(self._preferred, self._preferred)

    # set_render: how to draw the image at a given width and height in pixels, or None to show the text instead
    def set_render(self, render: Callable[[int, int], QPixmap] | None) -> None:
        self._render = render
        self._redraw()

    # resizeEvent: draw the image again at the new size
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._redraw()

    # _redraw: the image at the label's own size
    def _redraw(self) -> None:
        if self._render is not None and self.width() > 0 and self.height() > 0:
            self.setPixmap(self._render(self.width(), self.height()))

# to_image: a 2D array stretched between its 1st and 99th percentiles as an 8-bit grey image
def to_image(arr: np.ndarray) -> QImage:
    lo, hi = np.percentile(arr, (1, 99))
    img = np.ascontiguousarray(np.clip((arr - lo) * (255.0 / max(hi - lo, 1e-6)), 0, 255).astype(np.uint8))
    h, w = img.shape
    # copy so the image owns its pixels once the array is gone
    return QImage(img.data, w, h, w, QImage.Format.Format_Grayscale8).copy()

# to_pixmap: a 2D array stretched between its 1st and 99th percentiles and scaled to fit a square of the given edge
def to_pixmap(arr: np.ndarray, size: int) -> QPixmap:
    pixmap = QPixmap.fromImage(to_image(arr))
    return pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

# draw_box: a copy of a pixmap with a rectangle outlined on it
def draw_box(pixmap: QPixmap, rect: tuple[float, float, float, float], scale: float, colour: str, *, dotted: bool = False) -> QPixmap:
    out = QPixmap(pixmap)
    painter = QPainter(out)
    pen = QPen(QColor(colour))
    pen.setWidth(1)
    pen.setStyle(Qt.PenStyle.DotLine if dotted else Qt.PenStyle.SolidLine)
    painter.setPen(pen)
    left, top, right, bottom = (v * scale for v in rect)
    painter.drawRect(QRect(round(left), round(top), round(right - left), round(bottom - top)))
    painter.end()
    return out

# label_cells: a copy of a montage image with a small translucent box of text in the corner of each cell; cells are grid x grid, row by row, each pad pixels apart (times scale when the image has been resized)
def label_cells(image: QImage, labels: list[str], grid: int, pad: int, *, scale: float = 1.0) -> QImage:
    out = image.convertToFormat(QImage.Format.Format_RGB32)
    gap = pad * scale
    cell = (out.width() - gap) / grid - gap
    painter = QPainter(out)
    font = painter.font()
    font.setPixelSize(max(6, int(cell / 8)))
    painter.setFont(font)
    for i, text in enumerate(labels):
        row, col = divmod(i, grid)
        _draw_label(painter, int(gap + col * (cell + gap)), int(gap + row * (cell + gap)), text, int(cell))
    painter.end()
    return out

# tile_cells: the cells of a square montage laid out again in the number of columns that makes them biggest in a width x height area, each labelled; the block is centred on a dark background
def tile_cells(image: QImage, labels: list[str], grid: int, pad: int, width: int, height: int) -> QImage:
    count = len(labels)
    # side of one cell in the source image
    box = (image.width() - pad) / grid - pad
    def edge(cols: int) -> float:
        rows = math.ceil(count / cols)
        return min((width - TILE_GAP * (cols + 1)) / cols, (height - TILE_GAP * (rows + 1)) / rows)
    cols = max(range(1, count + 1), key=edge)
    rows, side = math.ceil(count / cols), max(edge(cols), 1.0)
    out = QImage(width, height, QImage.Format.Format_RGB32)
    out.fill(QColor(WELL_BG))
    left = (width - cols * side - (cols + 1) * TILE_GAP) / 2
    top = (height - rows * side - (rows + 1) * TILE_GAP) / 2
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    font = painter.font()
    font.setPixelSize(max(6, int(side / 8)))
    painter.setFont(font)
    for i, text in enumerate(labels):
        row, col = divmod(i, cols)
        src_row, src_col = divmod(i, grid)
        source = QRect(round(pad + src_col * (box + pad)), round(pad + src_row * (box + pad)), round(box), round(box))
        x, y = round(left + TILE_GAP + col * (side + TILE_GAP)), round(top + TILE_GAP + row * (side + TILE_GAP))
        painter.drawImage(QRect(x, y, round(side), round(side)), image, source)
        _draw_label(painter, x, y, text, round(side))
    painter.end()
    return out

# label_image: a copy of a pixmap with a label in its top-left corner
def label_image(pixmap: QPixmap, text: str) -> QPixmap:
    out = QPixmap(pixmap)
    painter = QPainter(out)
    font = painter.font()
    font.setPixelSize(max(10, out.height() // 16))
    painter.setFont(font)
    _draw_label(painter, 4, 4, text, out.width() - 8)
    painter.end()
    return out

# _draw_label: a translucent dark box with white text at a corner position, no wider than max_width (text elided on the right)
def _draw_label(painter: QPainter, x: int, y: int, text: str, max_width: int) -> None:
    metrics = painter.fontMetrics()
    shown = metrics.elidedText(text, Qt.TextElideMode.ElideRight, max(max_width - 6, 1))
    box = QRect(x, y, min(metrics.horizontalAdvance(shown) + 6, max_width), metrics.height() + 2)
    painter.fillRect(box, LABEL_BG)
    painter.setPen(OVERLAY_TEXT)
    painter.drawText(box, Qt.AlignmentFlag.AlignCenter, shown)
