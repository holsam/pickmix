'''
pickmix: tomogram discovery and volume reading utilities
'''

# Import external dependencies
import mrcfile, sys, numpy as np
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# Import internal pickmix objects
from pickmix.config import Config
from pickmix.utils.star import read_star_loop

# Tomogram: one reconstruction paired with its RELION star row; shape is (z, y, x) at the reconstruction sampling
@dataclass(frozen=True)
class Tomogram:
    # RELION name from tomograms.star, e.g. raw2_Position_10_4
    name: str
    # file stem of the reconstruction as RELION knows it
    stem: str
    raw_path: Path
    denoised_path: Path | None
    # reconstruction (binned) voxel size from the MRC header
    pixel_size: float
    shape: tuple[int, int, int]
    # tilt-series (unbinned) voxel size, and tomogram size in unbinned voxels (x, y, z), from the star file
    unbinned_pixel_size: float
    size_xyz: tuple[int, int, int]

# TomogramError: a tomogram that cannot be used
class TomogramError(ValueError):
    # __init__: keep what could be read alongside the message
    def __init__(
        self, reason: str, detail: str, *,
        shape: tuple[int, int, int] | None = None, pixel_size: float | None = None, denoised: bool | None = None,
    ) -> None:
        super().__init__(detail)
        # short label for why tomogram can't be used
        self.reason = reason
        self.shape = shape
        self.pixel_size = pixel_size
        self.denoised = denoised

# find_tomograms: pair every tomograms.star row with its raw and denoised MRC, keyed by RELION name; bad tomograms go to the issues dict if given, else a warning on stderr
def find_tomograms(config: Config, *, issues: dict[str, TomogramError] | None = None) -> dict[str, Tomogram]:
    # each directory is listed once, not once per row
    raw = _index(config.raw_dir, '')
    denoised = _index(config.denoised_dir, config.denoised_suffix) if config.denoised_dir else None
    out: dict[str, Tomogram] = {}
    for row in read_star_loop(config.tomograms_star):
        name = row['rlnTomoName']
        try:
            out[name] = _build(row, raw, denoised)
        except TomogramError as e:
            if issues is None:
                print(f'skipped: {name!r}: {e}', file=sys.stderr)
            else:
                issues[name] = e
    return out

# volume_path: the denoised MRC when asked for and present, else the raw one
def volume_path(tomo: Tomogram, *, source: Literal['raw', 'denoised'] = 'denoised') -> Path:
    return tomo.denoised_path if source == 'denoised' and tomo.denoised_path else tomo.raw_path

# load_volume: read-only memory-mapped (z, y, x) volume
def load_volume(tomo: Tomogram, *, source: Literal['raw', 'denoised'] = 'denoised') -> np.ndarray:
    return mrcfile.mmap(volume_path(tomo, source=source), mode='r', permissive=True).data

# _Index: the MRC files of one directory with their stems, suffix removed
@dataclass(frozen=True)
class _Index:
    directory: Path
    entries: list[tuple[Path, str]]

# _index: list a directory once
def _index(directory: Path, suffix: str) -> _Index:
    return _Index(directory, [(p, p.stem.removesuffix(suffix)) for p in sorted(directory.glob('*.mrc'))])

# _build: Tomogram for one star row, raising if files are missing or disagree with the star
def _build(row: dict[str, str], raw_index: _Index, denoised_index: _Index | None) -> Tomogram:
    name = row['rlnTomoName']
    stem = Path(row['rlnTomoReconstructedTomogram']).stem
    raw = _match(raw_index, name, stem)
    if raw is None:
        raise TomogramError('no raw tomogram', f'no raw tomogram in {str(raw_index.directory)!r}')
    denoised = _match(denoised_index, name, stem) if denoised_index else None
    pixel_size, shape = _header(raw)
    seen = {'shape': shape, 'pixel_size': pixel_size, 'denoised': denoised is not None}
    binning = float(row['rlnTomoTomogramBinning'])
    unbinned = float(row['rlnTomoTiltSeriesPixelSize'])
    size_xyz = (int(row['rlnTomoSizeX']), int(row['rlnTomoSizeY']), int(row['rlnTomoSizeZ']))
    # the header and the star file must describe the same reconstruction
    expected = tuple(round(n / binning) for n in size_xyz)
    if any(abs(a - b) > 1 for a, b in zip(expected, shape[::-1], strict=True)):
        raise TomogramError('shape mismatch', f'header shape (z, y, x) {shape!r} disagrees with star size {size_xyz!r} at binning {binning}', **seen)
    if abs(pixel_size / (unbinned * binning) - 1.0) > 0.02:
        raise TomogramError('pixel size mismatch', f'header pixel size {pixel_size:.2f} disagrees with {unbinned} x {binning}', **seen)
    return Tomogram(name, stem, raw, denoised, pixel_size, shape, unbinned, size_xyz)

# _stem_matches: whether a file stem is <run prefix> + reconstruction stem, the prefix being the one the merged name carries
def _stem_matches(stem: str, name: str, recon: str) -> bool:
    prefix = stem.removesuffix(recon)
    if prefix == stem and recon:
        return False
    # the name is <prefix><original RELION name>, and the original name begins the reconstruction stem
    return name.startswith(prefix) and recon.startswith(name.removeprefix(prefix))

# _match: single MRC in an index whose stem matches the tomogram, or None
def _match(index: _Index, name: str, recon: str) -> Path | None:
    hits = [p for p, s in index.entries if _stem_matches(s, name, recon)]
    # unmerged star names carry no run prefix, so any prefixed file is accepted
    hits = hits or [p for p, s in index.entries if s == recon or s.endswith('_' + recon)]
    if len(hits) > 1:
        raise TomogramError('ambiguous match', f'{len(hits)} files in {str(index.directory)!r} match')
    return hits[0] if hits else None

# _header: voxel size and (z, y, x) shape from an MRC header without reading the data
def _header(path: Path) -> tuple[float, tuple[int, int, int]]:
    with mrcfile.open(path, permissive=True, header_only=True) as mrc:
        return float(mrc.voxel_size.x), (int(mrc.header.nz), int(mrc.header.ny), int(mrc.header.nx))
