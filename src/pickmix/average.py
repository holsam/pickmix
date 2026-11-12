'''
pickmix: mean projection and montage of a kind's boxes
'''

# Import external dependencies
import math, imageio.v3 as iio, numpy as np
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from scipy import ndimage
from skimage.transform import resize
from skimage.util import montage

# Import internal pickmix objects
from pickmix.config import Config, Kind
from pickmix.estimate.registry import Fit
from pickmix.export import Item
from pickmix.model import Pick
from pickmix.extract import box_pixels, crop_box, pixel_size_of
from pickmix.utils.io import Tomogram, load_volume

# _MONTAGE_MAX: most boxes shown in the montage, spread evenly over the picks
_MONTAGE_MAX: int = 64

# MONTAGE_PAD: pixels of padding around every cell of the montage
MONTAGE_PAD: int = 2

# AverageResult: normalised 2D images, ready to show; overall and per-tomogram means, and the montage
@dataclass(frozen=True)
class AverageResult:
    kind: str
    count: int
    box_px: int
    overall: np.ndarray
    montage: np.ndarray
    per_tomogram: dict[str, np.ndarray]
    folder: Path
    # montage geometry and label
    grid: int
    pad: int
    labels: list[str]
    # boxes averaged per tomogram
    counts: dict[str, int]
    # whether any box was turned so its filament axis lies along x
    aligned: bool = False

# box_images: the normalised projection of every item's box, tomogram by tomogram in order of first appearance, and the box edge in pixels. Each is the central slab of a box cut at the fit (the planes of the fit, turned so the axis lies along x, for a filament). A pick with a box of its own is cut at that size and resampled to the kind's box, so picks of different sizes can be compared
def box_images(
    name: str, kind: Kind, items: list[Item], tomos: dict[str, Tomogram], config: Config,
    *, log: Callable[[str], None] = lambda _: None,
) -> tuple[list[tuple[Pick, np.ndarray]], int]:
    if not items:
        raise ValueError(f'kind {name!r}: nothing to average')
    px = pixel_size_of(name, items, tomos)
    box = box_pixels(kind, items, px)
    out: list[tuple[Pick, np.ndarray]] = []
    for tomogram in dict.fromkeys(p.tomogram for p, _ in items):
        vol = load_volume(tomos[tomogram], source=config.source)
        count = 0
        for p, f in items:
            if p.tomogram != tomogram:
                continue
            img = _sized_image(vol, p, f, box, kind, px)
            out.append((p, (img - img.mean()) / (img.std() or 1.0)))
            count += 1
        log(f'{name} {tomogram}: {count} boxes')
    return out, box

# average_kind: cut a box at every item, project the central slab of each along z (the slab of the fit for a filament, turned so its axis lies along x), normalise it, and average per tomogram and overall; nothing is written until save_average
def average_kind(
    name: str, kind: Kind, items: list[Item], tomos: dict[str, Tomogram], config: Config,
    *, log: Callable[[str], None] = lambda _: None, scores: dict[int, float] | None = None,
) -> AverageResult:
    pairs, box = box_images(name, kind, items, tomos, config, log=log)
    images: dict[str, list[np.ndarray]] = {}
    origins: list[str] = []
    for pick, img in pairs:
        images.setdefault(pick.tomogram, []).append(img)
        origins.append(f'{len(images[pick.tomogram])} ({pick.tomogram})')
    everything = [img for imgs in images.values() for img in imgs]
    if scores:
        # unscored picks go last
        ranked = sorted(range(len(pairs)), key=lambda i: scores.get(pairs[i][0].id, math.inf))
        chosen = np.array(ranked[:_MONTAGE_MAX])
        origins = [o if pairs[i][0].id not in scores else f'{o} {scores[pairs[i][0].id]:.2f}' for i, o in enumerate(origins)]
    else:
        chosen = np.linspace(0, len(everything) - 1, min(len(everything), _MONTAGE_MAX)).astype(int)
    grid = math.ceil(math.sqrt(len(chosen)))
    result = AverageResult(
        name, 
        len(everything), 
        box,
        np.mean(everything, axis=0),
        montage(np.stack([everything[i] for i in chosen]), grid_shape=(grid, grid), padding_width=MONTAGE_PAD),
        {t: np.mean(imgs, axis=0) for t, imgs in images.items()},
        config.out_dir / 'average' / name,
        grid, 
        MONTAGE_PAD, 
        [origins[i] for i in chosen],
        {t: len(imgs) for t, imgs in images.items()},
        any(f.psi_deg is not None for _, f in items),
    )
    return result

# _sized_image: the projection of one item's box at the kind's box edge. A pick with a box of its own is cut at that size, with the slab scaled to match, and resampled to the kind's box
def _sized_image(vol: np.ndarray, pick: Pick, fit: Fit, box: int, kind: Kind, px: float) -> np.ndarray:
    own = box if pick.box_a is None else max(int(round(pick.box_a / px / 2)) * 2, 2)
    # slab as thick as the particle, so the projection is not washed out by empty box
    half = min(max(round(kind.marker_a / 2 / px * own / box), 1), own // 2)
    img = _box_image(vol, fit, own, half)
    return img if own == box else resize(img, (box, box), order=1, anti_aliasing=own > box, preserve_range=True).astype(np.float32)

# save_average: clear the kind's old PNGs and write the overall mean and montage, and each tomogram's mean when asked; returns the paths written
def save_average(result: AverageResult, *, per_tomogram: bool = False) -> list[Path]:
    result.folder.mkdir(parents=True, exist_ok=True)
    for stale in result.folder.glob('*.png'):
        stale.unlink()
    written = [result.folder / 'overall_mean.png', result.folder / 'overall_montage.png']
    _save(written[0], result.overall)
    _save(written[1], result.montage)
    if per_tomogram:
        for tomogram, img in result.per_tomogram.items():
            written.append(result.folder / f'{tomogram}_mean.png')
            _save(written[-1], img)
    return written

# _box_image: projection of an item's box (fits without direction use central slab with half voxels either side, filament takes the planes z_lo to z_hi of fit from a box 1.5 times as wide, oriented so axis is along x)
def _box_image(vol: np.ndarray, fit: Fit, box: int, half: int) -> np.ndarray:
    centre = (round(fit.z), round(fit.y), round(fit.x))
    if fit.psi_deg is None:
        cube = crop_box(vol, centre, box)
        return cube[box // 2 - half : box // 2 + half + 1].mean(axis=0)
    # even, so the centre voxel sits at big // 2 as in crop_box
    big = 2 * math.ceil(box * 1.5 / 2)
    cube = crop_box(vol, centre, big)
    lo, hi = (min(max(z - centre[0] + big // 2, 0), big - 1) for z in (fit.z_lo, fit.z_hi))
    img = cube[lo : hi + 1].mean(axis=0)
    # a positive turn lays an axis at psi, measured from x towards y, along x
    turned = ndimage.rotate(img, fit.psi_deg, reshape=False, order=1, mode='constant', cval=float(img.mean()))
    start = (big - box) // 2
    return turned[start : start + box, start : start + box]

# _save: write an image stretched between its 1st and 99th percentiles as an 8-bit PNG
def _save(path: Path, arr: np.ndarray) -> None:
    lo, hi = np.percentile(arr, (1, 99))
    iio.imwrite(path, np.clip((arr - lo) * (255.0 / max(hi - lo, 1e-6)), 0, 255).astype(np.uint8))
