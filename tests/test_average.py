'''
pickmix: tests for kind averages
'''

# Import external dependencies
import mrcfile, numpy as np, pytest
from pathlib import Path

# Import internal pickmix objects
from pickmix.average import average_kind
from pickmix.config import Config, Kind
from pickmix.estimate.registry import Fit
from pickmix.model import Pick
from pickmix.utils.io import Tomogram

# _tomogram: a 40-voxel cube at the given voxel size with a bright sphere at each (x, y, z) centre, in noise
def _tomogram(path: Path, name: str, centres: list[tuple[int, int, int]], voxel: float = 5.0) -> Tomogram:
    rng = np.random.default_rng(3)
    vol = rng.normal(0.0, 0.1, (40, 40, 40)).astype(np.float32)
    zz, yy, xx = np.mgrid[:40, :40, :40]
    for x, y, z in centres:
        vol[np.hypot(np.hypot(xx - x, yy - y), zz - z) <= 5] += 1.0
    with mrcfile.new(path / f'{name}.mrc') as mrc:
        mrc.set_data(vol)
        mrc.voxel_size = voxel
    return Tomogram(name, name, path / f'{name}.mrc', None, voxel, (40, 40, 40), voxel / 4, (160, 160, 160))

# _item: a pick of kind yellow with a fit at the same place
def _item(i: int, tomogram: str, x: float, y: float, z: float) -> tuple[Pick, Fit]:
    return Pick(i, tomogram, 'yellow', x, y, z), Fit(x=x, y=y, z=z, radius_a=30.0, box_a=100.0, snr=0, z_lo=round(z), z_hi=round(z))

# TestAverage: mean projections, montage and files
class TestAverage:
    # test_blob_in_centre: the overall mean is brightest in the middle, and files are written per tomogram and overall
    def test_blob_in_centre(self, tmp_path: Path) -> None:
        tomos = {'T': _tomogram(tmp_path, 'T', [(12, 20, 20), (28, 20, 20)]), 'U': _tomogram(tmp_path, 'U', [(20, 28, 20)])}
        config = Config(raw_dir=tmp_path, tomograms_star=tmp_path / 't.star', out_dir=tmp_path / 'out')
        items = [_item(1, 'T', 12, 20, 20), _item(2, 'T', 28, 20, 20), _item(3, 'U', 20, 28, 20)]
        r = average_kind('yellow', Kind(marker_a=60, box_a=100), items, tomos, config)
        assert r.count == 3 and r.box_px == 20 and r.overall.shape == (20, 20)
        assert r.overall[10, 10] > r.overall[0, 0] + 1.0
        assert set(r.per_tomogram) == {'T', 'U'} and r.montage.shape[0] >= 40
        assert sorted(p.name for p in r.folder.glob('*.png')) == ['T_mean.png', 'U_mean.png', 'overall_mean.png', 'overall_montage.png']

    # test_nothing: no picks is an error
    def test_nothing(self, tmp_path: Path) -> None:
        config = Config(raw_dir=tmp_path, tomograms_star=tmp_path / 't.star', out_dir=tmp_path / 'out')
        with pytest.raises(ValueError, match='nothing to average'):
            average_kind('yellow', Kind(marker_a=60, box_a=100), [], {}, config)

    # test_mixed_pixel_sizes: one box in pixels needs one pixel size
    def test_mixed_pixel_sizes(self, tmp_path: Path) -> None:
        tomos = {'T': _tomogram(tmp_path, 'T', [(20, 20, 20)]), 'U': _tomogram(tmp_path, 'U', [(20, 20, 20)], voxel=6.0)}
        config = Config(raw_dir=tmp_path, tomograms_star=tmp_path / 't.star', out_dir=tmp_path / 'out')
        with pytest.raises(ValueError, match='pixel size'):
            average_kind('yellow', Kind(marker_a=60, box_a=100), [_item(1, 'T', 20, 20, 20), _item(2, 'U', 20, 20, 20)], tomos, config)

    # test_montage_labels: one label per cell, pick order within its tomogram and the tomogram name, and the geometry matches the montage
    def test_montage_labels(self, tmp_path: Path) -> None:
        tomos = {'T': _tomogram(tmp_path, 'T', [(12, 20, 20), (28, 20, 20)]), 'U': _tomogram(tmp_path, 'U', [(20, 28, 20)])}
        config = Config(raw_dir=tmp_path, tomograms_star=tmp_path / 't.star', out_dir=tmp_path / 'out')
        items = [_item(1, 'T', 12, 20, 20), _item(2, 'T', 28, 20, 20), _item(3, 'U', 20, 28, 20)]
        r = average_kind('yellow', Kind(marker_a=60, box_a=100), items, tomos, config)
        assert r.labels == ['1 (T)', '2 (T)', '1 (U)'] and r.grid == 2 and r.pad == 2
        assert r.montage.shape == (r.grid * (r.box_px + r.pad) + r.pad,) * 2
