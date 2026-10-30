'''
pickmix: tests for configuration schema, kinds validation and TOML round trip
'''

# Import external dependencies
import pytest
from pathlib import Path
from pydantic import ValidationError

# Import internal pickmix objects
from pickmix.config import Config, Kind, load_config, save_config

# _config: a config with absolute paths, so it survives a save and load unchanged, and the given kinds
def _config(**kinds: Kind) -> Config:
    extra = {'kinds': kinds} if kinds else {}
    return Config(raw_dir=Path('/r'), tomograms_star=Path('/t.star'), out_dir=Path('/out'), **extra)

# test_default_kind: no kinds table means one cage kind
def test_default_kind() -> None:
    assert list(_config().kinds) == ['cage']

# test_round_trip: save then load keeps every field and the kind order
def test_round_trip(tmp_path: Path) -> None:
    config = _config(
        cage=Kind(marker_a=600, estimator='ring'),
        green=Kind(marker_a=40, box_a=200, parent='cage', tilt_prior_deg=0),
        yellow=Kind(marker_a=100, box_a=100),
    )
    save_config(config, tmp_path / 'config.toml')
    loaded = load_config(tmp_path / 'config.toml')
    assert loaded == config
    assert list(loaded.kinds) == ['cage', 'green', 'yellow']

# test_relative_paths: relative paths resolve against the config file, not the cwd
def test_relative_paths(tmp_path: Path) -> None:
    (tmp_path / 'config.toml').write_text('raw_dir = "raw"\ntomograms_star = "t.star"\n')
    config = load_config(tmp_path / 'config.toml')
    assert config.raw_dir == tmp_path.resolve() / 'raw'
    assert config.out_dir == tmp_path.resolve() / 'out'
    assert config.denoised_dir is None

# test_replace: replace validates the result
def test_replace() -> None:
    assert _config().replace(source='raw').source == 'raw'
    with pytest.raises(ValidationError):
        _config().replace(source='other')

# test_unknown_parent: a parent that is not a kind is rejected
def test_unknown_parent() -> None:
    with pytest.raises(ValidationError, match='unknown parent'):
        _config(green=Kind(marker_a=40, box_a=200, parent='cage'))

# test_parent_cycle: a parent chain that loops is rejected
def test_parent_cycle() -> None:
    with pytest.raises(ValidationError, match='loops'):
        _config(a=Kind(marker_a=1, box_a=1, parent='b'), b=Kind(marker_a=1, box_a=1, parent='a'))

# test_none_needs_box: a passthrough kind with no box is rejected
def test_none_needs_box() -> None:
    with pytest.raises(ValidationError, match='box_a'):
        _config(yellow=Kind(marker_a=100))

# test_bad_kind_name: names that cannot be folder names are rejected
def test_bad_kind_name() -> None:
    with pytest.raises(ValidationError, match='letters'):
        _config(**{'bad name': Kind(marker_a=1, box_a=1)})
