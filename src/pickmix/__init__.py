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
    import sys
    from pickmix.gui.app import run
    raise SystemExit(run(sys.argv[1:]))
