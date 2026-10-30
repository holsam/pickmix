'''
pickmix: shared test fixtures
'''

# Import external dependencies
import os, pytest
from collections.abc import Callable
from pathlib import Path

# set headless Qt for the GUI tests
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

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
