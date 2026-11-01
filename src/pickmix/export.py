'''
pickmix: RELION coordinate star files and box recommendation per kind
'''

# Import external dependencies
import numpy as np
from dataclasses import dataclass
from pathlib import Path

# Import internal pickmix objects
from pickmix.config import Kind
from pickmix.estimate.registry import Fit
from pickmix.model import Pick
from pickmix.utils.coords import to_centred_angstrom
from pickmix.utils.io import Tomogram
from pickmix.utils.star import write_star_loop

# Item: a pick with its current fit
type Item = tuple[Pick, Fit]

# KindSummary: what an export of one kind wrote
@dataclass(frozen=True)
class KindSummary:
    kind: str
    written: int
    below_snr: int
    dropped_flagged: int
    box_a: float
    box_px: int
    folder: Path

# recommend_box: (box edge in Angstrom, in pixels at the kind's extraction pixel size rounded up to even); the kind's own box if set, else a percentile of the fits
def recommend_box(kind: Kind, items: list[Item], *, percentile: float = 95.0) -> tuple[float, int]:
    if kind.box_a > 0:
        box_a = kind.box_a
    elif items:
        box_a = float(np.percentile([fit.box_a for _, fit in items], percentile))
    else:
        return 0.0, 0
    box_px = int(np.ceil(box_a / kind.extract_angpix))
    return box_a, box_px + box_px % 2

# export_kind: write out_dir/relion/<kind>/particles.star and one NAME_coords.star per tomogram
def export_kind(
    name: str, kind: Kind, items: list[Item], tomos: dict[str, Tomogram], out_dir: Path,
    *, min_snr: float = 0.0, drop_flagged: bool = False, percentile: float = 95.0,
) -> KindSummary:
    kept = [(p, f) for p, f in items if f.snr >= min_snr and not (drop_flagged and f.flag)]
    below = sum(f.snr < min_snr for _, f in items)
    dropped = sum(bool(f.flag) for _, f in items if f.snr >= min_snr) if drop_flagged else 0
    if not kept:
        raise ValueError(f'kind {name!r}: no particles left after filtering')
    folder = out_dir / 'relion' / name
    for stale in folder.glob('*.star'):
        stale.unlink()
    rows = [(p.tomogram, *to_centred_angstrom((f.x, f.y, f.z), tomos[p.tomogram]), f.snr) for p, f in kept]
    _write(folder / 'particles.star', rows)
    for tomogram in sorted({r[0] for r in rows}):
        _write(folder / f'{tomogram}_coords.star', [r for r in rows if r[0] == tomogram])
    box_a, box_px = recommend_box(kind, kept, percentile=percentile)
    return KindSummary(name, len(kept), below, dropped, box_a, box_px, folder)

# _write: a particles table with centred Angstrom coordinates
def _write(path: Path, rows: list[tuple[str, float, float, float, float]]) -> None:
    columns = ['rlnTomoName', 'rlnCenteredCoordinateXAngst', 'rlnCenteredCoordinateYAngst', 'rlnCenteredCoordinateZAngst', 'rlnAutopickFigureOfMerit']
    write_star_loop(path, 'particles', columns, ((t, f'{x:.2f}', f'{y:.2f}', f'{z:.2f}', f'{s:.3f}') for t, x, y, z, s in rows))
