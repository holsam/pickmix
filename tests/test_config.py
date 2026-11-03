'''
pickmix: tests for configuration schema, kinds validation and TOML round trip
'''

# Import external dependencies
import pytest
from pathlib import Path
from pydantic import ValidationError

# Import internal pickmix objects
from pickmix.config import Config, Kind, RingParams, load_config, save_config

# _config: a config with absolute paths, so it survives a save and load unchanged, and the given kinds
def _config(**kinds: Kind) -> Config:
    extra = {'kinds': kinds} if kinds else {}
    return Config(raw_dir=Path('/r'), tomograms_star=Path('/t.star'), out_dir=Path('/out'), **extra)

# TestConfig: kinds validation, paths and the TOML round trip
class TestConfig:
    # test_default_kind: no kinds table means one cage kind
    def test_default_kind(self) -> None:
        assert list(_config().kinds) == ['cage']

    # test_round_trip: save then load keeps every field and the kind order
    def test_round_trip(self, tmp_path: Path) -> None:
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
    def test_relative_paths(self, tmp_path: Path) -> None:
        (tmp_path / 'config.toml').write_text('raw_dir = "raw"\ntomograms_star = "t.star"\n')
        config = load_config(tmp_path / 'config.toml')
        assert config.raw_dir == tmp_path.resolve() / 'raw'
        assert config.out_dir == tmp_path.resolve() / 'out'
        assert config.denoised_dir is None

    # test_replace: replace validates the result
    def test_replace(self) -> None:
        assert _config().replace(source='raw').source == 'raw'
        with pytest.raises(ValidationError):
            _config().replace(source='other')

    # test_unknown_parent: a parent that is not a kind is rejected
    def test_unknown_parent(self) -> None:
        with pytest.raises(ValidationError, match='unknown parent'):
            _config(green=Kind(marker_a=40, box_a=200, parent='cage'))

    # test_parent_cycle: a parent chain that loops is rejected
    def test_parent_cycle(self) -> None:
        with pytest.raises(ValidationError, match='loops'):
            _config(a=Kind(marker_a=1, box_a=1, parent='b'), b=Kind(marker_a=1, box_a=1, parent='a'))

    # test_none_needs_box: a passthrough kind with no box is rejected
    def test_none_needs_box(self) -> None:
        with pytest.raises(ValidationError, match='box_a'):
            _config(yellow=Kind(marker_a=100))

    # test_bad_kind_name: names that cannot be folder names are rejected
    def test_bad_kind_name(self) -> None:
        with pytest.raises(ValidationError, match='letters'):
            _config(**{'bad name': Kind(marker_a=1, box_a=1)})

    # test_ring_params_documented: every ring parameter has a form label and a tooltip
    def test_ring_params_documented(self) -> None:
        for name, field in RingParams.model_fields.items():
            assert field.title and field.description, name

    # test_default_hotkeys: no hotkeys means the first nine kinds in table order, padded with unused keys
    def test_default_hotkeys(self) -> None:
        assert _config().hotkeys == ['cage', *[''] * 8]
        kinds = {f'k{i}': Kind(marker_a=10, box_a=10) for i in range(11)}
        assert _config(**kinds).hotkeys == [f'k{i}' for i in range(9)]

    # test_hotkeys_round_trip: chosen hotkeys survive a save and load, unused keys included
    def test_hotkeys_round_trip(self, tmp_path: Path) -> None:
        config = _config(cage=Kind(marker_a=600, estimator='ring'), yellow=Kind(marker_a=100, box_a=100))
        config = config.replace(hotkeys=['', 'yellow', 'cage'])
        save_config(config, tmp_path / 'config.toml')
        assert load_config(tmp_path / 'config.toml').hotkeys == ['', 'yellow', 'cage', *[''] * 6]

    # test_bad_hotkeys: unknown kinds, repeats and too many keys are rejected
    def test_bad_hotkeys(self) -> None:
        config = _config()
        for keys, text in ((['nope'], 'unknown kind'), (['cage', 'cage'], 'one hotkey'), (['cage'] + [''] * 9, 'at most')):
            with pytest.raises(ValidationError, match=text):
                config.replace(hotkeys=keys)

    # test_replace_kinds_resets_hotkeys: swapping the kinds without hotkeys gives the default hotkeys for the new kinds
    def test_replace_kinds_resets_hotkeys(self) -> None:
        config = _config().replace(kinds={'yellow': Kind(marker_a=100, box_a=100)})
        assert config.hotkeys == ['yellow', *[''] * 8]

    # test_no_kinds: a config may have no kinds, which saves and loads as no kinds rather than the default
    def test_no_kinds(self, tmp_path: Path) -> None:
        config = Config(raw_dir=Path('/r'), tomograms_star=Path('/t.star'), out_dir=Path('/out'), kinds={})
        assert config.kinds == {} and config.hotkeys == [''] * 9
        save_config(config, tmp_path / 'config.toml')
        assert load_config(tmp_path / 'config.toml') == config

    # test_kind_documented: every kind field has a dialog label and a tooltip
    def test_kind_documented(self) -> None:
        for name, field in Kind.model_fields.items():
            assert field.title and field.description, name
