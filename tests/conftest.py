'''
pickmix: shared test fixtures
'''

# Import external dependencies
import mrcfile, os, pytest, numpy as np
from collections.abc import Callable
from pathlib import Path

# Import internal pickmix objects
from pickmix.config import Config, save_config

# set headless Qt for GUI tests
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

# STAR_HEAD: tomograms.star header; each tomogram is 32 x 24 x 16 voxels at 1.34 A, binned 4 to 8 x 6 x 4 at 5.36 A
STAR_HEAD = '''data_global

loop_
_rlnTomoName #1
_rlnTomoTiltSeriesPixelSize #2
_rlnTomoTomogramBinning #3
_rlnTomoSizeX #4
_rlnTomoSizeY #5
_rlnTomoSizeZ #6
_rlnTomoReconstructedTomogram #7
'''

# write_mrc: write a small MRC with the given voxel size and (z, y, x) shape, values counting up
def write_mrc(path: Path, voxel: float, shape: tuple[int, int, int]) -> None:
    with mrcfile.new(path) as mrc:
        mrc.set_data(np.arange(np.prod(shape), dtype=np.float32).reshape(shape))
        mrc.voxel_size = voxel

# make_config: factory writing raw and denoised MRCs, a star file and a config.toml under tmp_path, returning the config path
@pytest.fixture
def make_config(tmp_path: Path) -> Callable[..., Path]:
    # make: build the project; shape is (z, y, x), one tomogram per name
    def make(shape: tuple[int, int, int] = (4, 6, 8), names: tuple[str, ...] = ('Position_1_2',)) -> Path:
        (tmp_path / 'raw').mkdir()
        (tmp_path / 'den').mkdir()
        rows = []
        for n in names:
            write_mrc(tmp_path / 'raw' / f'nt_raw4_{n}_stack_Vol.mrc', 5.36, shape)
            write_mrc(tmp_path / 'den' / f'nt_raw4_{n}_stack_Vol.denoised.mrc', 5.36, shape)
            rows.append(f'{n} 1.34 4.0 32 24 16 Tomograms/job006/tomograms/{n}_stack_Vol.mrc')
        (tmp_path / 't.star').write_text(STAR_HEAD + '\n'.join(rows) + '\n')
        config = Config(raw_dir=tmp_path / 'raw', denoised_dir=tmp_path / 'den', denoised_suffix='.denoised', tomograms_star=tmp_path / 't.star')
        save_config(config, tmp_path / 'config.toml')
        return tmp_path / 'config.toml'
    return make

# relion_project: factory for a fake RELION project root with tomograms.star and one tilt-series star per name
@pytest.fixture
def relion_project() -> Callable[[Path, list[str]], None]:
    # make: write the project under root
    def make(root: Path, names: list[str]) -> None:
        job = root / 'Tomograms' / 'job006'
        job.mkdir(parents=True)
        (root / 'tilt_series').mkdir()
        lines = ['data_global', '', 'loop_', '_rlnTomoName #1', '_rlnTomoTiltSeriesStarFile #2', '_rlnTomoReconstructedTomogram #3']
        for n in names:
            lines.append(f'{n} tilt_series/{n}.star Tomograms/job006/tomograms/{n}_Vol.mrc')
            (root / 'tilt_series' / f'{n}.star').write_text('data_x\n\nloop_\n_rlnMicrographName #1\nframes/a.mrc\n')
        (job / 'tomograms.star').write_text('\n'.join(lines) + '\n')
    return make
