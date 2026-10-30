'''
pickmix: tests for project creation
'''

# Import external dependencies
import pytest
from collections.abc import Callable
from pathlib import Path

# Import internal pickmix objects
from pickmix.config import load_config
from pickmix.project import create_project

# TestProject: creating and opening projects
class TestProject:
    # test_create_project: writes a loadable config and refuses to overwrite it
    def test_create_project(self, tmp_path: Path, relion_project: Callable[[Path, list[str]], None]) -> None:
        relion_project(tmp_path / 'p', ['A'])
        (tmp_path / 'raw').mkdir()
        path, result = create_project(tmp_path / 'proj', [('r1', tmp_path / 'p')], 'Tomograms/job006', tmp_path / 'raw')
        config = load_config(path)
        assert config.tomograms_star == result.star
        assert config.raw_dir == (tmp_path / 'raw').resolve()
        with pytest.raises(FileExistsError):
            create_project(tmp_path / 'proj', [('r1', tmp_path / 'p')], 'Tomograms/job006', tmp_path / 'raw')
