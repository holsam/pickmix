'''
pickmix: per-pick estimates
'''

# Import external dependencies
import csv, hashlib, json, os, threading
from collections.abc import Callable
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from pydantic import field_validator
from typing import Literal

# Import internal pickmix objects
from pickmix.config import Kind
from pickmix.estimate.registry import ESTIMATORS, Fit
from pickmix.loader import Loader
from pickmix.model import Pick, PickStore, Session
from pickmix.project import Project
from pickmix.validation import ValidationStore

# _PICKING: kind settings about how a pick is made, which do not change how it is estimated
_PICKING: set[str] = {'pick_mode', 'bounds_padding'}

# effective_box_a: the box edge in Angstrom for a pick: its own if it has one, else the fit's, else the kind's, else the marker's
def effective_box_a(pick: Pick, kind: Kind, fit: Fit | None) -> float:
    if pick.box_a is not None:
        return pick.box_a
    if fit is not None and fit.box_a > 0:
        return fit.box_a
    return kind.box_a if kind.box_a > 0 else kind.marker_a

# _Row: one estimates.csv row, the fit plus the pick it was computed for and a digest of the settings used
class _Row(Fit):
    tomogram: str
    kind: str
    pick_x: float
    pick_y: float
    pick_z: float
    digest: str

    # _blank: an empty csv cell is no direction
    @field_validator('psi_deg', mode='before')
    @classmethod
    def _blank(cls, value: object) -> object:
        return None if value == '' else value

# _Key: tomogram, kind and rounded coordinates of a pick; picks have no stable id across sessions
type _Key = tuple[str, str, float, float, float]

# EstimateStore: fits for picks, valid while the pick and the settings that produced them are unchanged
class EstimateStore:
    # __init__: load estimates.csv if there is one
    def __init__(self, project: Project, picks: PickStore) -> None:
        self.project = project
        self.picks = picks
        self.path = project.config.out_dir / 'estimates.csv'
        # called from whichever thread stored a result
        self.listeners: list[Callable[[], None]] = []
        self._lock = threading.Lock()
        self._rows: dict[_Key, _Row] = {}
        self._digests: tuple[object, dict[str, str]] = (None, {})
        if self.path.exists():
            with open(self.path, newline='') as handle:
                for row in map(_Row.model_validate, csv.DictReader(handle)):
                    self._rows[_key(row.tomogram, row.kind, row.pick_x, row.pick_y, row.pick_z)] = row

    # digest: fingerprint of everything that changes a kind's estimates, None for a kind not in the config
    def digest(self, kind: str) -> str | None:
        config = self.project.config
        if self._digests[0] is not config:
            self._digests = (config, {})
        cache = self._digests[1]
        if kind not in cache and kind in config.kinds:
            parts = {'kind': config.kinds[kind].model_dump(exclude=_PICKING), 'ring': config.ring.model_dump(), 'source': config.source}
            if config.kinds[kind].estimator == 'filament':
                parts['filament'] = config.filament.model_dump()
            blob = json.dumps(parts, sort_keys=True)
            cache[kind] = hashlib.sha1(blob.encode()).hexdigest()[:12]
        return cache.get(kind)

    # state: ok when a fit matches the pick and settings, stale when only the settings changed, else missing
    def state(self, pick: Pick) -> Literal['ok', 'stale', 'missing']:
        row = self._rows.get(_key(pick.tomogram, pick.kind, pick.x, pick.y, pick.z))
        if row is None or self.digest(pick.kind) is None:
            return 'missing'
        return 'ok' if row.digest == self.digest(pick.kind) else 'stale'

    # get: the fit for a pick if it is current, with pick's own box edge in place of estimator's when it has one
    def get(self, pick: Pick) -> Fit | None:
        fit = self._rows.get(_key(pick.tomogram, pick.kind, pick.x, pick.y, pick.z)) if self.state(pick) == 'ok' else None
        return fit if fit is None or pick.box_a is None else fit.model_copy(update={'box_a': pick.box_a})

    # put: store a fit for the pick as it was when asked, save, and tell listeners
    def put(self, pick: Pick, fit: Fit, digest: str) -> None:
        row = _Row(**fit.model_dump(), tomogram=pick.tomogram, kind=pick.kind, pick_x=pick.x, pick_y=pick.y, pick_z=pick.z, digest=digest)
        with self._lock:
            self._rows[_key(pick.tomogram, pick.kind, pick.x, pick.y, pick.z)] = row
            self._save()
        for listener in self.listeners:
            listener()

    # rename_kind: keep the fits of a renamed kind; written with the next estimate, and rows that never match a pick are dropped then
    def rename_kind(self, old: str, new: str) -> None:
        with self._lock:
            self._rows = {(_key(r.tomogram, new, r.pick_x, r.pick_y, r.pick_z) if r.kind == old else k): r.model_copy(update={'kind': new}) if r.kind == old else r for k, r in self._rows.items()}

    # _save: write the CSV atomically, keeping only rows that belong to a pick now
    def _save(self) -> None:
        live = {_key(p.tomogram, p.kind, p.x, p.y, p.z) for p in self.picks.all()}
        self._rows = {k: r for k, r in self._rows.items() if k in live}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.csv.tmp')
        with open(tmp, 'w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(_Row.model_fields))
            writer.writeheader()
            writer.writerows(r.model_dump() for r in self._rows.values())
        os.replace(tmp, self.path)

# EstimateService: keeps estimates current for the picks of the tomogram being shown, one at a time on its own thread
class EstimateService:
    # __init__: follow edits and navigation
    def __init__(self, session: Session, loader: Loader) -> None:
        self.session, self.loader = session, loader
        self.store = EstimateStore(session.project, session.store)
        self.validation = ValidationStore(session.project, session.store, self.store.digest)
        self.last_error = ''
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='pickmix-estimate')
        self._lock = threading.Lock()
        self._pending: dict[int, tuple[_Key, Future[None]]] = {}
        self._closed = False
        session.store.listeners.append(self.request_current)
        session.goto_listeners.append(self.request_current)
        self.request_current()

    # pending: number of estimates queued or running
    @property
    def pending(self) -> int:
        with self._lock:
            return sum(not f.done() for _, f in self._pending.values())

    # request: queue an estimate for a pick unless it is current or already queued for the same position
    def request(self, pick: Pick) -> None:
        if self._closed or pick.kind not in self.session.project.config.kinds or self.store.state(pick) == 'ok':
            return
        key = _key(pick.tomogram, pick.kind, pick.x, pick.y, pick.z)
        with self._lock:
            old = self._pending.get(pick.id)
            if old is not None and old[0] == key and not old[1].done():
                return
            if old is not None:
                old[1].cancel()
            # a copy, because the pick may be moved while the estimate runs
            snapshot = Pick(pick.id, pick.tomogram, pick.kind, pick.x, pick.y, pick.z)
            self._pending[pick.id] = (key, self._pool.submit(self._run, snapshot))

    # request_current: queue estimates for the picks of the tomogram being shown
    def request_current(self) -> None:
        for pick in self.session.store.picks(self.session.current):
            self.request(pick)

    # request_all: queue estimates for every pick that needs one, the current tomogram first
    def request_all(self) -> None:
        picks = sorted(self.session.store.all(), key=lambda p: p.tomogram != self.session.current)
        for pick in picks:
            self.request(pick)

    # shutdown: stop the thread
    def shutdown(self) -> None:
        self._closed = True
        self._pool.shutdown(wait=False, cancel_futures=True)

    # _run: estimate one pick; a failure is stored as a flagged fit so it shows and is not retried until something changes
    def _run(self, pick: Pick) -> None:
        config = self.session.project.config
        kind = config.kinds[pick.kind]
        digest = self.store.digest(pick.kind)
        try:
            vol = self.loader.open(pick.tomogram).result().vol
            pixel_size = self.session.project.tomos[pick.tomogram].pixel_size
            fit = ESTIMATORS[kind.estimator](vol, (pick.x, pick.y, pick.z), kind, pixel_size, config)
        except CancelledError:
            return
        except Exception as e:
            self.last_error = f'{pick.tomogram} {pick.kind}: {type(e).__name__}: {e}'
            fit = Fit(
                x=pick.x, y=pick.y, z=pick.z, radius_a=kind.marker_a / 2, box_a=kind.box_a, snr=0.0,
                z_lo=round(pick.z), z_hi=round(pick.z), flag='error',
            )
        if digest is not None and not self._closed:
            self.store.put(pick, fit, digest)

# _key: dictionary key for a pick's position
def _key(tomogram: str, kind: str, x: float, y: float, z: float) -> _Key:
    return tomogram, kind, round(x, 3), round(y, 3), round(z, 3)
