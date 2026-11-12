'''
pickmix: template building and normalised cross-correlation search
'''

# Import external dependencies
import math, numpy as np, os, scipy.fft
from collections.abc import Callable, Sequence
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

# bin_volume: mean of factor-sized blocks of a (z, y, x) volume, read a slab at a time
def bin_volume(vol: np.ndarray, factor: int, *, stop: Callable[[], bool] = lambda: False) -> np.ndarray:
    nz, ny, nx = (n // factor * factor for n in vol.shape)
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

# score_volume: normalised cross-correlation of binned volume with template under its mask
def score_volume(vol: np.ndarray, template: Template, *, workers: int = 2) -> np.ndarray:
    centred = vol - vol.mean()
    n = float(template.mask.sum())
    energy = float((template.kernel**2 / np.maximum(template.mask, 1e-6)).sum())
    kernel, mask = (k[::-1, ::-1, ::-1] for k in (template.kernel, template.mask))
    with scipy.fft.set_workers(workers):
        top = signal.fftconvolve(centred, kernel, mode='same')
        local_sum = signal.fftconvolve(centred, mask, mode='same')
        local_square = signal.fftconvolve(centred * centred, mask, mode='same')
    variance = local_square - local_sum * local_sum / n
    live = variance > 1e-2 * n * float(centred.var())
    score = np.zeros(centred.shape, dtype=np.float32)
    score[live] = top[live] / np.sqrt(variance[live] * energy)
    return score

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
    found = np.argwhere(maxima)
    values = inner[maxima]
    order = np.argsort(-values)[:_CANDIDATE_POOL]
    kept: list[tuple[tuple[int, int, int], float]] = []
    for o in order:
        centre = found[o]
        if all(((centre - np.array(k)) ** 2).sum() > separation**2 for k, _ in kept):
            kept.append(((int(centre[0]), int(centre[1]), int(centre[2])), float(values[o])))
            if len(kept) >= limit:
                break
    return kept

# scan: candidates in a binned volume, as Hits in reconstruction voxels, left out where within the separation of a known position (x, y, z in voxels)
def scan(
    binned: np.ndarray, template: Template, kind: Kind, config: Config, known: Sequence[tuple[float, float, float]] = (),
) -> list[Hit]:
    params = config.match
    separation = params.separation * kind.marker_a / (template.pixel_size * template.bin)
    peaks = find_peaks(
        score_volume(binned, template, workers=params.workers),
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

# binned_volume: tomogram binned by a factor, from out_dir/cache/binned when that is newer than the volume, else made and saved there
def binned_volume(tomo: Tomogram, factor: int, config: Config, stop: Callable[[], bool] = lambda: False) -> np.ndarray:
    path = volume_path(tomo, source=config.source)
    cached = config.out_dir / 'cache' / 'binned' / f'{path.stem}_x{factor}.npy'
    if cached.exists() and cached.stat().st_mtime >= path.stat().st_mtime:
        return np.load(cached)
    binned = bin_volume(load_volume(tomo, source=config.source), factor, stop=stop)
    cached.parent.mkdir(parents=True, exist_ok=True)
    partial = cached.with_name(cached.stem + '.partial.npy')
    np.save(partial, binned)
    os.replace(partial, cached)
    return binned

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
