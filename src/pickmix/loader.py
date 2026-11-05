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

# _MIB: bytes in a mebibyte
_MIB: int = 1024 * 1024

# _WARM_CHUNK: bytes read per step when warming the page cache
_WARM_CHUNK: int = 8 * 1024 * 1024

# warm_order: slices to read around z, nearest first; sign is the scrolling direction, so slices ahead of it come before the ones behind
def warm_order(z: int, depth: int, *, sign: int, ahead: int, behind: int) -> list[int]:
    order = []
    for d in range(1, max(ahead, behind) + 1):
        for step, reach in ((sign * d, ahead), (-sign * d, behind)):
            if d <= reach and 0 <= z + step < depth:
                order.append(z + step)
    return order

# Opened: a tomogram ready to show; vol is the read-only (z, y, x) memory map
@dataclass(frozen=True)
class Opened:
    name: str
    vol: np.ndarray
    limits: tuple[float, float]

# Loader: opens tomograms and serves slices
class Loader:
    # __init__: nothing is read until asked
    def __init__(self, project: Project, *, cache_bytes: int | None = None, keep_open: int = 3) -> None:
        self.project = project
        self.cache_bytes = project.config.cache_mb * _MIB if cache_bytes is None else cache_bytes
        self.keep_open = keep_open
        self._fg = ThreadPoolExecutor(max_workers=2, thread_name_prefix='pickmix-slice')
        self._bg = ThreadPoolExecutor(max_workers=2, thread_name_prefix='pickmix-warm')
        self._opener = ThreadPoolExecutor(max_workers=2, thread_name_prefix='pickmix-open')
        self._lock = threading.Lock()
        self._inflight: dict[tuple[str, int], Future[np.ndarray]] = {}
        self._opened: OrderedDict[str, Future[Opened]] = OrderedDict()
        self._slices: OrderedDict[tuple[str, int], np.ndarray] = OrderedDict()
        self._bytes = 0
        self._warm_generation = 0
        self._near_generation = 0
        self._fetching: Future[np.ndarray] | None = None
        self._closed = False
        self._contrast_path = project.config.out_dir / 'contrast.json'

    # open: future of the tomogram, started once and kept for the last few
    def open(self, name: str) -> Future[Opened]:
        with self._lock:
            future = self._opened.get(name)
            if future is None:
                future = self._opened[name] = self._submit(self._opener, self._open, name)
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
        key = (name, z)
        hit = self.cached(name, z)
        if hit is not None:
            return hit
        with self._lock:
            pending = self._inflight.get(key)
            leader = pending is None
            if pending is None:
                pending = self._inflight[key] = Future()
        if not leader:
            return pending.result()
        try:
            opened = self.open(name).result()
            with timed(f'slice {name} z={z}'):
                data = np.array(opened.vol[z])
        except BaseException as e:
            with self._lock:
                del self._inflight[key]
            pending.set_exception(e)
            raise
        with self._lock:
            self._store(key, data)
            del self._inflight[key]
        pending.set_result(data)
        return data

    # fetch: future of a slice, for the GUI to wait on without blocking; the previous fetch is cancelled if it has not started, since the GUI has moved on
    def fetch(self, name: str, z: int) -> Future[np.ndarray]:
        with self._lock:
            if self._fetching is not None:
                self._fetching.cancel()
            future = self._fetching = self._submit(self._fg, self.slice, name, z)
        return future

    # prefetch: open a tomogram, read its middle slices and warm the page cache for the rest of the file
    def prefetch(self, name: str) -> None:
        self._warm_generation += 1
        generation = self._warm_generation
        self._submit(self._bg, self._prefetch, name, generation)

    # warm_around: read slices near z so scrolling is served from memory, more of them ahead of the scrolling direction (sign) than behind; a newer call stops an older one
    def warm_around(self, name: str, z: int, *, sign: int = 1, ahead: int = 16, behind: int = 4) -> None:
        self._near_generation += 1
        self._submit(self._bg, self._warm_around, name, z, self._near_generation, sign, ahead, behind)

    # shutdown: stop the threads
    def shutdown(self) -> None:
        self._closed = True
        self._warm_generation += 1
        self._near_generation += 1
        for pool in (self._fg, self._bg, self._opener):
            pool.shutdown(wait=False, cancel_futures=True)

    # _submit: run on a pool, or hand back a cancelled future once shut down so late callers fail quietly
    def _submit[T](self, pool: ThreadPoolExecutor, fn: Callable[..., T], *args: object) -> Future[T]:
        if self._closed:
            future: Future[T] = Future()
            future.cancel()
            return future
        return pool.submit(fn, *args)

    # _store: add a slice to the cache and drop the least recently used until it fits the budget, but never the slice just added; call with the lock held
    def _store(self, key: tuple[str, int], data: np.ndarray) -> None:
        old = self._slices.pop(key, None)
        if old is not None:
            self._bytes -= old.nbytes
        self._slices[key] = data
        self._bytes += data.nbytes
        while self._bytes > self.cache_bytes and len(self._slices) > 1:
            _, dropped = self._slices.popitem(last=False)
            self._bytes -= dropped.nbytes

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

    # _warm_around: read the slices warm_order gives, until a newer warm_around starts
    def _warm_around(self, name: str, z: int, generation: int, sign: int, ahead: int, behind: int) -> None:
        depth = self.open(name).result().vol.shape[0]
        for zi in warm_order(z, depth, sign=sign, ahead=ahead, behind=behind):
            if self._near_generation != generation:
                return
            self.slice(name, zi)

    # _warm_file: read a file sequentially so its pages are in the operating system cache; stops when a newer prefetch starts
    def _warm_file(self, path: Path, generation: int) -> None:
        with timed(f'warm {path.name}'), open(path, 'rb') as handle:
            while self._warm_generation == generation and handle.read(_WARM_CHUNK):
                pass
