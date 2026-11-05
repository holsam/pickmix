'''
pickmix: tests for tomogram slice loading
'''

# Import external dependencies
import json, numpy as np, pytest, time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

# Import internal pickmix objects
from pickmix.loader import Loader, Opened
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

    # test_lru_eviction: the oldest slice goes first and a touched one stays
    def test_lru_eviction(self, make_config: Callable[..., Path]) -> None:
        loader = _loader(make_config, cache_slices=2)
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