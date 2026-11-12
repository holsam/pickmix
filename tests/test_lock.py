'''
pickmix: tests for project lock
'''

# Import external dependencies
import pytest
from pathlib import Path

# Import internal pickmix objects
from pickmix.lock import ProjectBusy, ProjectLock

class TestProjectLock:
    # test_second_holder_is_refused: a held lock refuses another and names the holder
    def test_second_holder_is_refused(self, tmp_path: Path) -> None:
        with ProjectLock(tmp_path / 'out', 'GUI') as first:
            assert first.protected
            with pytest.raises(ProjectBusy, match=r'GUI \(pid \d+ on '):
                ProjectLock(tmp_path / 'out', 'candidate-search')

    # test_release_frees_it: after release, or leaving the with block, the lock can be taken again, and release twice is harmless
    def test_release_frees_it(self, tmp_path: Path) -> None:
        lock = ProjectLock(tmp_path, 'GUI')
        lock.release()
        lock.release()
        ProjectLock(tmp_path, 'GUI').release()

    # test_no_fcntl_warns_and_opens: without fcntl (Windows) the project opens unprotected, with a warning on stderr
    def test_no_fcntl_warns_and_opens(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr('pickmix.lock.fcntl', None)
        with ProjectLock(tmp_path, 'GUI') as first, ProjectLock(tmp_path, 'candidate-search') as second:
            assert not first.protected and not second.protected
        assert 'lock files are not supported' in capsys.readouterr().err
