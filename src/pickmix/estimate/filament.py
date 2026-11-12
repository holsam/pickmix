'''
pickmix: filament estimator, snaps a pick onto the axis of a dark filament and measures its direction, width, length and z extent
'''

# Import external dependencies
import math, numpy as np
from dataclasses import dataclass
from scipy import ndimage
from skimage.feature import hessian_matrix, hessian_matrix_eigvals

# Import internal pickmix objects
from pickmix.config import Config, FilamentParams, Kind
from pickmix.estimate.common import prepare
from pickmix.estimate.registry import Fit, register

# _FWHM_PER_SIGMA: full width at half maximum of a gaussian dip per unit of the Hessian scale that responds most strongly to it
_FWHM_PER_SIGMA: float = 1.665

# Trace: the stretch of ridge joined to the seed, in crop coordinates (y, x), with the axis as a unit vector (ux, uy) and the stretch's ends as distances along it from the seed
@dataclass(frozen=True)
class Trace:
    y: float
    x: float
    ux: float
    uy: float
    s_lo: float
    s_hi: float

    # length_px: how far the stretch reaches along the axis, in pixels
    @property
    def length_px(self) -> float:
        return self.s_hi - self.s_lo + 1.0

# filament: snap to the axis of the filament nearest the pick, find how far it reaches in z, then measure it on the slab of those planes
@register('filament')
def filament(vol: np.ndarray, xyz: tuple[float, float, float], kind: Kind, pixel_size_a: float, config: Config) -> Fit:
    params, px = config.filament, pixel_size_a
    x0, y0, z0 = (round(v) for v in xyz)
    z0 = min(max(z0, 0), vol.shape[0] - 1)
    widths = _widths(params, px)
    half = math.ceil((params.search_range_a + params.max_length_a / 2) / px) + math.ceil(params.width_range_a[1] / px)
    # first look: a slab about the pick, to find the axis
    k = round(params.slab_half_a / px)
    img, valid = _projection(vol, max(z0 - k, 0), min(z0 + k, vol.shape[0] - 1), y0, x0, half, params, px)
    ridge, scale = _ridge(img, valid, widths)
    seed = _seed(ridge, (half, half), params.search_range_a / px)
    trace = _trace(ridge, valid, seed, params, px)
    # z extent from the contrast of the filament plane by plane
    z_lo, z_hi, flags = _z_extent(vol, (x0, y0, z0), half, trace, float(widths[scale[seed]]), params, px)
    # second look: the slab of those planes, which has far less noise
    img, valid = _projection(vol, z_lo, z_hi, y0, x0, half, params, px)
    ridge, scale = _ridge(img, valid, widths)
    seed = _seed(ridge, (trace.y, trace.x), 2 * float(widths[scale[seed]]))
    trace = _trace(ridge, valid, seed, params, px)
    width_px = _width(img, trace, float(widths[scale[seed]]))
    (cy, cx), snr = _centre(img, trace, width_px)
    ends = [(cx + s * trace.ux, cy + s * trace.uy) for s in (trace.s_lo, trace.s_hi)]
    # the segment's middle, or the filament point nearest the pick, which keeps particles where they were picked along the axis
    along = (trace.s_lo + trace.s_hi) / 2 if params.box_from == 'segment' else (half - cx) * trace.ux + (half - cy) * trace.uy
    fx, fy = cx + along * trace.ux, cy + along * trace.uy
    width_a, length_a = width_px * px, trace.length_px * px
    # crop coordinates map back by (value - half)
    ex, ey = x0 + (fx - half), y0 + (fy - half)
    if any(not (1 <= x0 + (x - half) <= vol.shape[2] - 2 and 1 <= y0 + (y - half) <= vol.shape[1] - 2) for x, y in ends):
        flags.append('edge')
    if snr < params.weak_snr:
        flags.append('weak')
    if length_a < params.min_elongation * width_a:
        flags.append('short')
    if math.hypot(fx - half, fy - half) > 0.75 * params.search_range_a / px:
        flags.append('moved')
    box_a = max(width_a * params.box_margin, params.min_box_a)
    if params.box_from == 'segment':
        box_a = max(box_a, min(length_a, params.max_length_a))
    return Fit(
        x=ex, y=ey, z=(z_lo + z_hi) / 2, radius_a=width_a / 2, box_a=kind.box_a if kind.box_a > 0 else box_a,
        snr=snr, z_lo=z_lo, z_hi=z_hi, flag=','.join(flags), psi_deg=round(math.degrees(math.atan2(trace.uy, trace.ux)), 6) % 180.0,
    )

# _widths: the filament widths tried, in pixels, on a geometric ladder across the range
def _widths(params: FilamentParams, px: float) -> np.ndarray:
    lo, hi = params.width_range_a
    return np.geomspace(lo, hi, params.width_steps) / px

# _window: a (2 half + 1) square of a plane centred on voxel (y, x), edge padded where it leaves the plane, with a mask of the pixels that are real
def _window(plane: np.ndarray, y: int, x: int, half: int) -> tuple[np.ndarray, np.ndarray]:
    ys = slice(max(y - half, 0), min(y + half + 1, plane.shape[0]))
    xs = slice(max(x - half, 0), min(x + half + 1, plane.shape[1]))
    block = np.asarray(plane[ys, xs], dtype=np.float32)
    pad = ((ys.start - (y - half), (y + half + 1) - ys.stop), (xs.start - (x - half), (x + half + 1) - xs.stop))
    return np.pad(block, pad, mode='edge'), np.pad(np.ones(block.shape, dtype=bool), pad)

# _projection: mean of planes z_lo to z_hi (inclusive) in a window round (y, x), prepared, with the mask of real pixels
def _projection(vol: np.ndarray, z_lo: int, z_hi: int, y: int, x: int, half: int, params: FilamentParams, px: float) -> tuple[np.ndarray, np.ndarray]:
    ys = slice(max(y - half, 0), min(y + half + 1, vol.shape[1]))
    xs = slice(max(x - half, 0), min(x + half + 1, vol.shape[2]))
    mean = np.asarray(vol[z_lo : z_hi + 1, ys, xs]).mean(axis=0, dtype=np.float32)
    padded = np.zeros((vol.shape[1], vol.shape[2]), dtype=np.float32)
    padded[ys, xs] = mean
    window, valid = _window(padded, y, x, half)
    return prepare(window, params.smooth_sigma_a, params.highpass_sigma_a, px), valid

# _ridge: strongest dark-ridge response over the widths at every pixel, and the index of the width that gave it; blobs, which curve both ways, score nothing
def _ridge(img: np.ndarray, valid: np.ndarray, widths: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    best = np.zeros(img.shape, dtype=np.float32)
    which = np.zeros(img.shape, dtype=np.intp)
    for i, w in enumerate(widths):
        sigma = w / _FWHM_PER_SIGMA
        l1, l2 = hessian_matrix_eigvals(hessian_matrix(img, sigma=sigma, order='rc', use_gaussian_derivatives=True))
        response = (sigma**2 * np.maximum(l1 - np.abs(l2), 0)).astype(np.float32)
        better = response > best
        best[better], which[better] = response[better], i
    best[~valid] = 0
    return best, which

# _seed: the ridge pixel (y, x) with the best response within reach of a centre, nearer ones favoured
def _seed(ridge: np.ndarray, centre: tuple[float, float], reach_px: float) -> tuple[int, int]:
    yy, xx = np.indices(ridge.shape)
    d = np.hypot(yy - centre[0], xx - centre[1])
    score = np.where(d <= reach_px, ridge * np.exp(-0.5 * (d / max(reach_px, 1.0)) ** 2), -1.0)
    y, x = np.unravel_index(np.argmax(score), ridge.shape)
    return int(y), int(x)

# _trace: the stretch of strong ridge joined to the seed within max_length of it, with its axis and its extent along the axis from the seed
def _trace(ridge: np.ndarray, valid: np.ndarray, seed: tuple[int, int], params: FilamentParams, px: float) -> Trace:
    yy, xx = np.indices(ridge.shape)
    reach = params.max_length_a / 2 / px
    mask = (ridge >= params.ridge_fraction * ridge[seed]) & valid & (np.hypot(yy - seed[0], xx - seed[1]) <= reach)
    # close one pixel gaps so noise does not cut a filament in two, and keep the seed itself
    closed = ndimage.binary_closing(mask, structure=np.ones((3, 3), dtype=bool))
    closed[seed] = True
    labels, _ = ndimage.label(closed, structure=np.ones((3, 3), dtype=bool))
    ys, xs = np.nonzero((labels == labels[seed]) & mask)
    if len(ys) < 3:
        return Trace(float(seed[0]), float(seed[1]), 1.0, 0.0, 0.0, 0.0)
    cy, cx = ys.mean(), xs.mean()
    _, vectors = np.linalg.eigh(np.cov(np.vstack([xs - cx, ys - cy])))
    ux, uy = (float(v) for v in vectors[:, -1])
    s = (xs - seed[1]) * ux + (ys - seed[0]) * uy
    return Trace(float(seed[0]), float(seed[1]), ux, uy, float(s.min()), float(s.max()))

# _strip: a plane sampled on a grid along an axis (columns, s) and across it (rows, t), both in pixels from a point (y, x)
def _strip(plane: np.ndarray, point: tuple[float, float], u: tuple[float, float], s: np.ndarray, t: np.ndarray) -> np.ndarray:
    ss, tt = np.meshgrid(s, t)
    ys = point[0] + ss * u[1] + tt * u[0]
    xs = point[1] + ss * u[0] - tt * u[1]
    return ndimage.map_coordinates(plane, [ys, xs], order=1, mode='nearest')

# _contrast: how much darker the core of a strip is than its flanks, and the pixel noise of the flanks; t is the row coordinate
def _contrast(strip: np.ndarray, t: np.ndarray, width_px: float) -> tuple[float, float]:
    core = np.abs(t) <= 0.25 * width_px
    flank = (np.abs(t) >= width_px) & (np.abs(t) <= 2 * width_px)
    return float(strip[flank].mean() - strip[core].mean()), float(strip[flank].std()) + 1e-6

# _z_extent: planes z_lo to z_hi, inclusive, over which the filament stays at least z_fraction as dark as at its darkest plane near the pick; flags say when the search or the volume ended it
def _z_extent(
    vol: np.ndarray, pick: tuple[int, int, int], half: int, trace: Trace, width_px: float, params: FilamentParams, px: float,
) -> tuple[int, int, list[str]]:
    x0, y0, z0 = pick
    reach = max(abs(trace.s_lo), abs(trace.s_hi), 2 * width_px)
    s = np.arange(-reach, reach + 1.0)
    t = np.arange(-math.ceil(2.5 * width_px), math.ceil(2.5 * width_px) + 1.0)
    first, last = max(z0 - round(params.z_max_half_a / px), 0), min(z0 + round(params.z_max_half_a / px), vol.shape[0] - 1)
    contrast = np.array([
        _contrast(_strip(_window(vol[z], y0, x0, half)[0], (trace.y, trace.x), (trace.ux, trace.uy), s, t), t, width_px)[0]
        for z in range(first, last + 1)
    ])
    smooth = ndimage.gaussian_filter1d(contrast, max(params.smooth_sigma_a / px, 1.0))
    # the darkest plane within the first slab, so a second filament far above or below is not taken for this one
    k = round(params.slab_half_a / px)
    near = np.arange(max(z0 - k, first), min(z0 + k, last) + 1) - first
    peak = int(near[np.argmax(smooth[near])])
    if smooth[peak] <= 0:
        return z0, z0, []
    keep = smooth >= params.z_fraction * smooth[peak]
    lo = hi = peak
    while lo > 0 and keep[lo - 1]:
        lo -= 1
    while hi < len(keep) - 1 and keep[hi + 1]:
        hi += 1
    flags = []
    if (lo == 0 and first > 0) or (hi == len(keep) - 1 and last < vol.shape[0] - 1):
        flags.append('zmax')
    if (lo == 0 and first == 0) or (hi == len(keep) - 1 and last == vol.shape[0] - 1):
        flags.append('zedge')
    return first + lo, first + hi, flags

# _width: full width at half depth of the dark profile across the traced stretch, interpolated; the ridge scale's width when the profile gives none
def _width(img: np.ndarray, trace: Trace, fallback_px: float) -> float:
    s = np.arange(trace.s_lo, trace.s_hi + 1.0)
    t = np.arange(-math.ceil(3 * fallback_px), math.ceil(3 * fallback_px) + 1.0)
    profile = _strip(img, (trace.y, trace.x), (trace.ux, trace.uy), s, t).mean(axis=1)
    edge = max(len(t) // 6, 1)
    baseline = float(np.concatenate([profile[:edge], profile[-edge:]]).mean())
    low = int(np.argmin(profile))
    depth = baseline - float(profile[low])
    if depth <= 0:
        return fallback_px
    level = baseline - depth / 2
    left = next((i for i in range(low, 0, -1) if profile[i - 1] >= level), None)
    right = next((i for i in range(low, len(profile) - 1) if profile[i + 1] >= level), None)
    if left is None or right is None:
        return fallback_px
    # the crossing lies between the pixel below the level and the one above it
    a = left - (level - profile[left]) / (profile[left - 1] - profile[left])
    b = right + (level - profile[right]) / (profile[right + 1] - profile[right])
    return max(float(b - a), 1.0)

# _centre: the point (y, x) of the seed's position along the axis moved across to the middle of the filament, and the SNR of the stretch
def _centre(img: np.ndarray, trace: Trace, width_px: float) -> tuple[tuple[float, float], float]:
    s = np.arange(trace.s_lo, trace.s_hi + 1.0)
    t = np.arange(-math.ceil(3 * width_px), math.ceil(3 * width_px) + 1.0)
    strip = _strip(img, (trace.y, trace.x), (trace.ux, trace.uy), s, t)
    profile = strip.mean(axis=1)
    # middle across the filament from the profile minimum, refined by a parabola through it
    i = int(np.argmin(profile))
    offset = float(t[i])
    if 0 < i < len(t) - 1:
        curve = profile[i - 1] - 2 * profile[i] + profile[i + 1]
        if curve > 0:
            offset += 0.5 * float(profile[i - 1] - profile[i + 1]) / float(curve)
    diff, noise = _contrast(strip, t, width_px)
    # across is the axis turned a quarter, so a step of offset moves x by -uy and y by ux
    return (trace.y + offset * trace.ux, trace.x - offset * trace.uy), diff / noise
