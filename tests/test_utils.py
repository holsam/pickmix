'''
pickmix: tests for the utils modules
'''

# Import external dependencies
import pytest
from collections.abc import Callable
from pathlib import Path

# Import internal pickmix objects
from pickmix.config import load_config
from pickmix.utils.coords import from_centred_angstrom, to_centred_angstrom
from pickmix.utils.io import Tomogram, TomogramError, find_tomograms, load_volume, volume_path
from pickmix.utils.star import merge_tomograms, read_star_loop, write_star_loop

# TOMO: 32 x 24 x 16 unbinned voxels at 1.34 A, reconstructed at 5.36 A (bin 4)
TOMO: Tomogram = Tomogram('T', 'T', Path('r.mrc'), None, 5.36, (4, 6, 8), 1.34, (32, 24, 16))

# TestStar: STAR reading and writing, and merging RELION runs
class TestStar:
    # test_round_trip: columns and values survive a write then a read
    def test_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / 'sub' / 'p.star'
        write_star_loop(path, 'particles', ['rlnTomoName', 'rlnCenteredCoordinateXAngst'], [('T1', 1.5), ('T2', -2.25)])
        assert read_star_loop(path) == [
            {'rlnTomoName': 'T1', 'rlnCenteredCoordinateXAngst': '1.5'},
            {'rlnTomoName': 'T2', 'rlnCenteredCoordinateXAngst': '-2.25'},
        ]

    # test_only_first_loop: a second loop is ignored
    def test_only_first_loop(self, tmp_path: Path) -> None:
        path = tmp_path / 'p.star'
        path.write_text('data_a\n\nloop_\n_rlnA #1\n1\n\nloop_\n_rlnB #1\n2\n')
        assert read_star_loop(path) == [{'rlnA': '1'}]

    # test_merge: names get the run prefix and every path is absolute
    def test_merge(self, tmp_path: Path, relion_project: Callable[[Path, list[str]], None]) -> None:
        relion_project(tmp_path / 'p', ['A', 'B'])
        result = merge_tomograms([('r1', tmp_path / 'p')], 'Tomograms/job006', tmp_path / 'out')
        rows = read_star_loop(result.star)
        assert [r['rlnTomoName'] for r in rows] == ['r1_A', 'r1_B']
        assert rows[0]['rlnTomoReconstructedTomogram'] == str(tmp_path / 'p' / 'Tomograms/job006/tomograms/A_Vol.mrc')
        ts = read_star_loop(Path(rows[0]['rlnTomoTiltSeriesStarFile']))
        assert ts[0]['rlnMicrographName'] == str(tmp_path / 'p' / 'frames/a.mrc')

    # test_merge_duplicates: the first occurrence wins and the rest are reported
    def test_merge_duplicates(self, tmp_path: Path, relion_project: Callable[[Path, list[str]], None]) -> None:
        relion_project(tmp_path / 'p', ['A', 'B'])
        result = merge_tomograms([('r1', tmp_path / 'p'), ('r1', tmp_path / 'p')], 'Tomograms/job006', tmp_path / 'out')
        assert result.count == 2
        assert result.skipped == ('r1_A', 'r1_B')

    # test_merge_nothing: runs with no rows are an error
    def test_merge_nothing(self, tmp_path: Path, relion_project: Callable[[Path, list[str]], None]) -> None:
        relion_project(tmp_path / 'p', [])
        with pytest.raises(ValueError, match='no tomograms'):
            merge_tomograms([('r1', tmp_path / 'p')], 'Tomograms/job006', tmp_path / 'out')

# TestIo: tomogram discovery and volume access
class TestIo:
    # test_find_tomograms: pairing by stem, header values and star values
    def test_find_tomograms(self, make_config: Callable[..., Path]) -> None:
        t = find_tomograms(load_config(make_config()))['Position_1_2']
        assert t.shape == (4, 6, 8)
        assert t.pixel_size == pytest.approx(5.36, rel=1e-4)
        assert t.size_xyz == (32, 24, 16)
        assert t.denoised_path is not None
        assert load_volume(t, source='denoised').shape == (4, 6, 8)

    # test_volume_path: raw is used when asked for, denoised otherwise when present
    def test_volume_path(self, make_config: Callable[..., Path]) -> None:
        t = find_tomograms(load_config(make_config()))['Position_1_2']
        assert volume_path(t, source='raw') == t.raw_path
        assert volume_path(t, source='denoised') == t.denoised_path

    # test_shape_mismatch: a header that disagrees with the star file is skipped and reported
    def test_shape_mismatch(self, make_config: Callable[..., Path]) -> None:
        issues: dict[str, TomogramError] = {}
        tomos = find_tomograms(load_config(make_config(shape=(4, 6, 20))), issues=issues)
        assert tomos == {}
        assert issues['Position_1_2'].reason == 'shape mismatch'
        assert issues['Position_1_2'].shape == (4, 6, 20)

    # test_no_raw: a star row with no matching file is reported
    def test_no_raw(self, make_config: Callable[..., Path]) -> None:
        config = load_config(make_config())
        next(config.raw_dir.glob('*.mrc')).unlink()
        issues: dict[str, TomogramError] = {}
        assert find_tomograms(config, issues=issues) == {}
        assert issues['Position_1_2'].reason == 'no raw tomogram'

# TestCoords: voxel and centred Angstrom conversions
class TestCoords:
    # test_centre_is_origin: the middle voxel of the tomogram maps to zero
    def test_centre_is_origin(self) -> None:
        assert to_centred_angstrom((4.0, 3.0, 2.0), TOMO) == pytest.approx((0.0, 0.0, 0.0), abs=1e-6)

    # test_known_value: voxel 0 is half the unbinned size away from the centre, and x, y, z keep their order
    def test_known_value(self) -> None:
        assert to_centred_angstrom((0.0, 0.0, 0.0), TOMO) == pytest.approx((-21.44, -16.08, -10.72))
        assert to_centred_angstrom((8.0, 0.0, 0.0), TOMO)[0] == pytest.approx(21.44)

    # test_round_trip: the conversion inverts
    def test_round_trip(self) -> None:
        xyz = (6.0, 2.5, 1.5)
        assert from_centred_angstrom(to_centred_angstrom(xyz, TOMO), TOMO) == pytest.approx(xyz)
