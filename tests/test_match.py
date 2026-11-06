'''
pickmix: tests for template building and correlation search
'''

# Import external dependencies
import mrcfile, pytest, numpy as np
from pathlib import Path

# Import internal pickmix objects
from pickmix.candidates import Hit
from pickmix.config import Config, Kind
from pickmix.match import Cancelled, bin_cube, bin_volume, build_template, find_peaks, scan, score_volume, soft_sphere, template_geometry, to_voxel
from pickmix.utils.io import Tomogram

# PIXEL: Angstrom per voxel of the test tomograms
PIXEL: float = 10.0

# _blob: a smooth 3D bump of the given radius in voxels, in a cube of odd side
def _blob(radius: float, side: int) -> np.ndarray:
    c = side // 2
    z, y, x = np.ogrid[:side, :side, :side]
    return np.exp(-(((z - c) ** 2 + (y - c) ** 2 + (x - c) ** 2) / (2 * (radius / 2) ** 2))).astype(np.float32)

# _tomogram: tomogram with planted blobs
def _tomogram(tmp_path: Path, name: str, centres: list[tuple[int, int, int]], *, seed: int = 0) -> Tomogram:
    rng = np.random.default_rng(seed)
    vol = rng.normal(0, 1, (48, 96, 128)).astype(np.float32)
    blob = _blob(8, 25)
    for x, y, z in centres:
        vol[z - 12 : z + 13, y - 12 : y + 13, x - 12 : x + 13] += 4 * blob
    path = tmp_path / f'{name}.mrc'
    with mrcfile.new(path) as mrc:
        mrc.set_data(vol)
        mrc.voxel_size = PIXEL
    return Tomogram(name, name, path, None, PIXEL, vol.shape, PIXEL, (128, 96, 48))

# _matches: whether every centre has a hit within tol voxels and no hit is left over
def _matches(hits: list[Hit], centres: list[tuple[int, int, int]], tol: float = 2.0) -> bool:
    close = lambda h, c: max(abs(h.x - c[0]), abs(h.y - c[1]), abs(h.z - c[2])) <= tol
    return len(hits) == len(centres) and all(any(close(h, c) for h in hits) for c in centres)

# _config: example config with kind that has 160 Angstrom marker
def _config(tmp_path: Path) -> tuple[Config, Kind]:
    kind = Kind(marker_a=160, box_a=240)
    return Config(raw_dir=tmp_path, tomograms_star=tmp_path / 't.star', out_dir=tmp_path / 'out', kinds={'blob': kind}), kind

class TestMatch:
    # test_template_geometry: template is binned until it is about template_px across, with an odd edge
    def test_template_geometry(self, tmp_path: Path) -> None:
        config, kind = _config(tmp_path)
        assert template_geometry(kind, config, PIXEL) == (1, 25)
        big = kind.model_copy(update={'box_a': 1500.0})
        factor, edge = template_geometry(big, config, PIXEL)
        assert factor == 5 and edge % 2 == 1 and abs(edge * factor - 150) <= factor

    # test_template_geometry_default_box: a kind with no box takes the marker diameter times the ring margin
    def test_template_geometry_default_box(self, tmp_path: Path) -> None:
        config, kind = _config(tmp_path)
        assert template_geometry(kind.model_copy(update={'box_a': 0.0}), config, PIXEL) == (1, 21)

    # test_soft_sphere: one inside the radius, zero outside, symmetric
    def test_soft_sphere(self) -> None:
        m = soft_sphere(21, 6)
        assert m[10, 10, 10] == 1 and m[0, 0, 0] == 0 and np.allclose(m, m[::-1, ::-1, ::-1])

    # test_bin_cube: blocks are averaged
    def test_bin_cube(self) -> None:
        cube = np.arange(64, dtype=np.float32).reshape(4, 4, 4)
        assert bin_cube(cube, 2).shape == (2, 2, 2) and bin_cube(cube, 2)[0, 0, 0] == cube[:2, :2, :2].mean()

    # test_bin_volume: blocks are averaged, remainders dropped, and a stop request raises Cancelled
    def test_bin_volume(self) -> None:
        vol = np.arange(5 * 6 * 7, dtype=np.float32).reshape(5, 6, 7)
        out = bin_volume(vol, 2)
        assert out.shape == (2, 3, 3) and out[1, 2, 2] == vol[2:4, 4:6, 4:6].mean()
        with pytest.raises(Cancelled):
            bin_volume(vol, 2, stop=lambda: True)

    # test_to_voxel: centre of a binned voxel in reconstruction voxels
    def test_to_voxel(self) -> None:
        assert to_voxel(0, 1) == 0 and to_voxel(2, 4) == 9.5

    # test_template_is_masked_and_centred: kernel is zero outside the mask and sums to zero
    def test_template_is_masked_and_centred(self, tmp_path: Path) -> None:
        config, kind = _config(tmp_path)
        tomo = _tomogram(tmp_path, 'a', [(40, 40, 24)])
        template = build_template('blob', kind, [('a', 40, 40, 24)], {'a': tomo}, config)
        assert template.kernel.shape == (25, 25, 25) and template.count == 1 and template.bin == 1
        assert abs(float(template.kernel.sum())) < 1e-3 and template.kernel[0, 0, 0] == 0

    # test_build_needs_picks_and_one_pixel_size: no positions or mixed pixel sizes are refused
    def test_build_needs_picks_and_one_pixel_size(self, tmp_path: Path) -> None:
        config, kind = _config(tmp_path)
        a, b = _tomogram(tmp_path, 'a', [(40, 40, 24)]), _tomogram(tmp_path, 'b', [])
        with pytest.raises(ValueError, match='nothing'):
            build_template('blob', kind, [], {'a': a}, config)
        odd = Tomogram('b', 'b', b.raw_path, None, 5.0, b.shape, 5.0, b.size_xyz)
        with pytest.raises(ValueError, match='one pixel size'):
            build_template('blob', kind, [('a', 40, 40, 24), ('b', 40, 40, 24)], {'a': a, 'b': odd}, config)

    # test_scan_finds_planted_blobs: a template from one tomogram finds blobs planted elsewhere, at the right places
    def test_scan_finds_planted_blobs(self, tmp_path: Path) -> None:
        config, kind = _config(tmp_path)
        source = _tomogram(tmp_path, 'a', [(40, 40, 24), (80, 60, 24)])
        target = _tomogram(tmp_path, 'b', [(30, 30, 24), (90, 50, 20), (60, 70, 28)], seed=1)
        template = build_template('blob', kind, [('a', 40, 40, 24), ('a', 80, 60, 24)], {'a': source}, config)
        with mrcfile.mmap(target.raw_path, mode='r') as mrc:
            hits = scan(np.asarray(mrc.data), template, kind, config)
        assert _matches(hits[:3], [(30, 30, 24), (90, 50, 20), (60, 70, 28)]) and all(h.score > 0.3 for h in hits[:3])
        # the three true sites outscore everything else
        assert len(hits) == 3 or hits[3].score < hits[2].score

    # test_scan_skips_known: positions already picked are not offered again
    def test_scan_skips_known(self, tmp_path: Path) -> None:
        config, kind = _config(tmp_path)
        source = _tomogram(tmp_path, 'a', [(40, 40, 24)])
        target = _tomogram(tmp_path, 'b', [(30, 30, 24), (90, 50, 20)], seed=1)
        template = build_template('blob', kind, [('a', 40, 40, 24)], {'a': source}, config)
        with mrcfile.mmap(target.raw_path, mode='r') as mrc:
            hits = scan(np.asarray(mrc.data), template, kind, config, [(30.0, 30.0, 24.0)])
        assert _matches(hits[:1], [(90, 50, 20)])

    # test_score_flat_volume: a flat volume scores zero everywhere
    def test_score_flat_volume(self, tmp_path: Path) -> None:
        config, kind = _config(tmp_path)
        tomo = _tomogram(tmp_path, 'a', [(40, 40, 24)])
        template = build_template('blob', kind, [('a', 40, 40, 24)], {'a': tomo}, config)
        assert not score_volume(np.ones((30, 40, 50), dtype=np.float32), template).any()

    # test_find_peaks: best first, separated, away from the faces, above the minimum
    def test_find_peaks(self) -> None:
        score = np.zeros((20, 20, 20), dtype=np.float32)
        score[10, 10, 10], score[10, 10, 12], score[5, 5, 5], score[0, 0, 0], score[15, 15, 15] = 0.9, 0.8, 0.5, 0.99, 0.1
        peaks = find_peaks(score, min_score=0.2, separation=4, margin=2, limit=10)
        assert [p for p, _ in peaks] == [(10, 10, 10), (5, 5, 5)]
        assert [round(s, 1) for _, s in peaks] == [0.9, 0.5]
        assert len(find_peaks(score, min_score=0.2, separation=4, margin=2, limit=1)) == 1
        assert find_peaks(score, min_score=0.2, separation=4, margin=12, limit=10) == []
