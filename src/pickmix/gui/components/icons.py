'''
pickmix: bundled icon loading
'''

# Import external dependencies
from pathlib import Path
from PySide6.QtGui import QColor, QIcon, QPainter

# ICON_DIR: bundled icon files
ICON_DIR: Path = Path(__file__).parent / 'assets'

# icon: a bundled icon by file stem, or None when its file is not there so the caller can fall back to text
def icon(stem: str) -> QIcon | None:
    path = ICON_DIR / f'{stem}.svg'
    return QIcon(str(path)) if path.exists() else None

# tinted: a bundled icon redrawn in one colour at a fixed size (or None when its file is not there)
def tinted(stem: str, colour: str, size: int = 16) -> QIcon | None:
    base = icon(stem)
    if base is None:
        return None
    pixmap = base.pixmap(size, size)
    painter = QPainter(pixmap)
    # keep the glyph's shape, replace its colour
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), QColor(colour))
    painter.end()
    return QIcon(pixmap)
