'''
pickmix: lock so one pickmix process at a time works on a project
'''

# Import external dependencies
import os, socket, sys, time
from pathlib import Path
from typing import IO, Self

# fcntl: Unix only so None on Windows
try:
    import fcntl
except ImportError:
    fcntl = None

# LOCK_NAME: lockfile in out_dir
LOCK_NAME: str = '.pickmix.lock'

# ProjectBusy: another pickmix process has project open
class ProjectBusy(Exception):
    pass

# ProjectLock: exclusive advisory lock on project, held until release or process ends, however it ends
class ProjectLock:
    # __init__: take lock or raise ProjectBusy naming holder
    def __init__(self, out_dir: Path, what: str) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        self.path = out_dir / LOCK_NAME
        # False when nothing can be locked, so project is open but unprotected
        self.protected = fcntl is not None
        self._handle: IO[str] | None = open(self.path, 'a+')
        if fcntl is not None:
            try:
                fcntl.flock(self._handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self._handle.close()
                self._handle = None
                raise ProjectBusy(f'{str(out_dir)!r} is in use by {self._holder()}; close it first') from None
            except OSError:
                self.protected = False
        if not self.protected:
            print('[pickmix] lock files are not supported on Windows, so do not open the GUI and candidate-search on one project at once', file=sys.stderr)
        self._handle.seek(0)
        self._handle.truncate()
        self._handle.write(f'{what} (pid {os.getpid()} on {socket.gethostname()}, since {time.strftime("%Y-%m-%d %H:%M")})')
        self._handle.flush()

    # release: let go of lock
    def release(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    # __enter__, __exit__: hold lock for a with block
    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.release()

    # _holder: what wrote lock file
    def _holder(self) -> str:
        try:
            return self.path.read_text().strip() or 'another pickmix process'
        except OSError:
            return 'another pickmix process'
