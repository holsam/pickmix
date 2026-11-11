'''
pickmix: tests for kind averages
'''

# Import external dependencies
import mrcfile, numpy as np, pytest
from pathlib import Path

# Import internal pickmix objects
from pickmix.average import average_kind, save_average
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

# _rod_tomogram: an 80-voxel cube at 5 A with a dark rod through the middle at angle_deg from the x axis towards y, in planes 36 to 44
def _rod_tomogram(path: Path, name: str, angle_deg: float) -> Tomogram:
    rng = np.random.default_rng(7)
    vol = rng.normal(0.0, 0.3, (80, 80, 80)).astype(np.float32)
    yy, xx = np.mgrid[:80, :80]
    ux, uy = np.cos(np.radians(angle_deg)), np.sin(np.radians(angle_deg))
    along = (xx - 40) * ux + (yy - 40) * uy
    across = -(xx - 40) * uy + (yy - 40) * ux
    vol[36:45] -= 1.0 * np.exp(-0.5 * (across / 2.0) ** 2) * (np.abs(along) <= 22)
    with mrcfile.new(path / f'{name}.mrc') as mrc:
        mrc.set_data(vol)
        mrc.voxel_size = 5.0
    return Tomogram(name, name, path / f'{name}.mrc', None, 5.0, (80, 80, 80), 5.0 / 4, (320, 320, 320))

# _rod_items: one pick per rod tomogram with a fit at its middle that has the rod's planes and, unless psi is False, its direction
def _rod_items(angles: dict[str, float], *, psi: bool = True) -> list[tuple[Pick, Fit]]:
    return [(Pick(i, name, 'rod', 40, 40, 40), Fit(x=40, y=40, z=40, radius_a=25.0, box_a=250.0, snr=5.0, z_lo=36, z_hi=44, psi_deg=angle if psi else None)) for i, (name, angle) in enumerate(angles.items(), start=1)]

# _bar_depth: how much darker the middle rows of a mean image are than the rows 8 pixels either side, in units of the image's own spread
def _bar_depth(img: np.ndarray) -> float:
    c = img.shape[0] // 2
    return float((img[c - 8 : c - 5].mean() + img[c + 6 : c + 9].mean()) / 2 - img[c - 1 : c + 2].mean()) / float(img.std())

# TestAverage: mean projections, montage and files
class TestAverage:
    # test_blob_in_centre: the overall mean is brightest in the middle, and averaging alone writes nothing
    def test_blob_in_centre(self, tmp_path: Path) -> None:
        tomos = {'T': _tomogram(tmp_path, 'T', [(12, 20, 20), (28, 20, 20)]), 'U': _tomogram(tmp_path, 'U', [(20, 28, 20)])}
        config = Config(raw_dir=tmp_path, tomograms_star=tmp_path / 't.star', out_dir=tmp_path / 'out')
        items = [_item(1, 'T', 12, 20, 20), _item(2, 'T', 28, 20, 20), _item(3, 'U', 20, 28, 20)]
        r = average_kind('yellow', Kind(marker_a=60, box_a=100), items, tomos, config)
        assert r.count == 3 and r.box_px == 20 and r.overall.shape == (20, 20)
        assert r.overall[10, 10] > r.overall[0, 0] + 1.0
        assert set(r.per_tomogram) == {'T', 'U'} and r.montage.shape[0] >= 40
        assert not r.folder.exists()

    # test_save_average: the overall images are always written, per-tomogram means only when asked, and old files are cleared
    def test_save_average(self, tmp_path: Path) -> None:
        tomos = {'T': _tomogram(tmp_path, 'T', [(12, 20, 20), (28, 20, 20)]), 'U': _tomogram(tmp_path, 'U', [(20, 28, 20)])}
        config = Config(raw_dir=tmp_path, tomograms_star=tmp_path / 't.star', out_dir=tmp_path / 'out')
        items = [_item(1, 'T', 12, 20, 20), _item(2, 'T', 28, 20, 20), _item(3, 'U', 20, 28, 20)]
        r = average_kind('yellow', Kind(marker_a=60, box_a=100), items, tomos, config)
        assert r.counts == {'T': 2, 'U': 1} and sum(r.counts.values()) == r.count
        names = lambda: sorted(p.name for p in r.folder.glob('*.png'))
        paths = save_average(r)
        assert sorted(p.name for p in paths) == names() == ['overall_mean.png', 'overall_montage.png']
        assert sorted(p.name for p in save_average(r, per_tomogram=True)) == names() == ['T_mean.png', 'U_mean.png', 'overall_mean.png', 'overall_montage.png']
        save_average(r)
        assert names() == ['overall_mean.png', 'overall_montage.png']

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

    # test_rods_line_up: rods at four different angles average to one bar along x, sharper than the same rods averaged without turning them
    def test_rods_line_up(self, tmp_path: Path) -> None:
        angles = {'A': 0.0, 'B': 45.0, 'C': 90.0, 'D': 135.0}
        tomos = {name: _rod_tomogram(tmp_path, name, angle) for name, angle in angles.items()}
        config = Config(raw_dir=tmp_path, tomograms_star=tmp_path / 't.star', out_dir=tmp_path / 'out')
        kind = Kind(marker_a=100, box_a=250)
        aligned = average_kind('rod', kind, _rod_items(angles), tomos, config).overall
        plain = average_kind('rod', kind, _rod_items(angles, psi=False), tomos, config).overall
        assert aligned.shape == plain.shape == (50, 50)
        assert _bar_depth(aligned) > 2.0 * _bar_depth(plain)
        # a bar along x is dark across the middle rows end to end, and darker in the middle than at the top of the image
        c = aligned.shape[0] // 2
        assert aligned[c - 1 : c + 2, 10:40].mean() < aligned[3:6, 10:40].mean() - 0.3

    # test_turned_by_its_own_angle: one rod at 30 degrees turned by 30 lies along x, and turned by the wrong angle does not
    def test_turned_by_its_own_angle(self, tmp_path: Path) -> None:
        tomos = {'A': _rod_tomogram(tmp_path, 'A', 30.0)}
        config = Config(raw_dir=tmp_path, tomograms_star=tmp_path / 't.star', out_dir=tmp_path / 'out')
        kind = Kind(marker_a=100, box_a=250)
        right = average_kind('rod', kind, _rod_items({'A': 30.0}), tomos, config).overall
        wrong = average_kind('rod', kind, _rod_items({'A': -30.0}), tomos, config).overall
        assert _bar_depth(right) > 2.0 * _bar_depth(wrong)

    # test_slab_follows_fit: a filament takes the planes of its fit, so a fit that misses the rod averages to no bar
    def test_slab_follows_fit(self, tmp_path: Path) -> None:
        tomos = {'A': _rod_tomogram(tmp_path, 'A', 30.0)}
        config = Config(raw_dir=tmp_path, tomograms_star=tmp_path / 't.star', out_dir=tmp_path / 'out')
        kind = Kind(marker_a=100, box_a=250)
        on = _rod_items({'A': 30.0})
        off = [(p, f.model_copy(update={'z_lo': 10, 'z_hi': 18})) for p, f in on]
        assert _bar_depth(average_kind('rod', kind, on, tomos, config).overall) > 3.0 * abs(_bar_depth(average_kind('rod', kind, off, tomos, config).overall))

    # test_kinds_without_direction_unchanged: a fit with no direction is cut and projected exactly as before
    def test_kinds_without_direction_unchanged(self, tmp_path: Path) -> None:
        tomos = {'T': _tomogram(tmp_path, 'T', [(12, 20, 20), (28, 20, 20)])}
        config = Config(raw_dir=tmp_path, tomograms_star=tmp_path / 't.star', out_dir=tmp_path / 'out')
        r = average_kind('yellow', Kind(marker_a=60, box_a=100), [_item(1, 'T', 12, 20, 20), _item(2, 'T', 28, 20, 20)], tomos, config)
        from pickmix.extract import crop_box
        from pickmix.utils.io import load_volume
        vol = load_volume(tomos['T'], source=config.source)
        expected = []
        for x in (12, 28):
            img = crop_box(vol, (20, 20, x), 20)[10 - 6 : 10 + 6 + 1].mean(axis=0)
            expected.append((img - img.mean()) / img.std())
        assert np.allclose(r.overall, np.mean(expected, axis=0))
