'''
pickmix: cubic MRC boxes cut from the tomograms at the fitted centres
'''

# Import external dependencies
import mrcfile, numpy as np
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# Import internal pickmix objects
from pickmix.config import Config, Kind
from pickmix.export import Item, recommend_box
from pickmix.utils.io import Tomogram, load_volume

# ExtractSummary: what an extraction of one kind wrote
@dataclass(frozen=True)
class ExtractSummary:
    kind: str
    written: int
    box_px: int
    pixel_size: float
    folder: Path

# crop_box: cubic crop centred on (z, y, x) voxel indices, padded with the crop's own mean where it leaves the volume
def crop_box(vol: np.ndarray, centre: tuple[int, int, int], box: int) -> np.ndarray:
    half = box // 2
    src = tuple(slice(max(c - half, 0), min(c - half + box, n)) for c, n in zip(centre, vol.shape, strict=True))
    block = np.asarray(vol[src], dtype=np.float32)
    out = np.full((box, box, box), block.mean(), dtype=np.float32)
    out[tuple(slice(s.start - (c - half), s.stop - (c - half)) for s, c in zip(src, centre, strict=True))] = block
    return out

# extract_kind: write out_dir/particles/<kind>/<tomogram>/<tomogram>_NNN.mrc at the reconstruction sampling; one even box for the whole kind
def extract_kind(
    name: str, kind: Kind, items: list[Item], tomos: dict[str, Tomogram], config: Config,
    *, log: Callable[[str], None] = lambda _: None,
) -> ExtractSummary:
    if not items:
        raise ValueError(f'kind {name!r}: nothing to extract')
    sizes = {tomos[p.tomogram].pixel_size for p, _ in items}
    if len(sizes) > 1:
        raise ValueError(f'kind {name!r}: one box in pixels needs one pixel size, got {sorted(sizes)!r}')
    px = sizes.pop()
    box_a, _ = recommend_box(kind, items)
    # even box, so the centre voxel sits at box // 2
    box = max(int(round(box_a / px / 2)) * 2, 2)
    folder = config.out_dir / 'particles' / name
    for tomogram in sorted({p.tomogram for p, _ in items}):
        vol = load_volume(tomos[tomogram], source=config.source)
        mine = [f for p, f in items if p.tomogram == tomogram]
        for i, f in enumerate(mine):
            dest = folder / tomogram / f'{tomogram}_{i:03d}.mrc'
            dest.parent.mkdir(parents=True, exist_ok=True)
            with mrcfile.new(dest, overwrite=True) as mrc:
                mrc.set_data(crop_box(vol, (round(f.z), round(f.y), round(f.x)), box))
                mrc.voxel_size = px
        log(f'{name} {tomogram}: {len(mine)} boxes')
    return ExtractSummary(name, len(items), box, px, folder)
