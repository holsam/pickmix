'''
pickmix: bundled icon loading
'''

# Import external dependencies
from pathlib import Path
from PySide6.QtGui import QIcon

# ICON_DIR: bundled icon files
ICON_DIR: Path = Path(__file__).parent / 'assets'

# icon: a bundled icon by file stem, or None when its file is not there so the caller can fall back to text
def icon(stem: str) -> QIcon | None:
    path = ICON_DIR / f'{stem}.svg'
    return QIcon(str(path)) if path.exists() else None
