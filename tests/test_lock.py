'''
pickmix: tests for project lock
'''

# Import external dependencies
import os, pytest, socket, time
from pathlib import Path

# Import internal pickmix objects
from pickmix.lock import ProjectBusy, ProjectLock

class TestProjectLock:
    # test_second_holder_is_refused: a held lock refuses another and names the holder
    def test_second_holder_is_refused(self, tmp_path: Path) -> None:
        with ProjectLock(tmp_path / 'out', 'GUI') as first:
            with pytest.raises(ProjectBusy, match=r'GUI \(pid \d+ on '):
                ProjectLock(tmp_path / 'out', 'candidate-search')

    # test_release_frees_it: after release, or leaving the with block, the lock can be taken again, and release twice is harmless
    def test_release_frees_it(self, tmp_path: Path) -> None:
        lock = ProjectLock(tmp_path, 'GUI')
        lock.release()
        lock.release()
        ProjectLock(tmp_path, 'GUI').release()

    # test_dead_local_holder_is_replaced: a lockfile left by a dead process on this host is taken over
    def test_dead_local_holder_is_replaced(self, tmp_path: Path) -> None:
        (tmp_path / '.pickmix.lock').write_text(f'GUI (pid 2147483646 on {socket.gethostname()}, since 2020-01-01 00:00)')
        ProjectLock(tmp_path, 'candidate-search').release()
        assert not (tmp_path / '.pickmix.lock').exists()

    # test_other_host_holder_is_respected: a fresh lockfile from another host is respected and the error says how to clear it
    def test_other_host_holder_is_respected(self, tmp_path: Path) -> None:
        (tmp_path / '.pickmix.lock').write_text('candidate-search (pid 1 on elsewhere, since 2020-01-01 00:00)')
        with pytest.raises(ProjectBusy, match='elsewhere.*delete'):
            ProjectLock(tmp_path, 'GUI')

    # test_release_leaves_foreign_file: release does not delete a lockfile that another process has since written
    def test_release_leaves_foreign_file(self, tmp_path: Path) -> None:
        lock = ProjectLock(tmp_path, 'GUI')
        lock.path.write_text('candidate-search (pid 1 on elsewhere, since 2020-01-01 00:00)')
        lock.release()
        assert lock.path.exists()

    # test_silent_other_host_holder_is_replaced: a lockfile from another host that has stopped being touched is taken over
    def test_silent_other_host_holder_is_replaced(self, tmp_path: Path) -> None:
        old = tmp_path / '.pickmix.lock'
        old.write_text('candidate-search (pid 1 on elsewhere, since 2020-01-01 00:00)')
        os.utime(old, (0, 0))
        ProjectLock(tmp_path, 'GUI').release()

    # test_held_lock_is_touched: the holder keeps touching the lockfile so it never looks stale
    def test_held_lock_is_touched(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr('pickmix.lock.BEAT_SECONDS', 0.05)
        with ProjectLock(tmp_path, 'GUI') as lock:
            os.utime(lock.path, (0, 0))
            time.sleep(0.3)
            assert lock.path.stat().st_mtime > 1
