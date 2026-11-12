'''
pickmix: lock so one pickmix process at a time works on a project
'''

# Import external dependencies
import atexit, os, re, signal, socket, sys, threading, time
from pathlib import Path
from typing import Self

# LOCK_NAME: lockfile in out_dir
LOCK_NAME: str = '.pickmix.lock'

# BEAT_SECONDS: how often the holder touches the lockfile
BEAT_SECONDS: float = 30.0

# STALE_SECONDS: lockfile untouched this long means its holder was killed (4x BEAT_SECONDS to allow for clock skew and filesystem lag)
STALE_SECONDS: float = 120.0

# ProjectBusy: another pickmix process has project open
class ProjectBusy(Exception):
    pass

# ProjectLock: lockfile made with O_EXCL and touched by a heartbeat thread while held, so a killed holder (SIGKILL, OOM) goes stale, and removed on release/normal exit/SIGTERM/SIGHUP
class ProjectLock:
    # __init__: take lock or raise ProjectBusy naming holder
    def __init__(self, out_dir: Path, what: str) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        self.path = out_dir / LOCK_NAME
        self._text = f'{what} (pid {os.getpid()} on {socket.gethostname()}, since {time.strftime("%Y-%m-%d %H:%M")})'
        self._held = False
        # second pass only after clearing a stale file
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if self._stale():
                    self.path.unlink(missing_ok=True)
                    continue
                raise ProjectBusy(f'{str(out_dir)!r} is in use by {self._holder()}; close it first, or delete {str(self.path)!r} if that process is gone') from None
            with os.fdopen(fd, 'w') as handle:
                handle.write(self._text)
            self._held = True
            break
        else:
            raise ProjectBusy(f'{str(out_dir)!r} could not be locked; delete {str(self.path)!r} if no pickmix process is using it')
        self._stop = threading.Event()
        threading.Thread(target=self._beat, daemon=True).start()
        atexit.register(self.release)
        _exit_on_signals()

    # release: let go of lock, removing file only if it is still this processes
    def release(self) -> None:
        if self._held:
            self._held = False
            self._stop.set()
            if self._holder() == self._text:
                self.path.unlink(missing_ok=True)

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

    # _beat: touch lockfile until released
    def _beat(self) -> None:
        while not self._stop.wait(BEAT_SECONDS):
            try:
                os.utime(self.path)
            except OSError:
                pass

    # _stale: holder is a dead process or has not touched the lockfile for STALE_SECONDS
    def _stale(self) -> bool:
        try:
            if time.time() - self.path.stat().st_mtime > STALE_SECONDS:
                return True
        except OSError:
            return False
        found = re.search(r'pid (\d+) on (\S+),', self._holder())
        # another host's pid cannot be checked, so only the age counts
        if found is None or found[2] != socket.gethostname():
            return False
        try:
            os.kill(int(found[1]), 0)
        except ProcessLookupError:
            return True
        except OSError:
            pass
        return False

# _exit_on_signals: turn SIGTERM and SIGHUP into a normal exit so locks are released, leaving any handler already set alone
def _exit_on_signals() -> None:
    if threading.current_thread() is not threading.main_thread():
        return
    for name in ('SIGTERM', 'SIGHUP'):
        number = getattr(signal, name, None)
        if number is not None and signal.getsignal(number) == signal.SIG_DFL:
            signal.signal(number, lambda *_: sys.exit(1))
