'''
pickmix: mean projection and montage of a kind's boxes
'''

# Import external dependencies
import math, imageio.v3 as iio, numpy as np
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from scipy import ndimage
from skimage.util import montage

# Import internal pickmix objects
from pickmix.config import Config, Kind
from pickmix.estimate.registry import Fit
from pickmix.export import Item
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

# average_kind: cut a box at every item, project the central slab of each along z (slab of fit for filament, oriented so axis lies about x), normalise it, and average per tomogram and overall; nothing is written until save_average
def average_kind(
    name: str, kind: Kind, items: list[Item], tomos: dict[str, Tomogram], config: Config, *, log: Callable[[str], None] = lambda _: None) -> AverageResult:
    if not items:
        raise ValueError(f'kind {name!r}: nothing to average')
    px = pixel_size_of(name, items, tomos)
    box = box_pixels(kind, items, px)
    # slab as thick as the particle, so the projection is not washed out by empty box
    half = min(max(round(kind.marker_a / 2 / px), 1), box // 2)
    images: dict[str, list[np.ndarray]] = {}
    origins: list[str] = []
    for tomogram in dict.fromkeys(p.tomogram for p, _ in items):
        vol = load_volume(tomos[tomogram], source=config.source)
        for p, f in items:
            if p.tomogram != tomogram:
                continue
            img = _box_image(vol, f, box, half)
            images.setdefault(tomogram, []).append((img - img.mean()) / (img.std() or 1.0))
            origins.append(f'{len(images[tomogram])} ({tomogram})')
        log(f'{name} {tomogram}: {len(images[tomogram])} boxes')
    everything = [img for imgs in images.values() for img in imgs]
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
