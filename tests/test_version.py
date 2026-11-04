'''
pickmix: tests for the package version
'''

# Import external dependencies
from importlib.metadata import version

# Import internal pickmix objects
from pickmix import __version__

# TestVersion: version string
class TestVersion:
    # test_matches_install: the version is the installed package's
    def test_matches_install(self) -> None:
        assert __version__ == version('pickmix')
