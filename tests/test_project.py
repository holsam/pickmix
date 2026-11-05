'''
pickmix: tests for creating and opening projects
'''

# Import external dependencies
import pytest
from collections.abc import Callable
from pathlib import Path

# Import internal pickmix objects
from pickmix.config import load_config
from pickmix.project import create_project, open_project

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

    # test_open: usable tomograms and star order
    def test_open(self, make_config: Callable[..., Path]) -> None:
        project = open_project(make_config())
        assert project.names == ['Position_1_2']
        assert list(project.tomos) == ['Position_1_2']
        assert project.issues == {}

    # test_open_rejected: a bad tomogram is listed in names and issues but not in tomos
    def test_open_rejected(self, make_config: Callable[..., Path]) -> None:
        project = open_project(make_config(shape=(4, 6, 20)))
        assert project.names == ['Position_1_2']
        assert project.tomos == {}
        assert project.issues['Position_1_2'].reason == 'shape mismatch'

    # test_update: changes are validated, kept and written
    def test_update(self, make_config: Callable[..., Path]) -> None:
        path = make_config()
        project = open_project(path)
        project.update(source='raw')
        assert project.config.source == 'raw'
        assert load_config(path).source == 'raw'

    # test_display_name: the configured name wins, else the config directory's name
    def test_display_name(self, make_config: Callable[..., Path]) -> None:
        path = make_config()
        project = open_project(path)
        assert project.display_name == path.parent.name
        project.update(name='Cages')
        assert project.display_name == 'Cages' and load_config(path).name == 'Cages'

    # test_create_with_name: a name given at creation is saved
    def test_create_with_name(self, tmp_path: Path, relion_project: Callable[[Path, list[str]], None]) -> None:
        relion_project(tmp_path / 'p', ['A'])
        (tmp_path / 'raw').mkdir()
        path, _ = create_project(tmp_path / 'proj', [('r1', tmp_path / 'p')], 'Tomograms/job006', tmp_path / 'raw', name='Cages')
        assert load_config(path).name == 'Cages'

    # test_common_pixel_size: the pixel size most tomograms share, None when there are none
    def test_common_pixel_size(self, make_config: Callable[..., Path]) -> None:
        project = open_project(make_config())
        assert project.common_pixel_size == 5.36
        project.tomos = {}
        assert project.common_pixel_size is None