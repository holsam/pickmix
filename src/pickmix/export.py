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
from pickmix.geometry import Parent
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
    unmatched: int
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

# export_kind: write out_dir/relion/<kind>/particles.star and one NAME_coords.star per tomogram; a kind with a parent writes the subtomogram angles from parents and leaves out picks without one
def export_kind(
    name: str, kind: Kind, items: list[Item], tomos: dict[str, Tomogram], out_dir: Path,
    *, min_snr: float = 0.0, drop_flagged: bool = False, percentile: float = 95.0, parents: dict[int, Parent] | None = None,
) -> KindSummary:
    kept = [(p, f) for p, f in items if f.snr >= min_snr and not (drop_flagged and f.flag)]
    below = sum(f.snr < min_snr for _, f in items)
    dropped = sum(bool(f.flag) for _, f in items if f.snr >= min_snr) if drop_flagged else 0
    matched = parents or {}
    unmatched = 0
    if kind.parent is not None:
        unmatched = sum(p.id not in matched for p, _ in kept)
        kept = [(p, f) for p, f in kept if p.id in matched]
    if not kept:
        raise ValueError(f'kind {name!r}: no particles left after filtering and parent matching')
    columns = ['rlnTomoName', 'rlnCenteredCoordinateXAngst', 'rlnCenteredCoordinateYAngst', 'rlnCenteredCoordinateZAngst', 'rlnAutopickFigureOfMerit']
    if kind.parent is not None:
        columns += ['rlnTomoSubtomogramRot', 'rlnTomoSubtomogramTilt', 'rlnTomoSubtomogramPsi', 'rlnAngleRot', 'rlnAngleTilt', 'rlnAnglePsi']
    if kind.tilt_prior_deg is not None:
        columns.append('rlnAngleTiltPrior')
    rows = []
    for p, f in kept:
        row = [p.tomogram, *(f'{v:.2f}' for v in to_centred_angstrom((f.x, f.y, f.z), tomos[p.tomogram])), f'{f.snr:.3f}']
        if kind.parent is not None:
            g = matched[p.id]
            # the angles RELION refines start at zero in the frame the subtomogram angles define
            row += [f'{g.rot:.4f}', f'{g.tilt:.4f}', f'{g.psi:.4f}', '0.0000', '0.0000', '0.0000']
        if kind.tilt_prior_deg is not None:
            row.append(f'{kind.tilt_prior_deg:.4f}')
        rows.append(row)
    folder = out_dir / 'relion' / name
    for stale in folder.glob('*.star'):
        stale.unlink()
    write_star_loop(folder / 'particles.star', 'particles', columns, rows)
    for tomogram in sorted({r[0] for r in rows}):
        write_star_loop(folder / f'{tomogram}_coords.star', 'particles', columns, [r for r in rows if r[0] == tomogram])
    box_a, box_px = recommend_box(kind, kept, percentile=percentile)
    return KindSummary(name, len(kept), below, dropped, unmatched, box_a, box_px, folder)
