'''
pickmix: turning arrays into images and pixmaps for gui
'''

# Import external dependencies
import numpy as np
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap

# Import internal pickmix objects
from pickmix.gui.style import LABEL_BG, OVERLAY_TEXT

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

# label_cells: a copy of a montage image with a small translucent box of text in the corner of each cell; cells are grid x grid, row by row, each pad pixels apart (times scale when the image has been resized)
def label_cells(image: QImage, labels: list[str], grid: int, pad: int, *, scale: float = 1.0) -> QImage:
    out = image.convertToFormat(QImage.Format.Format_RGB32)
    gap = pad * scale
    cell = (out.width() - gap) / grid - gap
    painter = QPainter(out)
    font = painter.font()
    font.setPixelSize(max(8, int(cell / 4)))
    painter.setFont(font)
    metrics = painter.fontMetrics()
    for i, text in enumerate(labels):
        row, col = divmod(i, grid)
        box = QRect(int(gap + col * (cell + gap)), int(gap + row * (cell + gap)), metrics.horizontalAdvance(text) + 6, metrics.height() + 2)
        painter.fillRect(box, LABEL_BG)
        painter.setPen(OVERLAY_TEXT)
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return out
