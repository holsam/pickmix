'''
pickmix: mean projection and montage of a kind's boxes
'''

# Import external dependencies
import math, imageio.v3 as iio, numpy as np
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from skimage.util import montage

# Import internal pickmix objects
from pickmix.config import Config, Kind
from pickmix.export import Item
from pickmix.extract import box_pixels, crop_box, pixel_size_of
from pickmix.utils.io import Tomogram, load_volume

# _MONTAGE_MAX: most boxes shown in the montage, spread evenly over the picks
_MONTAGE_MAX: int = 64

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

# average_kind: cut a box at every item, project the central slab of each along z, normalise it, and average per tomogram and overall; PNGs go to out_dir/average/<kind>/
def average_kind(
    name: str, kind: Kind, items: list[Item], tomos: dict[str, Tomogram], config: Config,
    *, log: Callable[[str], None] = lambda _: None,
) -> AverageResult:
    if not items:
        raise ValueError(f'kind {name!r}: nothing to average')
    px = pixel_size_of(name, items, tomos)
    box = box_pixels(kind, items, px)
    # slab as thick as the particle, so the projection is not washed out by empty box
    half = min(max(round(kind.marker_a / 2 / px), 1), box // 2)
    centre = box // 2
    images: dict[str, list[np.ndarray]] = {}
    for tomogram in dict.fromkeys(p.tomogram for p, _ in items):
        vol = load_volume(tomos[tomogram], source=config.source)
        for p, f in items:
            if p.tomogram != tomogram:
                continue
            cube = crop_box(vol, (round(f.z), round(f.y), round(f.x)), box)
            img = cube[centre - half : centre + half + 1].mean(axis=0)
            images.setdefault(tomogram, []).append((img - img.mean()) / (img.std() or 1.0))
        log(f'{name} {tomogram}: {len(images[tomogram])} boxes')
    everything = [img for imgs in images.values() for img in imgs]
    chosen = np.linspace(0, len(everything) - 1, min(len(everything), _MONTAGE_MAX)).astype(int)
    grid = math.ceil(math.sqrt(len(chosen)))
    result = AverageResult(
        name, len(everything), box,
        np.mean(everything, axis=0),
        montage(np.stack([everything[i] for i in chosen]), grid_shape=(grid, grid), padding_width=2),
        {t: np.mean(imgs, axis=0) for t, imgs in images.items()},
        config.out_dir / 'average' / name,
    )
    result.folder.mkdir(parents=True, exist_ok=True)
    for stale in result.folder.glob('*.png'):
        stale.unlink()
    _save(result.folder / 'overall_mean.png', result.overall)
    _save(result.folder / 'overall_montage.png', result.montage)
    for tomogram, img in result.per_tomogram.items():
        _save(result.folder / f'{tomogram}_mean.png', img)
    return result

# _save: write an image stretched between its 1st and 99th percentiles as an 8-bit PNG
def _save(path: Path, arr: np.ndarray) -> None:
    lo, hi = np.percentile(arr, (1, 99))
    iio.imwrite(path, np.clip((arr - lo) * (255.0 / max(hi - lo, 1e-6)), 0, 255).astype(np.uint8))
