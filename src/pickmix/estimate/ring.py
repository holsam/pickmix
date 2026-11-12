'''
pickmix: ring estimator, centre, radius and box of a pick from a z slab grown until ring SNR stops improving
'''

# Import external dependencies
import numpy as np
from dataclasses import dataclass
from skimage.feature import match_template

# Import internal pickmix objects
from pickmix.config import Config, Kind, RingParams
from pickmix.estimate.common import crop, prepare
from pickmix.estimate.registry import Fit, register

# Step: ring fit for one slab half-thickness k; y, x are crop coordinates, radius_px in voxels
@dataclass(frozen=True)
class Step:
    k: int
    y: float
    x: float
    radius_px: float
    snr: float

# ring: walk a z slab about the pick, fit a dark ring to its minimum projection, then scan the slab centre in z
@register('ring')
def ring(vol: np.ndarray, xyz: tuple[float, float, float], kind: Kind, pixel_size_a: float, config: Config) -> Fit:
    params, px = config.ring, pixel_size_a
    x0, y0, z0 = (round(v) for v in xyz)
    half = int(np.ceil((params.bg_range[1] * params.radius_range_a[1] + params.locate_range_a) / px))
    kmax = round(params.walk_max_half_a / px)
    shift = round(params.z_shift_a / px)
    sub, valid, zlo = crop(vol, z0 - kmax - shift, z0 + kmax + shift, y0, x0, half)
    zc = z0 - zlo
    best = _walk_z(sub, valid, zc, params, px)
    dz, snr = _scan_z(sub, valid, zc, best, shift, params, px)
    # crop centre is index half, so crop coordinates map back by (value - half)
    ex, ey, ez = x0 + (best.x - half), y0 + (best.y - half), z0 + dz
    radius_a = best.radius_px * px
    flags = []
    if min(ex, ey) - best.radius_px < 0 or ex + best.radius_px > vol.shape[2] - 1 or ey + best.radius_px > vol.shape[1] - 1:
        flags.append('edge')
    if zc + dz - best.k <= 0 or zc + dz + best.k >= sub.shape[0] - 1:
        flags.append('zedge')
    if best.k >= kmax:
        flags.append('zmax')
    return Fit(
        x=ex, y=ey, z=float(ez), radius_a=radius_a,
        box_a=kind.box_a if kind.box_a > 0 else 2 * radius_a * params.box_margin,
        snr=snr, z_lo=ez - best.k, z_hi=ez + best.k, flag=','.join(flags),
    )

# ring_template: dark gaussian ring of the given radius, zero elsewhere (low where the image should be low)
def ring_template(radius_px: float, sigma_px: float) -> np.ndarray:
    half = int(np.ceil(radius_px + 3 * sigma_px))
    yy, xx = np.mgrid[-half : half + 1, -half : half + 1]
    return (-np.exp(-0.5 * ((np.hypot(yy, xx) - radius_px) / sigma_px) ** 2)).astype(np.float32)

# ring_ncc: best normalised cross-correlation over a radius sweep, with the radius (voxels) that gave it
def ring_ncc(img: np.ndarray, radii_px: np.ndarray, sigma_px: float) -> tuple[np.ndarray, np.ndarray]:
    best = np.full(img.shape, -1.0, dtype=np.float32)
    radius = np.zeros(img.shape, dtype=np.float32)
    for r in radii_px:
        ncc = match_template(img, ring_template(float(r), sigma_px), pad_input=True)
        better = ncc > best
        best[better] = ncc[better]
        radius[better] = r
    return best, radius

# ring_snr: dark-ring contrast over background noise for a ring of radius_px centred at (y, x), valid voxels only
def ring_snr(img: np.ndarray, valid: np.ndarray, centre: tuple[float, float], radius_px: float, params: RingParams, pixel_size_a: float) -> float:
    d = _distance(img.shape, centre)
    ring_mask = valid & (np.abs(d - radius_px) <= params.ring_halfwidth_a / pixel_size_a)
    bg = valid & (d >= params.bg_range[0] * radius_px) & (d <= params.bg_range[1] * radius_px)
    # too little of either annulus inside the volume to say anything
    if ring_mask.sum() < 10 or bg.sum() < 10:
        return 0.0
    return float((img[bg].mean() - img[ring_mask].mean()) / (img[bg].std() + 1e-6))

# _walk_z: grow a symmetric slab about slice zc one slice at a time, returning the step with the best ring SNR
def _walk_z(sub: np.ndarray, valid: np.ndarray, zc: int, params: RingParams, px: float) -> Step:
    lo_r, hi_r = params.radius_range_a
    radii = np.arange(lo_r, hi_r + 1e-6, params.radius_step_a) / px
    sigma = params.ring_sigma_a / px
    kmax = round(params.walk_max_half_a / px)
    centre = (float(sub.shape[1] // 2), float(sub.shape[2] // 2))
    slab = sub[zc].copy()
    sweep = radii
    best: Step | None = None
    misses = 0
    for k in range(kmax + 1):
        if k:
            lo, hi = zc - k, zc + k
            # the slab has run out of volume on both sides
            if lo < 0 and hi >= sub.shape[0]:
                break
            for zi in (lo, hi):
                if 0 <= zi < sub.shape[0]:
                    slab = np.minimum(slab, sub[zi])
        img = prepare(slab, params.smooth_sigma_a, params.highpass_sigma_a, px)
        y, x, r = _locate(img, centre, sweep, sigma, params, px)
        r = _radial_radius(img, valid, (y, x), r, params, px)
        step = Step(k, y, x, r, ring_snr(img, valid, (y, x), r, params, px))
        # later steps only need the radii next to the current one
        centre, sweep = (y, x), radii[np.argsort(np.abs(radii - r))[:3]]
        if best is None or step.snr > best.snr:
            best, misses = step, 0
        else:
            misses += 1
            if misses >= params.walk_patience:
                break
    assert best is not None
    return best

# _distance: distance of every pixel from a (y, x) centre
def _distance(shape: tuple[int, ...], centre: tuple[float, float]) -> np.ndarray:
    yy, xx = np.indices(shape)
    return np.hypot(yy - centre[0], xx - centre[1])

# _locate: (y, x, radius_px) maximising ring NCC within locate_range of the previous centre
def _locate(img: np.ndarray, centre: tuple[float, float], radii: np.ndarray, sigma: float, params: RingParams, px: float) -> tuple[float, float, float]:
    ncc, radius = ring_ncc(img, radii, sigma)
    ncc = np.where(_distance(ncc.shape, centre) <= params.locate_range_a / px, ncc, -np.inf)
    y, x = np.unravel_index(np.argmax(ncc), ncc.shape)
    return float(y), float(x), float(radius[y, x])

# _radial_radius: radius (voxels) of the darkest annulus within one radius step of r0, from the 1-voxel radial profile
def _radial_radius(img: np.ndarray, valid: np.ndarray, centre: tuple[float, float], r0: float, params: RingParams, px: float) -> float:
    idx = np.rint(_distance(img.shape, centre)).astype(int)[valid]
    profile = np.bincount(idx, weights=img[valid]) / np.maximum(np.bincount(idx), 1)
    reach = params.radius_step_a / px
    lo, hi = max(int(r0 - reach), 1), min(int(r0 + reach) + 1, len(profile))
    return float(lo + np.argmin(profile[lo:hi]))

# _scan_z: slab centre shift (slices) maximising ring SNR for the best half-thickness and ring, with that SNR
def _scan_z(sub: np.ndarray, valid: np.ndarray, zc: int, best: Step, shift: int, params: RingParams, px: float) -> tuple[int, float]:
    scan = (0, best.snr)
    for dz in range(-shift, shift + 1):
        lo, hi = max(zc + dz - best.k, 0), min(zc + dz + best.k, sub.shape[0] - 1)
        img = prepare(sub[lo : hi + 1].min(axis=0), params.smooth_sigma_a, params.highpass_sigma_a, px)
        snr = ring_snr(img, valid, (best.y, best.x), best.radius_px, params, px)
        if snr > scan[1]:
            scan = (dz, snr)
    return scan
