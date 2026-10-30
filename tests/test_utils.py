'''
pickmix: tests for utils modules
'''

# Import external dependencies
import pytest
from collections.abc import Callable
from pathlib import Path

# Import internal pickmix objects
from pickmix.utils.star import merge_tomograms, read_star_loop, write_star_loop

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
