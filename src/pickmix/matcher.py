'''
pickmix: background template matching over the tomograms of a project
'''

# Import external dependencies
import numpy as np, os, threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

# Import internal pickmix objects
from pickmix.config import Config
from pickmix.estimates import EstimateStore
from pickmix.match import Cancelled, bin_volume, build_template, scan
from pickmix.model import Session
from pickmix.utils.io import Tomogram, load_volume, volume_path

# MatchService: builds a template from picks and scans unvisited tomograms for matches
class MatchService:
    # __init__: nothing runs until start
    def __init__(self, session: Session, estimates: EstimateStore | None = None) -> None:
        self.session = session
        self.estimates = estimates
        # called from the scanning thread after each tomogram and when a scan ends
        self.listeners: list[Callable[[], None]] = []
        self.kind: str | None = None
        self.total = 0
        self.done = 0
        self.last_error = ''
        # tomograms left out because their pixel size differs from the template's
        self.skipped: list[str] = []
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='pickmix-match')
        self._lock = threading.Lock()
        self._generation = 0
        self._active = 0
        self._closed = False

    # busy: whether a scan is queued or running
    @property
    def busy(self) -> bool:
        with self._lock:
            return self._active > 0

    # start: scan unvisited tomograms for matches
    def start(self, kind: str) -> None:
        if self._closed:
            return
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._active += 1
        self.kind, self.total, self.done, self.last_error, self.skipped = kind, 0, 0, '', []
        self._notify()
        self._pool.submit(self._run, kind, generation)

    # stop: end the scan after the step it is on
    def stop(self) -> None:
        with self._lock:
            self._generation += 1

    # shutdown: stop the thread
    def shutdown(self) -> None:
        self._closed = True
        self.stop()
        self._pool.shutdown(wait=False, cancel_futures=True)

    # _run: one scan; a failure is kept in last_error and a stop is not a failure
    def _run(self, kind: str, generation: int) -> None:
        try:
            self._scan(kind, lambda: self._generation != generation)
        except Cancelled:
            pass
        except Exception as e:
            self.last_error = f'{kind}: {type(e).__name__}: {e}'
        finally:
            with self._lock:
                self._active -= 1
            self._notify()

    # _positions: where the template is cut for each pick of a kind, at the fit when it has a current one
    def _positions(self, kind: str) -> list[tuple[str, float, float, float]]:
        out = []
        for pick in self.session.store.all(kind):
            if pick.tomogram in self.session.project.tomos:
                fit = self.estimates.get(pick) if self.estimates else None
                out.append((pick.tomogram, *((fit.x, fit.y, fit.z) if fit else (pick.x, pick.y, pick.z))))
        return out

    # _scan: build template then scan unvisited tomograms
    def _scan(self, name: str, stop: Callable[[], bool]) -> None:
        project = self.session.project
        config, tomos = project.config, project.tomos
        kind = config.kinds[name]
        template = build_template(name, kind, self._positions(name), tomos, config)
        names = [n for n in self.session.names if n not in self.session.visited]
        self.total = len(names)
        self._notify()
        for tomogram in names:
            if stop():
                raise Cancelled
            tomo = tomos[tomogram]
            if tomogram in self.session.visited:
                pass
            elif abs(tomo.pixel_size / template.pixel_size - 1) > 0.01:
                self.skipped.append(tomogram)
            else:
                binned = _binned(tomo, template.bin, config, stop)
                known = [(p.x, p.y, p.z) for p in self.session.store.picks(tomogram, name)]
                hits = scan(binned, template, kind, config, known)
                if stop():
                    raise Cancelled
                reach = config.match.separation * kind.marker_a / tomo.pixel_size
                self.session.candidates.replace(tomogram, name, hits, reach=reach)
            self.done += 1
            self._notify()

    # _notify: tell listeners
    def _notify(self) -> None:
        for listener in self.listeners:
            listener()

# _binned: the tomogram binned by a factor, from out_dir/cache/binned when that is newer than the volume, else made and saved there
def _binned(tomo: Tomogram, factor: int, config: Config, stop: Callable[[], bool]) -> np.ndarray:
    path = volume_path(tomo, source=config.source)
    cached = config.out_dir / 'cache' / 'binned' / f'{path.stem}_x{factor}.npy'
    if cached.exists() and cached.stat().st_mtime >= path.stat().st_mtime:
        return np.load(cached)
    binned = bin_volume(load_volume(tomo, source=config.source), factor, stop=stop)
    cached.parent.mkdir(parents=True, exist_ok=True)
    partial = cached.with_name(cached.stem + '.partial.npy')
    np.save(partial, binned)
    os.replace(partial, cached)
    return binned
