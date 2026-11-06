'''
pickmix: tests for background template matching service
'''

# Import external dependencies
import mrcfile, time, numpy as np, pytest
from collections.abc import Callable, Iterator
from pathlib import Path

# Import internal pickmix objects
from pickmix.config import Config, Kind, save_config
from pickmix.matcher import MatchService
from pickmix.model import Session
from pickmix.project import open_project

# STAR: tomograms.star for tomograms of 128 x 96 x 48 voxels at 5.36 Angstrom, binned 4 from 1.34
STAR = '''data_global

loop_
_rlnTomoName #1
_rlnTomoTiltSeriesPixelSize #2
_rlnTomoTomogramBinning #3
_rlnTomoSizeX #4
_rlnTomoSizeY #5
_rlnTomoSizeZ #6
_rlnTomoReconstructedTomogram #7
'''

# _blob: a smooth 3D bump in a cube of odd side
def _blob(side: int) -> np.ndarray:
    c = side // 2
    z, y, x = np.ogrid[:side, :side, :side]
    return np.exp(-(((z - c) ** 2 + (y - c) ** 2 + (x - c) ** 2) / (2 * 4.0**2))).astype(np.float32)

# blobs: session with two tomograms containing planted blobs
@pytest.fixture
def blobs(tmp_path: Path) -> Iterator[tuple[Session, dict[str, list[tuple[int, int, int]]]]]:
    (tmp_path / 'raw').mkdir()
    planted = {'A': [(40, 40, 24), (80, 60, 24)], 'B': [(30, 30, 24), (90, 50, 20)]}
    rows = []
    for i, (name, centres) in enumerate(planted.items()):
        vol = np.random.default_rng(i).normal(0, 1, (48, 96, 128)).astype(np.float32)
        for x, y, z in centres:
            vol[z - 12 : z + 13, y - 12 : y + 13, x - 12 : x + 13] += 4 * _blob(25)
        with mrcfile.new(tmp_path / 'raw' / f'nt_raw4_{name}_stack_Vol.mrc') as mrc:
            mrc.set_data(vol)
            mrc.voxel_size = 5.36
        rows.append(f'{name} 1.34 4.0 512 384 192 Tomograms/job006/tomograms/{name}_stack_Vol.mrc')
    (tmp_path / 't.star').write_text(STAR + '\n'.join(rows) + '\n')
    config = Config(raw_dir=tmp_path / 'raw', tomograms_star=tmp_path / 't.star', out_dir=tmp_path / 'out', kinds={'blob': Kind(marker_a=100, box_a=150)})
    save_config(config, tmp_path / 'config.toml')
    yield Session(open_project(tmp_path / 'config.toml')), planted

# _wait: block until service is idle
def _wait(service: MatchService) -> None:
    deadline = time.time() + 20
    while service.busy and time.time() < deadline:
        time.sleep(0.02)
    assert not service.busy

class TestMatcher:
    # test_scan_finds_blobs: picks in visited tomogram lead to candidates at the planted blobs of the unvisited one
    def test_scan_finds_blobs(self, blobs: tuple[Session, dict]) -> None:
        session, planted = blobs
        for x, y, z in planted['A']:
            session.store.add('A', 'blob', x, y, z)
        service = MatchService(session)
        service.start('blob')
        _wait(service)
        assert service.last_error == '' and service.done == service.total == 1 and service.skipped == []
        found = session.candidates.candidates('B', 'blob', min_score=0.3)
        assert len(found) == 2
        for x, y, z in planted['B']:
            assert any(max(abs(c.x - x), abs(c.y - y), abs(c.z - z)) <= 2 for c in found)
        # A is visited and not scanned
        assert session.candidates.count('blob', 'A') == 0
        service.shutdown()

    # test_binned_volumes_cached: the binned volume is written once and reused
    def test_binned_volumes_cached(self, blobs: tuple[Session, dict]) -> None:
        session, planted = blobs
        session.store.add('A', 'blob', *planted['A'][0])
        service = MatchService(session)
        service.start('blob')
        _wait(service)
        files = sorted((session.project.config.out_dir / 'cache' / 'binned').glob('*.npy'))
        assert len(files) == 1 and not any('partial' in f.name for f in files)
        stamp = files[0].stat().st_mtime_ns
        service.start('blob')
        _wait(service)
        assert files[0].stat().st_mtime_ns == stamp
        service.shutdown()

    # test_no_picks_is_an_error: a kind with no picks reports why instead of scanning
    def test_no_picks_is_an_error(self, blobs: tuple[Session, dict]) -> None:
        session, _ = blobs
        service = MatchService(session)
        service.start('blob')
        _wait(service)
        assert 'nothing to build a template from' in service.last_error and session.candidates.count('blob') == 0
        service.shutdown()

    # test_nothing_to_scan_when_all_visited: with every tomogram visited the scan finishes with no candidates
    def test_nothing_to_scan_when_all_visited(self, blobs: tuple[Session, dict]) -> None:
        session, planted = blobs
        session.store.add('A', 'blob', *planted['A'][0])
        session.go(1)
        service = MatchService(session)
        service.start('blob')
        _wait(service)
        assert service.last_error == '' and service.total == 0 and session.candidates.count('blob') == 0
        service.shutdown()

    # test_stop: stopping ends the scan without an error and leaves what was found
    def test_stop(self, blobs: tuple[Session, dict]) -> None:
        session, planted = blobs
        session.store.add('A', 'blob', *planted['A'][0])
        service = MatchService(session)
        service.start('blob')
        service.stop()
        _wait(service)
        assert service.last_error == '' and service.done <= service.total
        service.shutdown()

    # test_progress_is_announced: listeners hear the start, each tomogram and the end
    def test_progress_is_announced(self, blobs: tuple[Session, dict]) -> None:
        session, planted = blobs
        session.store.add('A', 'blob', *planted['A'][0])
        service = MatchService(session)
        seen: list[tuple[int, int]] = []
        service.listeners.append(lambda: seen.append((service.done, service.total)))
        service.start('blob')
        _wait(service)
        assert seen[0] == (0, 0) and (1, 1) in seen
        service.shutdown()
