'''
pickmix: entrypoint
'''

# Import external dependencies
from importlib.metadata import PackageNotFoundError, version

# __version__: installed version, 'unknown' when running from a bare checkout
try:
    __version__: str = version('pickmix')
except PackageNotFoundError:
    __version__ = 'unknown'

# main: launch the window, opening the config.toml given as the first argument
def main() -> None:
    import os, sys
    if sys.platform.startswith('linux') and not os.environ.get('WAYLAND_DISPLAY'):
        os.environ.setdefault('QT_QPA_PLATFORM', 'xcb')
    from pickmix.gui.app import run
    raise SystemExit(run(sys.argv[1:]))
