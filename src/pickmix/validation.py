'''
pickmix: kind validation, scores of each pick against the average of its kind, saved to out_dir/validation.csv
'''

# Import external dependencies
import csv, hashlib, json, numpy as np, os, threading
from collections.abc import Callable
from pydantic import BaseModel, field_validator
from typing import Literal

# Import internal pickmix objects
from pickmix.config import ValidationParams
from pickmix.model import Pick, PickStore
from pickmix.project import Project

# _MAD_TO_SIGMA: factor that turns a median absolute deviation into the standard deviation of a normal distribution with the same spread
_MAD_TO_SIGMA: float = 1.4826

# score_images: for every normalised image (n, h, w), the best normalised cross-correlation with the average of the others, over shifts up to shift_fraction of the box. The average leaves out the trim_fraction of lowest scoring images, found on a first pass, so bad picks do not pull it towards themselves
def score_images(images: np.ndarray, params: ValidationParams) -> np.ndarray:
    n = len(images)
    if n < params.min_picks:
        raise ValueError(f'needs at least {params.min_picks} picks to validate, has {n}')
    shift = round(params.shift_fraction * images.shape[1])
    first = _leave_one_out(images, np.ones(n, dtype=bool), shift)
    keep = first >= np.quantile(first, params.trim_fraction)
    return _leave_one_out(images, keep, shift)

# deviations: how many robust standard deviations each score sits below the median of the scores, with the spread never less than mad_floor; negative above the median
def deviations(scores: np.ndarray, params: ValidationParams) -> np.ndarray:
    median = np.median(scores)
    spread = max(_MAD_TO_SIGMA * float(np.median(np.abs(scores - median))), params.mad_floor)
    return (median - scores) / spread

# low_scores: which scores are far enough below the rest to flag, or under the lowest score if one is set
def low_scores(scores: np.ndarray, params: ValidationParams) -> np.ndarray:
    return (deviations(scores, params) > params.flag_deviations) | (scores < params.min_score)

# _leave_one_out: the best normalised cross-correlation of each image with the mean of the images in keep other than itself, over circular shifts up to shift pixels each way
def _leave_one_out(images: np.ndarray, keep: np.ndarray, shift: int) -> np.ndarray:
    n, h, w = images.shape
    total = images[keep].sum(axis=0)
    others = keep.sum() - keep
    means = (total[None] - images * keep[:, None, None]) / others[:, None, None]
    spread = means.reshape(n, -1).std(axis=1) + 1e-9
    # images have zero mean and unit spread, so the correlation needs only the spread of the average
    corr = np.fft.irfft2(np.conj(np.fft.rfft2(images)) * np.fft.rfft2(means), s=(h, w)) / (h * w * spread[:, None, None])
    ys, xs = np.arange(-shift, shift + 1) % h, np.arange(-shift, shift + 1) % w
    return corr[:, ys][:, :, xs].reshape(n, -1).max(axis=1)

# _Row: row from validation.csv (pick score, whether it was low, what score was against)
class _Row(BaseModel):
    tomogram: str
    kind: str
    pick_x: float
    pick_y: float
    pick_z: float
    score: float
    low: bool
    members: str
    digest: str

    # _blank: an empty csv cell reads as a false flag
    @field_validator('low', mode='before')
    @classmethod
    def _blank(cls, value: object) -> object:
        return False if value == '' else value

# _Key: tomogram, kind and rounded coordinates of a pick
type _Key = tuple[str, str, float, float, float]

# ValidationStore: scores for picks of a kind, valid while settings and all picks are the same as when scored
class ValidationStore:
    # __init__: load validation.csv if there is one; digest_of gives the estimate digest of a kind, which the scores depend on through the fits
    def __init__(self, project: Project, picks: PickStore, digest_of: Callable[[str], str | None]) -> None:
        self.project, self.picks, self._digest_of = project, picks, digest_of
        self.path = project.config.out_dir / 'validation.csv'
        # called from whichever thread stored a result
        self.listeners: list[Callable[[], None]] = []
        self._lock = threading.Lock()
        self._rows: dict[_Key, _Row] = {}
        if self.path.exists():
            with open(self.path, newline='') as handle:
                for row in map(_Row.model_validate, csv.DictReader(handle)):
                    self._rows[_key(row.tomogram, row.kind, row.pick_x, row.pick_y, row.pick_z)] = row

    # digest: fingerprint of what scores of a kind depend on beside picks
    def digest(self, kind: str) -> str | None:
        estimate = self._digest_of(kind)
        if estimate is None:
            return None
        blob = json.dumps({'estimate': estimate, 'validation': self.project.config.validation.model_dump()}, sort_keys=True)
        return hashlib.sha1(blob.encode()).hexdigest()[:12]

    # members: fingerprint of every pick of a kind and where it is, which changes when one is added, removed or moved
    def members(self, kind: str) -> str:
        keys = sorted((p.tomogram, round(p.x, 3), round(p.y, 3), round(p.z, 3)) for p in self.picks.all(kind))
        return hashlib.sha1(json.dumps(keys).encode()).hexdigest()[:12]

    # state: ok when score matches pick, settings and picks of kind
    def state(self, pick: Pick) -> Literal['ok', 'stale', 'missing']:
        row = self._rows.get(_key(pick.tomogram, pick.kind, pick.x, pick.y, pick.z))
        digest = self.digest(pick.kind)
        if row is None or digest is None:
            return 'missing'
        return 'ok' if row.digest == digest and row.members == self.members(pick.kind) else 'stale'

    # score: pick's score if it is current
    def score(self, pick: Pick) -> float | None:
        return self._rows[_key(pick.tomogram, pick.kind, pick.x, pick.y, pick.z)].score if self.state(pick) == 'ok' else None

    # low: whether pick's score is current and low enough to flag
    def low(self, pick: Pick) -> bool:
        return self.state(pick) == 'ok' and self._rows[_key(pick.tomogram, pick.kind, pick.x, pick.y, pick.z)].low

    # put_kind: replace scores of a kind with new ones, (pick, score, low) for each, save, and tell listeners
    def put_kind(self, kind: str, scored: list[tuple[Pick, float, bool]]) -> None:
        digest, members = self.digest(kind), self.members(kind)
        if digest is None:
            raise KeyError(kind)
        with self._lock:
            self._rows = {k: r for k, r in self._rows.items() if r.kind != kind}
            for pick, score, low in scored:
                self._rows[_key(pick.tomogram, kind, pick.x, pick.y, pick.z)] = _Row(tomogram=pick.tomogram, kind=kind, pick_x=pick.x, pick_y=pick.y, pick_z=pick.z, score=score, low=low, members=members, digest=digest)
            self._save()
        for listener in self.listeners:
            listener()

    # rename_kind: keep scores of a renamed kind
    def rename_kind(self, old: str, new: str) -> None:
        with self._lock:
            self._rows = {(_key(r.tomogram, new, r.pick_x, r.pick_y, r.pick_z) if r.kind == old else k): r.model_copy(update={'kind': new}) if r.kind == old else r for k, r in self._rows.items()}

    # _save: atomically write CSV, keeping only rows that belong to a pick now
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

# _key: dictionary key for a pick's position
def _key(tomogram: str, kind: str, x: float, y: float, z: float) -> _Key:
    return tomogram, kind, round(x, 3), round(y, 3), round(z, 3)
