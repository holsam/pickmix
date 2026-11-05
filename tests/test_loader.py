'''
pickmix: tests for tomogram slice loading
'''

# Import external dependencies
import json, numpy as np, pytest, time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

# Import internal pickmix objects
from pickmix.loader import Loader, Opened, warm_order
from pickmix.project import open_project

# NAME: the single tomogram of the fixture project
NAME: str = 'Position_1_2'

# _loader: a loader over a fresh project; the fixture volume counts up, shape (4, 6, 8)
def _loader(make_config: Callable[..., Path], **kwargs: int) -> Loader:
    return Loader(open_project(make_config()), **kwargs)

class TestLoader:
    # test_slice_values: a slice is the right plane of the volume
    def test_slice_values(self, make_config: Callable[..., Path]) -> None:
        loader = _loader(make_config)
        expected = np.arange(4 * 6 * 8, dtype=np.float32).reshape(4, 6, 8)
        assert np.array_equal(loader.slice(NAME, 2), expected[2])
        loader.shutdown()

    # test_cached: a read slice is served from memory
    def test_cached(self, make_config: Callable[..., Path]) -> None:
        loader = _loader(make_config)
        assert loader.cached(NAME, 1) is None
        loader.slice(NAME, 1)
        assert loader.cached(NAME, 1) is not None
        loader.shutdown()

    # test_lru_eviction: the oldest slice goes first and a touched one stays; a slice here is 6 x 8 float32, 192 bytes
    def test_lru_eviction(self, make_config: Callable[..., Path]) -> None:
        loader = _loader(make_config, cache_bytes=2 * 192)
        loader.slice(NAME, 0)
        loader.slice(NAME, 1)
        loader.cached(NAME, 0)
        loader.slice(NAME, 2)
        assert loader.cached(NAME, 0) is not None and loader.cached(NAME, 1) is None
        loader.shutdown()

    # test_contrast_limits_cached: limits come from the middle slices and are written to out/contrast.json
    def test_contrast_limits_cached(self, make_config: Callable[..., Path]) -> None:
        loader = _loader(make_config)
        opened = loader.open(NAME).result()
        vol = np.arange(4 * 6 * 8, dtype=np.float32).reshape(4, 6, 8)[:, ::2, ::2]
        lo, hi = np.percentile(vol, (1, 99))
        assert opened.limits == (float(lo), float(hi))
        cache = json.loads((loader.project.config.out_dir / 'contrast.json').read_text())
        assert cache[NAME]['lo'] == float(lo)
        loader.shutdown()

    # test_contrast_cache_used: a cached entry with the same mtime is returned without recomputing
    def test_contrast_cache_used(self, make_config: Callable[..., Path]) -> None:
        loader = _loader(make_config)
        loader.open(NAME).result()
        path = loader.project.config.out_dir / 'contrast.json'
        cache = json.loads(path.read_text())
        cache[NAME]['lo'], cache[NAME]['hi'] = -1.0, 1.0
        path.write_text(json.dumps(cache))
        again = Loader(loader.project)
        assert again.open(NAME).result().limits == (-1.0, 1.0)
        loader.shutdown()
        again.shutdown()

    # test_prefetch: prefetching opens the tomogram and caches its middle slice
    def test_prefetch(self, make_config: Callable[..., Path]) -> None:
        loader = _loader(make_config)
        loader.prefetch(NAME)
        loader.open(NAME).result()
        for _ in range(200):
            if loader.cached(NAME, 2) is not None:
                break
            loader._bg.submit(lambda: None).result()
        assert loader.cached(NAME, 2) is not None
        loader.shutdown()

    # test_fetch: the future resolves to the slice
    def test_fetch(self, make_config: Callable[..., Path]) -> None:
        loader = _loader(make_config)
        assert loader.fetch(NAME, 3).result().shape == (6, 8)
        loader.shutdown()

    # test_slice_read_once: concurrent requests for one slice share a single read
    def test_slice_read_once(self, make_config: Callable[..., Path]) -> None:
        loader = _loader(make_config)
        opened = loader.open(NAME).result()
        reads = []
        # _Counting: a volume that records which planes are read
        class _Counting:
            shape = opened.vol.shape
            # __getitem__: record the plane, slowly enough for the other threads to arrive
            def __getitem__(self, z: int) -> np.ndarray:
                reads.append(z)
                time.sleep(0.05)
                return opened.vol[z]
        loader._opened[NAME] = Future()
        loader._opened[NAME].set_result(Opened(NAME, _Counting(), opened.limits))  # type: ignore[arg-type]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: loader.slice(NAME, 1), range(4)))
        assert reads == [1] and all(np.array_equal(r, results[0]) for r in results)
        loader.shutdown()

    # test_slice_error_not_cached: a failed read raises for every waiter and is tried again next time
    def test_slice_error_not_cached(self, make_config: Callable[..., Path]) -> None:
        loader = _loader(make_config)
        with pytest.raises(IndexError):
            loader.slice(NAME, 99)
        assert loader._inflight == {} and loader.slice(NAME, 1).shape == (6, 8)
        loader.shutdown()

    # test_warm_order: nearest first, and the side the user is scrolling towards gets more
    def test_warm_order(self) -> None:
        assert warm_order(5, 20, sign=1, ahead=3, behind=1) == [6, 4, 7, 8]
        assert warm_order(5, 20, sign=-1, ahead=3, behind=1) == [4, 6, 3, 2]
        assert warm_order(1, 4, sign=1, ahead=5, behind=5) == [2, 0, 3]

    # test_fetch_cancels_queued: a fetch that has not started is cancelled by the next one
    def test_fetch_cancels_queued(self, make_config: Callable[..., Path]) -> None:
        loader = _loader(make_config)
        gate = Future()
        # two workers held busy, so the next fetches queue
        blockers = [loader._fg.submit(gate.result) for _ in range(2)]
        first = loader.fetch(NAME, 0)
        second = loader.fetch(NAME, 1)
        assert first.cancelled()
        gate.set_result(None)
        assert second.result().shape == (6, 8)
        loader.shutdown()
        assert all(b.done() for b in blockers)

    # test_warm_stops_when_superseded: a newer warm_around stops an older one
    def test_warm_stops_when_superseded(self, make_config: Callable[..., Path]) -> None:
        loader = _loader(make_config)
        loader.open(NAME).result()
        loader._near_generation += 1
        loader._warm_around(NAME, 0, loader._near_generation - 1, 1, 3, 3)
        assert all(loader.cached(NAME, z) is None for z in range(4))
        loader._warm_around(NAME, 0, loader._near_generation, 1, 3, 3)
        assert [loader.cached(NAME, z) is not None for z in range(4)] == [False, True, True, True]
        loader.shutdown()

    # test_cache_budget: the cache holds the budget in bytes and tracks it as slices come and go
    def test_cache_budget(self, make_config: Callable[..., Path]) -> None:
        loader = _loader(make_config, cache_bytes=3 * 192)
        for z in range(4):
            loader.slice(NAME, z)
        assert loader._bytes == 3 * 192 and loader.cached(NAME, 0) is None and loader.cached(NAME, 3) is not None
        loader.shutdown()

    # test_cache_budget_keeps_newest: a budget smaller than one slice still keeps the slice just read
    def test_cache_budget_keeps_newest(self, make_config: Callable[..., Path]) -> None:
        loader = _loader(make_config, cache_bytes=1)
        loader.slice(NAME, 0)
        loader.slice(NAME, 1)
        assert loader.cached(NAME, 0) is None and loader.cached(NAME, 1) is not None and loader._bytes == 192
        loader.shutdown()

    # test_default_budget: the budget comes from cache_mb in the config
    def test_default_budget(self, make_config: Callable[..., Path]) -> None:
        loader = _loader(make_config)
        assert loader.cache_bytes == 2048 * 1024 * 1024
        loader.shutdown()
