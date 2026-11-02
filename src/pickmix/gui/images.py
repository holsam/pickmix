'''
pickmix: turning arrays into pixmaps for the GUI
'''

# Import external dependencies
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap

# to_pixmap: a 2D array stretched between its 1st and 99th percentiles and scaled to fit a square of the given edge
def to_pixmap(arr: np.ndarray, size: int) -> QPixmap:
    lo, hi = np.percentile(arr, (1, 99))
    img = np.ascontiguousarray(np.clip((arr - lo) * (255.0 / max(hi - lo, 1e-6)), 0, 255).astype(np.uint8))
    h, w = img.shape
    pixmap = QPixmap.fromImage(QImage(img.data, w, h, w, QImage.Format.Format_Grayscale8))
    return pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
