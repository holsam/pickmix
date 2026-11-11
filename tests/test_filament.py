'''
pickmix: tests for the filament estimator
'''

# Import external dependencies
import math, numpy as np, pytest
from pathlib import Path

# Import internal pickmix objects
from pickmix.config import Config, FilamentParams, Kind
from pickmix.estimate.registry import ESTIMATORS, Fit

# PX: voxel size of the synthetic volumes, so 100 A is 18.7 voxels
PX = 5.36

# SHAPE: planes, rows and columns of the synthetic volumes
SHAPE: tuple[int, int, int] = (60, 260, 260)

# _config: a narrow width ladder, short reach and a modest high-pass to keep the fits fast
def _config(kind: Kind, **settings: object) -> Config:
    params = FilamentParams(**{
        'width_range_a': (80.0, 200.0), 'width_steps': 3, 'max_length_a': 1500.0, 'highpass_sigma_a': 400.0, 'z_max_half_a': 400.0, **settings,
    })
    return Config(raw_dir=Path('/r'), tomograms_star=Path('/t.star'), filament=params, kinds={'rod': kind})

# _fit: run the estimator on a volume from a pick (x, y, z) with a filament kind
def _fit(vol: np.ndarray, pick: tuple[float, float, float], *, kind: Kind | None = None, **settings: object) -> Fit:
    kind = kind or Kind(marker_a=100, estimator='filament')
    return ESTIMATORS['filament'](vol, pick, kind, PX, _config(kind, **settings))

# _rod: noise with a dark rod through (x, y) = centre at angle_deg from the x axis towards y, present only in planes z_range[0] to z_range[1] - 1; the rod is a gaussian in width_a (full width at half maximum) and a hard length_a long
def _rod(
    angle_deg: float, *, width_a: float = 100.0, length_a: float = 1200.0, z_range: tuple[int, int] = (20, 45),
    centre: tuple[float, float] = (130.0, 130.0), amp: float = 1.5, seed: int = 1, noise: bool = True,
) -> np.ndarray:
    vol = np.random.default_rng(seed).normal(0.0, 1.0, SHAPE).astype(np.float32) if noise else np.zeros(SHAPE, dtype=np.float32)
    yy, xx = np.mgrid[: SHAPE[1], : SHAPE[2]]
    ux, uy = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
    along = (xx - centre[0]) * ux + (yy - centre[1]) * uy
    across = -(xx - centre[0]) * uy + (yy - centre[1]) * ux
    profile = np.exp(-0.5 * (across / (width_a / 2.355 / PX)) ** 2) * (np.abs(along) <= length_a / 2 / PX)
    vol[z_range[0] : z_range[1]] -= amp * profile
    return vol

# _across: distance in voxels of a point from the line through (130, 130) at angle_deg
def _across(x: float, y: float, angle_deg: float) -> float:
    return abs(-(x - 130.0) * math.sin(math.radians(angle_deg)) + (y - 130.0) * math.cos(math.radians(angle_deg)))

# _turn: smallest difference in degrees between two directions that are only defined up to a half turn
def _turn(a: float, b: float) -> float:
    d = (a - b) % 180.0
    return min(d, 180.0 - d)

# _offset_pick: a pick shifted from the rod centre by along and across, in Angstrom, at plane z
def _offset_pick(angle_deg: float, along_a: float, across_a: float, z: float) -> tuple[float, float, float]:
    ux, uy = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
    a, c = along_a / PX, across_a / PX
    return 130.0 + a * ux - c * uy, 130.0 + a * uy + c * ux, z

# TestFilament: filament estimator tests
class TestFilament:
    # test_registered: the estimator is available by name
    def test_registered(self) -> None:
        assert 'filament' in ESTIMATORS

    # test_rods_at_angles: an off-axis pick is snapped onto the axis, with its direction, width and z extent found
    @pytest.mark.parametrize('angle', [0.0, 35.0, 90.0, 150.0])
    def test_rods_at_angles(self, angle: float) -> None:
        fit = _fit(_rod(angle), _offset_pick(angle, 150.0, 60.0, 30.0))
        assert _across(fit.x, fit.y, angle) < 1.0
        assert _turn(fit.psi_deg, angle) < 3.0 and 0.0 <= fit.psi_deg < 180.0
        assert 2 * fit.radius_a == pytest.approx(100.0, rel=0.15)
        assert fit.z == pytest.approx(32.0, abs=2.0) and abs(fit.z_lo - 20) <= 3 and abs(fit.z_hi - 44) <= 3
        assert fit.snr > 10.0 and fit.flag == ''

    # test_widths: widths across the range are measured
    @pytest.mark.parametrize('width', [70.0, 150.0, 260.0])
    def test_widths(self, width: float) -> None:
        fit = _fit(_rod(60.0, width_a=width), _offset_pick(60.0, 0.0, 30.0, 30.0), width_range_a=(60.0, 320.0), width_steps=4)
        assert 2 * fit.radius_a == pytest.approx(width, rel=0.15)

    # test_z_extent_follows_filament: the z extent and its middle come from the filament and not from where the pick was made
    @pytest.mark.parametrize('pick_z', [22.0, 32.0, 42.0])
    def test_z_extent_follows_filament(self, pick_z: float) -> None:
        fit = _fit(_rod(20.0, z_range=(20, 45)), _offset_pick(20.0, 0.0, 0.0, pick_z))
        assert fit.z == pytest.approx(32.0, abs=2.0) and abs(fit.z_lo - 20) <= 3 and abs(fit.z_hi - 44) <= 3

    # test_pick_snaps_back: a pick as far from the axis as the search allows still finds it, flagged moved
    def test_pick_snaps_back(self) -> None:
        fit = _fit(_rod(70.0), _offset_pick(70.0, 0.0, 250.0, 30.0))
        assert _across(fit.x, fit.y, 70.0) < 1.5 and 'moved' in fit.flag.split(',')

    # test_pick_in_noise_is_weak: a pick where there is no filament gets a low SNR and the weak flag, and nothing raises
    def test_pick_in_noise_is_weak(self) -> None:
        fit = _fit(np.random.default_rng(5).normal(0.0, 1.0, SHAPE).astype(np.float32), (130.0, 130.0, 30.0))
        assert 'weak' in fit.flag.split(',') and fit.snr < 3.0

    # test_faint_filament_is_found: a filament well under the noise in a single voxel is still found by the slab
    def test_faint_filament_is_found(self) -> None:
        fit = _fit(_rod(40.0, amp=0.4), _offset_pick(40.0, 0.0, 30.0, 30.0))
        assert _across(fit.x, fit.y, 40.0) < 1.5 and _turn(fit.psi_deg, 40.0) < 5.0 and 'weak' not in fit.flag.split(',')

    # test_nearer_filament_wins: of two parallel filaments the one nearer the pick is fitted
    def test_nearer_filament_wins(self) -> None:
        a, b = _rod(90.0, centre=(70.0, 130.0), seed=1), _rod(90.0, centre=(190.0, 130.0), seed=2, noise=False)
        vol = a + b
        near_a, near_b = _fit(vol, (85.0, 130.0, 30.0)), _fit(vol, (175.0, 130.0, 30.0))
        assert near_a.x == pytest.approx(70.0, abs=1.5) and near_b.x == pytest.approx(190.0, abs=1.5)

    # test_edge_flagged: a filament running off the volume is flagged and its fit stays inside
    def test_edge_flagged(self) -> None:
        fit = _fit(_rod(0.0, centre=(25.0, 130.0), length_a=800.0), (25.0, 130.0, 30.0))
        assert 'edge' in fit.flag.split(',') and 0 <= fit.x < SHAPE[2]

    # test_z_edge_flagged: a filament reaching the first plane is flagged zedge
    def test_z_edge_flagged(self) -> None:
        fit = _fit(_rod(70.0, z_range=(0, 18)), (130.0, 130.0, 8.0))
        assert 'zedge' in fit.flag.split(',') and fit.z_lo == 0

    # test_spot_is_short: a round spot is traced as a stretch no longer than it is wide and flagged short
    def test_spot_is_short(self) -> None:
        fit = _fit(_rod(0.0, length_a=110.0, width_a=110.0, amp=2.0), (130.0, 130.0, 30.0))
        assert 'short' in fit.flag.split(',')

    # test_box_from_segment: the default box holds the measured length of filament, and the width box is smaller
    def test_box_from_segment(self) -> None:
        vol, pick = _rod(35.0), _offset_pick(35.0, 100.0, 20.0, 30.0)
        assert _fit(vol, pick).box_a == pytest.approx(1200.0, rel=0.15)
        assert _fit(vol, pick, box_from='width').box_a == pytest.approx(1.25 * 100.0, rel=0.2)

    # test_segment_is_capped: a filament longer than the longest stretch gets a box of that length
    def test_segment_is_capped(self) -> None:
        fit = _fit(_rod(0.0, length_a=3000.0), (130.0, 130.0, 30.0), max_length_a=1000.0)
        assert fit.box_a == pytest.approx(1000.0, rel=0.1)

    # test_segment_centres_on_stretch: with the segment box the fit sits at the middle of the stretch, however far along it the pick was
    def test_segment_centres_on_stretch(self) -> None:
        fit = _fit(_rod(0.0, length_a=800.0), _offset_pick(0.0, 250.0, 0.0, 30.0))
        assert fit.x == pytest.approx(130.0, abs=6.0)

    # test_width_box_keeps_position_along_axis: with the width box the fit stays level with the pick along the filament
    def test_width_box_keeps_position_along_axis(self) -> None:
        fit = _fit(_rod(0.0), _offset_pick(0.0, 250.0, 40.0, 30.0), box_from='width')
        assert fit.x == pytest.approx(130.0 + 250.0 / PX, abs=1.5) and _across(fit.x, fit.y, 0.0) < 1.0

    # test_kind_box_wins: a kind with its own box keeps it
    def test_kind_box_wins(self) -> None:
        fit = _fit(_rod(35.0), _offset_pick(35.0, 0.0, 20.0, 30.0), kind=Kind(marker_a=100, box_a=333.0, estimator='filament'))
        assert fit.box_a == 333.0

    # test_minimum_box: a thin short filament still gets the smallest box
    def test_minimum_box(self) -> None:
        fit = _fit(_rod(35.0, width_a=60.0, length_a=200.0), (130.0, 130.0, 30.0), box_from='width', min_box_a=250.0, width_range_a=(50.0, 200.0))
        assert fit.box_a == 250.0
