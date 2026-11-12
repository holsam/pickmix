'''
pickmix: background template matching over the tomograms of a project
'''

# Import external dependencies
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

# Import internal pickmix objects
from pickmix.estimates import EstimateStore
from pickmix.match import Cancelled, build_template, scan_tomogram, template_positions
from pickmix.model import Session

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

    # _scan: build template then scan unvisited tomograms
    def _scan(self, name: str, stop: Callable[[], bool]) -> None:
        project = self.session.project
        config, tomos = project.config, project.tomos
        kind = config.kinds[name]
        positions = template_positions(self.session.store.all(name), tomos, self.estimates)
        template = build_template(name, kind, positions, tomos, config)
        names = [n for n in self.session.names if n not in self.session.visited]
        self.total = len(names)
        self._notify()
        for tomogram in names:
            if stop():
                raise Cancelled
            tomo = tomos[tomogram]
            known = [(p.x, p.y, p.z) for p in self.session.store.picks(tomogram, name)]
            hits, skipped = scan_tomogram(tomo, {name: template}, config, {name: known}, stop)
            if stop():
                raise Cancelled
            if skipped:
                self.skipped.append(tomogram)
            else:
                reach = config.match.separation * kind.marker_a / tomo.pixel_size
                self.session.candidates.replace(tomogram, name, hits[name], reach=reach)
            self.done += 1
            self._notify()

    # _notify: tell listeners
    def _notify(self) -> None:
        for listener in self.listeners:
            listener()
