'''
pickmix: STAR file read/write and merging utilities
'''

# Import external dependencies
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

# read_star_loop: rows of the first loop_ in a star file as column-name to string dicts
def read_star_loop(path: Path) -> list[dict[str, str]]:
    columns: list[str] = []
    rows: list[dict[str, str]] = []
    in_loop = False
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line == 'loop_':
            # a second loop means the first one is finished
            if in_loop:
                break
            in_loop = True
        elif line.startswith('data_'):
            if in_loop:
                break
        elif in_loop and line.startswith('_'):
            columns.append(line.split()[0].removeprefix('_'))
        elif in_loop:
            rows.append(dict(zip(columns, line.split(), strict=True)))
    return rows

# write_star_loop: write one data block holding a single loop_ table
def write_star_loop(path: Path, block: str, columns: Sequence[str], rows: Iterable[Sequence[object]]) -> None:
    lines = [f'data_{block}', '', 'loop_', *(f'_{c} #{i}' for i, c in enumerate(columns, 1))]
    lines += [' '.join(str(v) for v in row) for row in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines) + '\n')

# MergeResult: the merged star file, how many tomograms it holds and which duplicates were left out
@dataclass(frozen=True)
class MergeResult:
    star: Path
    count: int
    skipped: tuple[str, ...]

# merge_tomograms: write a merged tomograms.star plus per-tomogram tilt-series stars under out_dir, names prefixed by run; runs are (run name, project root)
def merge_tomograms(runs: Sequence[tuple[str, Path]], tomo_job: str, out_dir: Path) -> MergeResult:
    # star files must hold absolute paths
    out_dir = out_dir.resolve()
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    skipped: list[str] = []
    for run, root in runs:
        if not run:
            raise ValueError(f'empty run name for {str(root)!r}')
        for row in read_star_loop(root / tomo_job / 'tomograms.star'):
            new = f'{run}_{row["rlnTomoName"]}'
            # first occurrence wins when a project lists a tomogram twice
            if new in seen:
                skipped.append(new)
                continue
            seen.add(new)
            ts_rows = read_star_loop(root / row['rlnTomoTiltSeriesStarFile'])
            for r in ts_rows:
                r['rlnMicrographName'] = _absolute(root, r['rlnMicrographName'])
            ts_path = out_dir / 'tilt_series' / f'{new}.star'
            _write_rows(ts_path, new, ts_rows)
            row['rlnTomoName'] = new
            row['rlnTomoTiltSeriesStarFile'] = str(ts_path)
            row['rlnTomoReconstructedTomogram'] = _absolute(root, row['rlnTomoReconstructedTomogram'])
            merged.append(row)
    if not merged:
        raise ValueError('no tomograms found in the given runs')
    star = out_dir / 'tomograms.star'
    _write_rows(star, 'global', merged)
    return MergeResult(star, len(merged), tuple(skipped))

# _absolute: resolve a path relative to a project root, leaving absolute paths alone
def _absolute(root: Path, value: str) -> str:
    return value if value.startswith('/') else str(root / value)

# _write_rows: write dict rows as a single-loop star data block
def _write_rows(path: Path, block: str, rows: list[dict[str, str]]) -> None:
    columns = list(rows[0]) if rows else []
    write_star_loop(path, block, columns, ([r[c] for c in columns] for r in rows))
