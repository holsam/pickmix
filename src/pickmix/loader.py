'''
pickmix: asynchronous tomogram and slice loading with an LRU slice cache and prefetch
'''

# Import external dependencies
import json, threading, numpy as np
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

# Import internal pickmix objects
from pickmix.utils.io import Tomogram, load_volume, volume_path
from pickmix.project import Project
from pickmix.timing import timed

# _CONTRAST_HALF: slices either side of the middle used for contrast limits
_CONTRAST_HALF: int = 2

# _WARM_CHUNK: bytes read per step when warming the page cache
_WARM_CHUNK: int = 8 * 1024 * 1024

# Opened: a tomogram ready to show; vol is the read-only (z, y, x) memory map
@dataclass(frozen=True)
class Opened:
    name: str
    vol: np.ndarray
    limits: tuple[float, float]

# Loader: opens tomograms and serves slices
class Loader:
    # __init__: nothing is read until asked
    def __init__(self, project: Project, *, cache_slices: int = 96, keep_open: int = 3) -> None:
        self.project = project
        self.cache_slices = cache_slices
        self.keep_open = keep_open
        self._pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix='pickmix-load')
        self._lock = threading.Lock()
        self._opened: OrderedDict[str, Future[Opened]] = OrderedDict()
        self._slices: OrderedDict[tuple[str, int], np.ndarray] = OrderedDict()
        self._warm_generation = 0
        self._closed = False
        self._contrast_path = project.config.out_dir / 'contrast.json'

    # open: future of the tomogram, started once and kept for the last few
    def open(self, name: str) -> Future[Opened]:
        with self._lock:
            future = self._opened.get(name)
            if future is None:
                future = self._opened[name] = self._submit(self._open, name)
            self._opened.move_to_end(name)
            while len(self._opened) > self.keep_open:
                self._opened.popitem(last=False)
            return future

    # cached: the slice if it is already in memory
    def cached(self, name: str, z: int) -> np.ndarray | None:
        with self._lock:
            hit = self._slices.get((name, z))
            if hit is not None:
                self._slices.move_to_end((name, z))
            return hit

    # slice: the slice, reading it now if it is not cached; blocks, so call from a worker or when it is cheap
    def slice(self, name: str, z: int) -> np.ndarray:
        hit = self.cached(name, z)
        if hit is not None:
            return hit
        opened = self.open(name).result()
        with timed(f'slice {name} z={z}'):
            data = np.array(opened.vol[z])
        with self._lock:
            self._slices[(name, z)] = data
            while len(self._slices) > self.cache_slices:
                self._slices.popitem(last=False)
        return data

    # fetch: future of a slice, for the GUI to wait on without blocking
    def fetch(self, name: str, z: int) -> Future[np.ndarray]:
        return self._submit(self.slice, name, z)

    # prefetch: open a tomogram, read its middle slices and warm the page cache for the rest of the file
    def prefetch(self, name: str) -> None:
        self._warm_generation += 1
        generation = self._warm_generation
        self._submit(self._prefetch, name, generation)

    # warm_around: read slices near z so scrolling is served from memory
    def warm_around(self, name: str, z: int, radius: int = 8) -> None:
        self._submit(self._warm_around, name, z, radius)

    # shutdown: stop the threads
    def shutdown(self) -> None:
        self._closed = True
        self._warm_generation += 1
        self._pool.shutdown(wait=False, cancel_futures=True)

    # _submit: run on the pool, or hand back a cancelled future once shut down so late callers fail quietly
    def _submit[T](self, fn: Callable[..., T], *args: object) -> Future[T]:
        if self._closed:
            future: Future[T] = Future()
            future.cancel()
            return future
        return self._pool.submit(fn, *args)

    # _tomo: the tomogram record for a name
    def _tomo(self, name: str) -> Tomogram:
        return self.project.tomos[name]

    # _open: map the volume and find its contrast limits
    def _open(self, name: str) -> Opened:
        tomo = self._tomo(name)
        with timed(f'open {name}'):
            vol = load_volume(tomo, source=self.project.config.source)
        with timed(f'contrast {name}'):
            limits = self._limits(tomo, vol)
        return Opened(name, vol, limits)

    # _limits: 1st and 99th percentile of a few middle slices, from the cache file when the volume has not changed
    def _limits(self, tomo: Tomogram, vol: np.ndarray) -> tuple[float, float]:
        path = volume_path(tomo, source=self.project.config.source)
        mtime = path.stat().st_mtime
        with self._lock:
            cache = json.loads(self._contrast_path.read_text()) if self._contrast_path.exists() else {}
        entry = cache.get(tomo.name)
        if entry and entry['mtime'] == mtime and entry['path'] == str(path):
            return entry['lo'], entry['hi']
        mid = vol.shape[0] // 2
        sample = np.asarray(vol[max(mid - _CONTRAST_HALF, 0) : mid + _CONTRAST_HALF + 1, ::2, ::2], dtype=np.float32)
        lo, hi = (float(v) for v in np.percentile(sample, (1, 99)))
        with self._lock:
            cache = json.loads(self._contrast_path.read_text()) if self._contrast_path.exists() else {}
            cache[tomo.name] = {'mtime': mtime, 'path': str(path), 'lo': lo, 'hi': hi}
            self._contrast_path.parent.mkdir(parents=True, exist_ok=True)
            self._contrast_path.write_text(json.dumps(cache))
        return lo, hi

    # _prefetch: open, read the middle slices, then warm the file unless a newer prefetch started
    def _prefetch(self, name: str, generation: int) -> None:
        opened = self.open(name).result()
        self.slice(name, opened.vol.shape[0] // 2)
        self._warm_file(volume_path(self._tomo(name), source=self.project.config.source), generation)

    # _warm_around: read z - radius .. z + radius
    def _warm_around(self, name: str, z: int, radius: int) -> None:
        depth = self.open(name).result().vol.shape[0]
        for zi in range(max(z - radius, 0), min(z + radius + 1, depth)):
            self.slice(name, zi)

    # _warm_file: read a file sequentially so its pages are in the operating system cache; stops when a newer prefetch starts
    def _warm_file(self, path: Path, generation: int) -> None:
        with timed(f'warm {path.name}'), open(path, 'rb') as handle:
            while self._warm_generation == generation and handle.read(_WARM_CHUNK):
                pass
