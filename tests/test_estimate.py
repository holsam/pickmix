'''
pickmix: tests for the estimator registry, passthrough and ring estimator
'''

# Import external dependencies
import numpy as np, pytest
from pathlib import Path

# Import internal pickmix objects
from pickmix.config import Config, Kind, RingParams
from pickmix.estimate.common import crop, prepare
from pickmix.estimate.registry import ESTIMATORS
from pickmix.estimate.ring import ring_snr

# PX: voxel size of the synthetic volume, so 450 A is 84 voxels
PX = 5.36

# _config: coarse sweep and short walk to keep the ring tests fast
def _config(**kinds: Kind) -> Config:
    return Config(
        raw_dir=Path('/r'), tomograms_star=Path('/t.star'), ring=RingParams(radius_step_a=50.0, walk_max_half_a=250.0, z_shift_a=60.0),
        **({'kinds': kinds} if kinds else {}),
    )

# _volume: noise with a dark ring of radius 84 voxels at (y, x) = (170, 170) present only in z = 25 to 55
def _volume() -> np.ndarray:
    rng = np.random.default_rng(1)
    vol = rng.normal(0.0, 1.0, (80, 340, 340)).astype(np.float32)
    yy, xx = np.mgrid[:340, :340]
    vol[25:56] -= 1.5 * np.exp(-0.5 * ((np.hypot(yy - 170, xx - 170) - 84) / 5.6) ** 2)
    return vol

# TestEstimateRegistry: estimator registry tests
class TestEstimateRegistry:
    # test_registered: the passthrough is available by name
    def test_registered(self) -> None:
        assert {'none', 'ring'} <= set(ESTIMATORS)

# TestEstimateNone: passthrough estimator tests
class TestEstimateNone:
    # test_passthrough: centre kept, size and box from the kind, no score
    def test_passthrough(self) -> None:
        kind = Kind(marker_a=100, box_a=120)
        fit = ESTIMATORS['none'](np.zeros((1, 1, 1)), (10.4, 20.0, 30.6), kind, PX, _config(yellow=kind))
        assert (fit.x, fit.y, fit.z) == (10.4, 20.0, 30.6)
        assert fit.radius_a == 50 and fit.box_a == 120 and fit.snr == 0.0
        assert fit.z_lo == fit.z_hi == 31 and fit.flag == ''

# TestEstimateRing: ring estimator tests
    # test_ring_snr: a dark ring scores high, flat noise scores near zero
    def test_ring_snr(self) -> None:
        params = _config().ring
        rng = np.random.default_rng(2)
        yy, xx = np.mgrid[:340, :340]
        ring = np.exp(-0.5 * ((np.hypot(yy - 170, xx - 170) - 84) / 5.6) ** 2)
        noise = rng.normal(0.0, 1.0, (340, 340))
        valid = np.ones((340, 340), dtype=bool)
        assert ring_snr(noise - 4.0 * ring, valid, (170.0, 170.0), 84.0, params, PX) > 3.0
        assert abs(ring_snr(noise, valid, (170.0, 170.0), 84.0, params, PX)) < 1.0

    # test_ring_fit: an off-centre pick is pulled onto the ring, with a sensible radius, slab and box
    def test_ring_fit(self) -> None:
        kind = Kind(marker_a=600, estimator='ring')
        fit = ESTIMATORS['ring'](_volume(), (165, 174, 36), kind, PX, _config(cage=kind))
        assert fit.x == pytest.approx(170, abs=3)
        assert fit.y == pytest.approx(170, abs=3)
        assert fit.radius_a == pytest.approx(450.0, abs=30.0)
        assert fit.z == pytest.approx(40, abs=8)
        assert fit.z_lo <= 36 <= fit.z_hi
        assert fit.box_a == pytest.approx(2 * fit.radius_a * 1.25)
        assert fit.snr > 3.0
        assert 'edge' not in fit.flag

    # test_ring_fixed_box: a kind with its own box keeps it
    def test_ring_fixed_box(self) -> None:
        kind = Kind(marker_a=600, box_a=900, estimator='ring')
        fit = ESTIMATORS['ring'](_volume(), (165, 174, 36), kind, PX, _config(cage=kind))
        assert fit.box_a == 900

# TestEstimateCommon: helpers shared by the slab estimators
class TestEstimateCommon:
    # test_crop_pads_and_masks: a crop that leaves the volume is edge padded, the mask marks real voxels, and z is clipped
    def test_crop_pads_and_masks(self) -> None:
        vol = np.arange(5 * 6 * 7, dtype=np.float32).reshape(5, 6, 7)
        sub, valid, zlo = crop(vol, -3, 2, 1, 1, 3)
        assert sub.shape == (3, 7, 7) and zlo == 0
        assert valid.shape == (7, 7) and valid.sum() == 5 * 5 and not valid[0].any()
        assert np.array_equal(sub[:, 2:, 2:], vol[0:3, 0:5, 0:5])
        assert np.array_equal(sub[:, 0, 3], sub[:, 2, 3])

    # test_prepare_flattens: a slow ramp is removed away from the edges and a narrow feature stays
    def test_prepare_flattens(self) -> None:
        yy, xx = np.mgrid[:600, :600]
        img = (0.05 * xx).astype(np.float32)
        img[295:306, 195:206] += 5.0
        out = prepare(img, 8.0, 500.0, PX)
        assert abs(out[300, 400]) < 0.5 and out[300, 200] > out[300, 400] + 1.0
