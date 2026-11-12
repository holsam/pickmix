'''
pickmix: template building and normalised cross-correlation search
'''

# Import external dependencies
import math, numpy as np, os, scipy.fft
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from scipy import ndimage, signal

# Import internal pickmix objects
from pickmix.candidates import Hit
from pickmix.config import Config, Kind
from pickmix.estimates import EstimateStore
from pickmix.extract import crop_box
from pickmix.model import Pick
from pickmix.utils.io import Tomogram, load_volume, volume_path

# _SLAB: planes of a tomogram read and binned at a time
_SLAB: int = 32

# _SCORE_VOXELS: binned voxels scored at a time, about 10 float32 copies of which are alive in a slab, bounding memory per worker
_SCORE_VOXELS: int = 16_000_000

# _CANDIDATE_POOL: peaks ranked per tomogram before the closest are thinned out
_CANDIDATE_POOL: int = 5000

# Cancelled: a scan was stopped part way
class Cancelled(Exception):
    pass

# Template: binned, masked mean of boxes around picks of a kind
@dataclass(frozen=True)
class Template:
    kind: str
    # mask times the zero-mean template (correlation kernel)
    kernel: np.ndarray
    # soft spherical weights of the same shape
    mask: np.ndarray
    # reconstruction voxels per template voxel
    bin: int
    # edge in binned voxels (odd so centre is a voxel)
    edge: int
    # reconstruction pixel size
    pixel_size: float
    # boxes averaged
    count: int

# template_geometry: bin/edge for a kind
def template_geometry(kind: Kind, config: Config, pixel_size: float) -> tuple[int, int]:
    box_a = kind.box_a or kind.marker_a * config.ring.box_margin
    box_px = max(box_a / pixel_size, 1.0)
    factor = max(math.ceil(box_px / config.match.template_px), 1)
    edge = max(round(box_px / factor), 3) | 1
    return factor, edge

# soft_sphere: weight 1 inside radius, falling to 0 over edge voxels with a cosine, in cube of side n
def soft_sphere(n: int, radius: float, edge: float = 2.0) -> np.ndarray:
    c = (n - 1) / 2
    z, y, x = np.ogrid[:n, :n, :n]
    r = np.sqrt((z - c) ** 2 + (y - c) ** 2 + (x - c) ** 2)
    t = np.clip((radius - r) / edge + 0.5, 0, 1)
    return (0.5 - 0.5 * np.cos(np.pi * t)).astype(np.float32)

# bin_cube: mean of factor x factor x factor blocks of a cube whose side is a multiple of factor
def bin_cube(cube: np.ndarray, factor: int) -> np.ndarray:
    n = cube.shape[0] // factor
    return cube.reshape(n, factor, n, factor, n, factor).mean(axis=(1, 3, 5))

# bin_volume: mean of factor-sized blocks of a (z, y, x) volume, read a slab at a time, into out when given
def bin_volume(vol: np.ndarray, factor: int, *, stop: Callable[[], bool] = lambda: False, out: np.ndarray | None = None) -> np.ndarray:
    nz, ny, nx = (n // factor * factor for n in vol.shape)
    # out lets the caller bin straight into a file-backed array
    if out is None:
        out = np.empty((nz // factor, ny // factor, nx // factor), dtype=np.float32)
    step = max(_SLAB // factor, 1) * factor
    for z in range(0, nz, step):
        if stop():
            raise Cancelled
        end = min(z + step, nz)
        block = np.asarray(vol[z:end, :ny, :nx], dtype=np.float32)
        out[z // factor : end // factor] = block.reshape((end - z) // factor, factor, ny // factor, factor, nx // factor, factor).mean(axis=(1, 3, 5))
    return out

# to_voxel: reconstruction voxel coordinate of the centre of a binned voxel
def to_voxel(index: float, factor: int) -> float:
    return index * factor + (factor - 1) / 2

# build_template: mean of the unit-variance boxes cut at each position (tomogram, x, y, z in voxels), binned, masked and made zero-mean under the mask
def build_template(
    name: str, kind: Kind, positions: list[tuple[str, float, float, float]], tomos: dict[str, Tomogram], config: Config,
) -> Template:
    if not positions:
        raise ValueError(f'kind {name!r}: nothing to build a template from')
    sizes = {tomos[t].pixel_size for t, *_ in positions}
    if len(sizes) > 1:
        raise ValueError(f'kind {name!r}: one template needs one pixel size, got {sorted(sizes)!r}')
    pixel_size = sizes.pop()
    factor, edge = template_geometry(kind, config, pixel_size)
    box = edge * factor
    total = np.zeros((edge, edge, edge), dtype=np.float64)
    for tomogram in dict.fromkeys(t for t, *_ in positions):
        vol = load_volume(tomos[tomogram], source=config.source)
        for t, x, y, z in positions:
            if t == tomogram:
                cube = crop_box(vol, (round(z), round(y), round(x)), box)
                total += bin_cube((cube - cube.mean()) / (cube.std() or 1.0), factor)
    mean = total / len(positions)
    radius = kind.marker_a / 2 / (pixel_size * factor) * config.match.mask_margin
    mask = soft_sphere(edge, min(radius, edge / 2))
    centred = mean - (mean * mask).sum() / mask.sum()
    return Template(name, (centred * mask).astype(np.float32), mask, factor, edge, pixel_size, len(positions))

# _slabs: (start, end, lo, hi) z ranges that tile nz planes in steps, each read with halo extra planes either side as (lo, hi)
def _slabs(nz: int, step: int, halo: int) -> Iterator[tuple[int, int, int, int]]:
    for z in range(0, nz, step):
        end = min(z + step, nz)
        yield z, end, max(z - halo, 0), min(end + halo, nz)

# _step: planes per slab, within the voxel budget but at least two halos thick so the overlap does not dominate
def _step(shape: tuple[int, ...], halo: int) -> int:
    return max(_SCORE_VOXELS // (shape[1] * shape[2]), 2 * halo, 1)

# _moments: mean and variance of a volume, a slab at a time in float64 so no full-size temporary is made
def _moments(vol: np.ndarray) -> tuple[float, float]:
    total = square = 0.0
    for z, end, _, _ in _slabs(vol.shape[0], _step(vol.shape, 0), 0):
        block = np.asarray(vol[z:end], dtype=np.float64)
        total += float(block.sum())
        square += float((block * block).sum())
    count = vol.size
    mean = total / count
    return mean, max(square / count - mean * mean, 0.0)

# _score_slab: normalised cross-correlation of a slab with template under its mask, given the whole volume's mean and variance
def _score_slab(slab: np.ndarray, template: Template, mean: float, spread: float, workers: int) -> np.ndarray:
    centred = slab - np.float32(mean)
    n = float(template.mask.sum())
    energy = float((template.kernel**2 / np.maximum(template.mask, 1e-6)).sum())
    kernel, mask = (k[::-1, ::-1, ::-1] for k in (template.kernel, template.mask))
    with scipy.fft.set_workers(workers):
        top = signal.fftconvolve(centred, kernel, mode='same')
        local_sum = signal.fftconvolve(centred, mask, mode='same')
        local_square = signal.fftconvolve(centred * centred, mask, mode='same')
    variance = local_square - local_sum * local_sum / n
    live = variance > 1e-2 * n * spread
    score = np.zeros(centred.shape, dtype=np.float32)
    score[live] = top[live] / np.sqrt(variance[live] * energy)
    return score

# score_volume: score of a whole binned volume, a slab at a time with a halo of one template edge so the result matches a single pass; used for checks, as scan_peaks never holds the whole score
def score_volume(vol: np.ndarray, template: Template, *, workers: int = 2) -> np.ndarray:
    mean, spread = _moments(vol)
    score = np.zeros(vol.shape, dtype=np.float32)
    for z, end, lo, hi in _slabs(vol.shape[0], _step(vol.shape, template.edge), template.edge):
        score[z:end] = _score_slab(vol[lo:hi], template, mean, spread, workers)[z - lo : end - lo]
    return score

# _thin: peaks best first, none closer than separation, from candidate (z, y, x) indices and their scores
def _thin(found: np.ndarray, values: np.ndarray, separation: float, limit: int) -> list[tuple[tuple[int, int, int], float]]:
    order = np.argsort(-values, kind='stable')[:_CANDIDATE_POOL]
    kept: list[tuple[tuple[int, int, int], float]] = []
    for o in order:
        centre = found[o]
        if all(((centre - np.array(k)) ** 2).sum() > separation**2 for k, _ in kept):
            kept.append(((int(centre[0]), int(centre[1]), int(centre[2])), float(values[o])))
            if len(kept) >= limit:
                break
    return kept

# find_peaks: up to limit local maxima of a score volume at or above min_score, best first, none closer than separation voxels and none within margin voxels of a face; (z, y, x) indices
def find_peaks(score: np.ndarray, *, min_score: float, separation: float, margin: int, limit: int) -> list[tuple[tuple[int, int, int], float]]:
    if min(score.shape) <= 2 * margin:
        return []
    inner = np.zeros_like(score)
    core = tuple(slice(margin, n - margin) for n in score.shape)
    inner[core] = score[core]
    reach = max(round(separation), 1)
    # a cheap box filter finds the maxima, then the closest are thinned out best first
    maxima = (inner == ndimage.maximum_filter(inner, size=2 * reach + 1, mode='constant')) & (inner >= min_score)
    return _thin(np.argwhere(maxima), inner[maxima], separation, limit)

# scan_peaks: find_peaks of the score of a binned volume, a slab at a time, so memory is a slab's worth rather than the volume's; vol may be file-backed
def scan_peaks(vol: np.ndarray, template: Template, *, workers: int, min_score: float, separation: float, margin: int, limit: int) -> list[tuple[tuple[int, int, int], float]]:
    if min(vol.shape) <= 2 * margin:
        return []
    nz, ny, nx = vol.shape
    reach = max(round(separation), 1)
    mean, spread = _moments(vol)
    found: list[np.ndarray] = []
    values: list[np.ndarray] = []
    for z, end, lo, hi in _slabs(nz, _step(vol.shape, template.edge + reach), template.edge + reach):
        score = _score_slab(vol[lo:hi], template, mean, spread, workers)
        # nothing within margin of a face of the whole volume
        score[: max(margin - lo, 0)] = 0
        score[max(nz - margin - lo, 0) :] = 0
        score[:, :margin] = score[:, ny - margin :] = score[:, :, :margin] = score[:, :, nx - margin :] = 0
        maxima = (score == ndimage.maximum_filter(score, size=2 * reach + 1, mode='constant')) & (score >= min_score)
        # only the slab's own planes count; its halo is there for the filter
        maxima[: z - lo] = False
        maxima[end - lo :] = False
        index, value = np.argwhere(maxima), score[maxima]
        keep = np.argsort(-value, kind='stable')[:_CANDIDATE_POOL]
        found.append(index[keep] + np.array([lo, 0, 0]))
        values.append(value[keep])
    if not found:
        return []
    return _thin(np.concatenate(found), np.concatenate(values), separation, limit)

# scan: candidates in a binned volume, as Hits in reconstruction voxels, left out where within the separation of a known position (x, y, z in voxels)
def scan(
    binned: np.ndarray, template: Template, kind: Kind, config: Config, known: Sequence[tuple[float, float, float]] = (),
) -> list[Hit]:
    params = config.match
    separation = params.separation * kind.marker_a / (template.pixel_size * template.bin)
    peaks = scan_peaks(
        binned, template, workers=params.workers,
        min_score=params.min_score, separation=separation, margin=max(template.edge // 4, 1), limit=params.max_per_tomogram + len(known),
    )
    hits = [Hit(to_voxel(x, template.bin), to_voxel(y, template.bin), to_voxel(z, template.bin), s) for (z, y, x), s in peaks]
    near = separation * template.bin
    free = [h for h in hits if all((h.x - kx) ** 2 + (h.y - ky) ** 2 + (h.z - kz) ** 2 > near**2 for kx, ky, kz in known)]
    return free[: params.max_per_tomogram]

# template_positions: where template is cut for each pick, at its fit when it has a current one
def template_positions(picks: Iterable[Pick], tomos: dict[str, Tomogram], estimates: EstimateStore | None = None) -> list[tuple[str, float, float, float]]:
    out = []
    for pick in picks:
        if pick.tomogram in tomos:
            fit = estimates.get(pick) if estimates else None
            out.append((pick.tomogram, *((fit.x, fit.y, fit.z) if fit else (pick.x, pick.y, pick.z))))
    return out

# binned_volume: tomogram binned by a factor, as a read-only file-backed array from out_dir/cache/binned, made there first when missing or older than the volume
def binned_volume(tomo: Tomogram, factor: int, config: Config, stop: Callable[[], bool] = lambda: False) -> np.ndarray:
    path = volume_path(tomo, source=config.source)
    cached = config.out_dir / 'cache' / 'binned' / f'{path.stem}_x{factor}.npy'
    if not (cached.exists() and cached.stat().st_mtime >= path.stat().st_mtime):
        vol = load_volume(tomo, source=config.source)
        cached.parent.mkdir(parents=True, exist_ok=True)
        partial = cached.with_name(cached.stem + '.partial.npy')
        out = np.lib.format.open_memmap(partial, mode='w+', dtype=np.float32, shape=tuple(n // factor for n in vol.shape))
        bin_volume(vol, factor, stop=stop, out=out)
        out.flush()
        del out
        os.replace(partial, cached)
    return np.load(cached, mmap_mode='r')

# scan_tomogram: hits per kind in one tomogram, plus kinds left out because pixel size differs from the template's
def scan_tomogram(tomo: Tomogram, templates: dict[str, Template], config: Config, known: dict[str, list[tuple[float, float, float]]], stop: Callable[[], bool] = lambda: False) -> tuple[dict[str, list[Hit]], list[str]]:
    hits: dict[str, list[Hit]] = {}
    skipped: list[str] = []
    # one binned volume per binning factor, shared by the kinds that use it
    volumes: dict[int, np.ndarray] = {}
    for name, template in templates.items():
        if abs(tomo.pixel_size / template.pixel_size - 1) > 0.01:
            skipped.append(name)
            continue
        if template.bin not in volumes:
            volumes[template.bin] = binned_volume(tomo, template.bin, config, stop)
        hits[name] = scan(volumes[template.bin], template, config.kinds[name], config, known.get(name, []))
    return hits, skipped
