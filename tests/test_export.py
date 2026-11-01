'''
pickmix: tests for per-kind star file export
'''

# Import external dependencies
import pytest
from pathlib import Path

# Import internal pickmix objects
from pickmix.config import Kind
from pickmix.estimate.registry import Fit
from pickmix.export import Item, export_kind, recommend_box
from pickmix.model import Pick
from pickmix.utils.io import Tomogram
from pickmix.utils.star import read_star_loop

# TOMO: 32 x 24 x 16 unbinned voxels at 1.34 A, reconstructed at 5.36 A
TOMO: Tomogram = Tomogram('T', 'T', Path('r.mrc'), None, 5.36, (4, 6, 8), 1.34, (32, 24, 16))

# KIND: a passthrough kind with a 100 A box
KIND: Kind = Kind(marker_a=100, box_a=100)

# _item: a pick of kind yellow with its fit at the same place
def _item(i: int, x: float, y: float, z: float, snr: float, flag: str = '', box: float = 100.0) -> Item:
    return (
        Pick(i, 'T', 'yellow', x, y, z),
        Fit(x=x, y=y, z=z, radius_a=50.0, box_a=box, snr=snr, z_lo=round(z), z_hi=round(z), flag=flag),
    )

# TestExport: star files, filters and the box recommendation
class TestExport:
    # test_files: particles.star and a per-tomogram file with centred Angstrom coordinates
    def test_files(self, tmp_path: Path) -> None:
        s = export_kind('yellow', KIND, [_item(1, 4, 3, 2, 1.5), _item(2, 0, 0, 0, 2.0)], {'T': TOMO}, tmp_path)
        rows = read_star_loop(tmp_path / 'relion' / 'yellow' / 'particles.star')
        assert [r['rlnTomoName'] for r in rows] == ['T', 'T']
        assert (rows[0]['rlnCenteredCoordinateXAngst'], rows[0]['rlnCenteredCoordinateYAngst'], rows[0]['rlnCenteredCoordinateZAngst']) == ('0.00', '0.00', '0.00')
        assert rows[1]['rlnCenteredCoordinateXAngst'] == '-21.44' and rows[1]['rlnAutopickFigureOfMerit'] == '2.000'
        assert len(read_star_loop(tmp_path / 'relion' / 'yellow' / 'T_coords.star')) == 2
        assert s.written == 2 and s.box_a == 100 and s.box_px == 10

    # test_filters: minimum SNR and flagged picks are dropped and counted
    def test_filters(self, tmp_path: Path) -> None:
        items = [_item(1, 1, 1, 1, 0.5), _item(2, 2, 2, 2, 3.0, flag='edge'), _item(3, 3, 3, 3, 3.0)]
        s = export_kind('yellow', KIND, items, {'T': TOMO}, tmp_path, min_snr=1.0, drop_flagged=True)
        assert (s.written, s.below_snr, s.dropped_flagged) == (1, 1, 1)

    # test_nothing_left: an empty result is an error, not an empty file
    def test_nothing_left(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match='no particles'):
            export_kind('yellow', KIND, [_item(1, 1, 1, 1, 0.5)], {'T': TOMO}, tmp_path, min_snr=2.0)

    # test_old_files_removed: a tomogram that no longer has particles loses its file
    def test_old_files_removed(self, tmp_path: Path) -> None:
        other = Tomogram('U', 'U', Path('u.mrc'), None, 5.36, (4, 6, 8), 1.34, (32, 24, 16))
        first = [_item(1, 1, 1, 1, 1.0), (Pick(2, 'U', 'yellow', 1, 1, 1), _item(2, 1, 1, 1, 1.0)[1])]
        export_kind('yellow', KIND, first, {'T': TOMO, 'U': other}, tmp_path)
        assert (tmp_path / 'relion' / 'yellow' / 'U_coords.star').exists()
        export_kind('yellow', KIND, first[:1], {'T': TOMO, 'U': other}, tmp_path)
        assert not (tmp_path / 'relion' / 'yellow' / 'U_coords.star').exists()

    # test_recommend_box: a fixed box wins; otherwise a percentile of the fits, in even pixels
    def test_recommend_box(self) -> None:
        assert recommend_box(KIND, []) == (100, 10)
        ring = Kind(marker_a=600, estimator='ring')
        items = [_item(i, 1, 1, 1, 1.0, box=b) for i, b in enumerate((1000.0, 1100.0, 1200.0))]
        assert recommend_box(ring, items, percentile=100.0) == (1200.0, 114)
        assert recommend_box(ring, []) == (0.0, 0)
