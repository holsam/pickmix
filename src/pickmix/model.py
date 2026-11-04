'''
pickmix: pick store, tomogram navigation and progress schema
'''

# Import external dependencies
import csv, itertools, os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from pydantic import BaseModel

# Import internal pickmix objects
from pickmix.project import Project

# Pick: one hand-picked centre; x, y, z in reconstruction voxels; id lives for the session only
@dataclass
class Pick:
    id: int
    tomogram: str
    kind: str
    x: float
    y: float
    z: float

# _Row: one picks.csv row; a missing kind column is a CaVe file, whose picks were all cages
class _Row(BaseModel):
    tomogram: str
    kind: str = 'cage'
    x: float
    y: float
    z: float
    pixel_size_a: float

# Progress: where picking stopped and which tomograms have been opened, saved beside picks.csv
class Progress(BaseModel):
    last: str | None = None
    visited: list[str] = []

# Row: one line of the tomogram list
@dataclass(frozen=True)
class Row:
    index: int
    name: str
    count: int
    current: bool
    visited: bool

# PickStore: every pick of the project, saved to out_dir/picks.csv after each edit
class PickStore:
    # __init__: load picks.csv if there is one
    def __init__(self, project: Project) -> None:
        self.project = project
        self.path = project.config.out_dir / 'picks.csv'
        self.listeners: list[Callable[[], None]] = []
        self._ids = itertools.count(1)
        self._picks: dict[int, Pick] = {}
        if self.path.exists():
            with open(self.path, newline='') as handle:
                for row in map(_Row.model_validate, csv.DictReader(handle)):
                    pick = Pick(next(self._ids), row.tomogram, row.kind, row.x, row.y, row.z)
                    self._picks[pick.id] = pick

    # get: the pick with this id
    def get(self, pick_id: int) -> Pick:
        return self._picks[pick_id]

    # picks: picks in a tomogram, optionally of one kind, in the order added
    def picks(self, tomogram: str, kind: str | None = None) -> list[Pick]:
        return [p for p in list(self._picks.values()) if p.tomogram == tomogram and (kind is None or p.kind == kind)]

    # all: every pick, optionally of one kind
    def all(self, kind: str | None = None) -> list[Pick]:
        return [p for p in list(self._picks.values()) if kind is None or p.kind == kind]

    # count: number of picks in a tomogram, optionally of one kind
    def count(self, tomogram: str, kind: str | None = None) -> int:
        return len(self.picks(tomogram, kind))

    # total: number of picks of a kind across all tomograms
    def total(self, kind: str | None = None) -> int:
        return len(self.all(kind))

    # add: new pick; saves and notifies
    def add(self, tomogram: str, kind: str, x: float, y: float, z: float) -> Pick:
        pick = Pick(next(self._ids), tomogram, kind, x, y, z)
        self._picks[pick.id] = pick
        self._changed()
        return pick

    # move: new position for a pick; saves and notifies
    def move(self, pick_id: int, x: float, y: float, z: float | None = None) -> None:
        pick = self._picks[pick_id]
        pick.x, pick.y = x, y
        if z is not None:
            pick.z = z
        self._changed()

    # remove: delete picks; saves and notifies once
    def remove(self, *pick_ids: int) -> None:
        for pick_id in pick_ids:
            del self._picks[pick_id]
        self._changed()

    # rename_kind: move every pick of a kind to a new name; saves and notifies once, returns how many moved
    def rename_kind(self, old: str, new: str) -> int:
        moved = self.all(old)
        for pick in moved:
            pick.kind = new
        if moved:
            self._changed()
        return len(moved)

    # remove_kind: delete every pick of a kind; saves and notifies once, returns how many went
    def remove_kind(self, kind: str) -> int:
        ids = [p.id for p in self.all(kind)]
        if ids:
            self.remove(*ids)
        return len(ids)

    # save: write the CSV atomically
    def save(self) -> None:
        pixel = {name: t.pixel_size for name, t in self.project.tomos.items()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.csv.tmp')
        with open(tmp, 'w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(_Row.model_fields))
            writer.writeheader()
            for p in list(self._picks.values()):
                # unusable tomograms keep their picks; pixel size is only informative
                writer.writerow(_Row(tomogram=p.tomogram, kind=p.kind, x=p.x, y=p.y, z=p.z, pixel_size_a=pixel.get(p.tomogram, 0.0)).model_dump())
        os.replace(tmp, self.path)

    # _changed: save, then tell listeners
    def _changed(self) -> None:
        self.save()
        for listener in self.listeners:
            listener()

# Session: the store plus which tomogram is shown; navigation clamps and never wraps
class Session:
    # __init__: resume at the tomogram shown last time if it is still usable
    def __init__(self, project: Project) -> None:
        self.project = project
        self.store = PickStore(project)
        self.names = list(project.tomos)
        self.progress_path = project.config.out_dir / 'progress.json'
        self.goto_listeners: list[Callable[[], None]] = []
        saved = Progress.model_validate_json(self.progress_path.read_text()) if self.progress_path.exists() else Progress()
        self.visited = {n for n in saved.visited if n in project.tomos}
        self.index = self.names.index(saved.last) if saved.last in self.names else 0
        if self.names:
            self._remember()

    # current: name of the tomogram shown
    @property
    def current(self) -> str:
        return self.names[self.index]

    # go: show tomogram i, clamped; saves progress and notifies
    def go(self, i: int) -> None:
        self.index = min(max(i, 0), len(self.names) - 1)
        self._remember()
        for listener in self.goto_listeners:
            listener()

    # step: move by delta tomograms
    def step(self, delta: int) -> None:
        self.go(self.index + delta)

    # find: index of a tomogram by 1-based number or by name (exact match first, else the first containing the text), None if nothing matches
    def find(self, query: str) -> int | None:
        query = query.strip().lower()
        lowered = [n.lower() for n in self.names]
        if query.isdigit():
            return int(query) - 1 if 0 < int(query) <= len(lowered) else None
        if not query:
            return None
        return lowered.index(query) if query in lowered else next((i for i, n in enumerate(lowered) if query in n), None)

    # jump: go to the tomogram find returns; False if nothing matches
    def jump(self, query: str) -> bool:
        hit = self.find(query)
        if hit is None:
            return False
        self.go(hit)
        return True

    # rows: the tomogram list with counts, the current one and the opened ones flagged
    def rows(self) -> list[Row]:
        return [Row(i, n, self.store.count(n), i == self.index, n in self.visited) for i, n in enumerate(self.names)]

    # _remember: mark the current tomogram visited and save progress
    def _remember(self) -> None:
        self.visited.add(self.current)
        self.progress_path.parent.mkdir(parents=True, exist_ok=True)
        self.progress_path.write_text(Progress(last=self.current, visited=sorted(self.visited)).model_dump_json())
