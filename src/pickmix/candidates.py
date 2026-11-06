'''
pickmix: candidate picks found by template matching, saved to out_dir/candidates.csv
'''

# Import external dependencies
import csv, itertools, os, threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from pydantic import BaseModel
from typing import Literal

# Import internal pickmix objects
from pickmix.project import Project

# Hit: candidate centre in reconstruction voxels and its score
@dataclass(frozen=True)
class Hit:
    x: float
    y: float
    z: float
    score: float

# Candidate: region matching a template
@dataclass
class Candidate:
    id: int
    tomogram: str
    kind: str
    x: float
    y: float
    z: float
    score: float
    status: Literal['new', 'rejected'] = 'new'

# _Row: one candidates.csv row
class _Row(BaseModel):
    tomogram: str
    kind: str
    x: float
    y: float
    z: float
    score: float
    status: Literal['new', 'rejected'] = 'new'

# CandidateStore: every candidate, saved after each change
class CandidateStore:
    # __init__: load candidates.csv if there is one
    def __init__(self, project: Project) -> None:
        self.project = project
        self.path: Path = project.config.out_dir / 'candidates.csv'
        # called from whichever thread changed the store
        self.listeners: list[Callable[[], None]] = []
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._items: dict[int, Candidate] = {}
        if self.path.exists():
            with open(self.path, newline='') as handle:
                for row in map(_Row.model_validate, csv.DictReader(handle)):
                    candidate = Candidate(next(self._ids), **row.model_dump())
                    self._items[candidate.id] = candidate

    # get: the candidate with this id
    def get(self, candidate_id: int) -> Candidate:
        with self._lock:
            return self._items[candidate_id]

    # candidates: the new candidates in a tomogram, optionally of one kind and at or above a score, best first
    def candidates(self, tomogram: str, kind: str | None = None, *, min_score: float = 0.0) -> list[Candidate]:
        with self._lock:
            found = [c for c in self._items.values() if c.status == 'new' and c.tomogram == tomogram and (kind is None or c.kind == kind) and c.score >= min_score]
        return sorted(found, key=lambda c: -c.score)

    # count: number of new candidates of a kind across all tomograms, or in one tomogram
    def count(self, kind: str, tomogram: str | None = None, *, min_score: float = 0.0) -> int:
        with self._lock:
            return sum(c.status == 'new' and c.kind == kind and (tomogram is None or c.tomogram == tomogram) and c.score >= min_score for c in self._items.values())

    # replace: the new candidates of a kind in a tomogram become these hits, except any within reach voxels of a rejected one
    def replace(self, tomogram: str, kind: str, hits: Iterable[Hit], *, reach: float) -> None:
        with self._lock:
            rejected = [c for c in self._items.values() if c.status == 'rejected' and c.tomogram == tomogram and c.kind == kind]
            for stale in [c.id for c in self._items.values() if c.status == 'new' and c.tomogram == tomogram and c.kind == kind]:
                del self._items[stale]
            for h in hits:
                if all((h.x - r.x) ** 2 + (h.y - r.y) ** 2 + (h.z - r.z) ** 2 > reach**2 for r in rejected):
                    candidate = Candidate(next(self._ids), tomogram, kind, h.x, h.y, h.z, h.score)
                    self._items[candidate.id] = candidate
        self._changed()

    # reject: mark candidates as not wanted
    def reject(self, *candidate_ids: int) -> None:
        with self._lock:
            for candidate_id in candidate_ids:
                self._items[candidate_id].status = 'rejected'
        self._changed()

    # remove: forget candidates, as when they become picks
    def remove(self, *candidate_ids: int) -> None:
        with self._lock:
            for candidate_id in candidate_ids:
                del self._items[candidate_id]
        self._changed()

    # clear: forget the candidates of a kind, or all, rejected ones included
    def clear(self, kind: str | None = None) -> None:
        with self._lock:
            self._items = {i: c for i, c in self._items.items() if kind is not None and c.kind != kind}
        self._changed()

    # prune: forget every candidate for a tomogram
    def prune(self, tomograms: Iterable[str]) -> None:
        gone = set(tomograms)
        with self._lock:
            kept = {i: c for i, c in self._items.items() if c.tomogram not in gone}
            changed = len(kept) != len(self._items)
            self._items = kept
        if changed:
            self._changed()

    # rename_kind: move every candidate of a kind to a new name
    def rename_kind(self, old: str, new: str) -> None:
        with self._lock:
            for candidate in self._items.values():
                if candidate.kind == old:
                    candidate.kind = new
        self._changed()

    # remove_kind: forget every candidate of a kind
    def remove_kind(self, kind: str) -> None:
        self.clear(kind)

    # save: write CSV atomically
    def save(self) -> None:
        with self._lock:
            rows = [_Row(**{k: v for k, v in vars(c).items() if k != 'id'}).model_dump() for c in self._items.values()]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.csv.tmp')
        with open(tmp, 'w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(_Row.model_fields))
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp, self.path)

    # _changed: save, then tell listeners
    def _changed(self) -> None:
        self.save()
        for listener in self.listeners:
            listener()
