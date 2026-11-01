'''
pickmix: optional per-step timing
'''

# Import external dependencies
import os, sys, time
from collections.abc import Iterator
from contextlib import contextmanager

# enabled: whether timing output is on, read each call so tests can switch it
def enabled() -> bool:
    return os.environ.get('PICKMIX_TIMING') == '1'

# timed: context manager printing how long its body took
@contextmanager
def timed(label: str) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        if enabled():
            print(f'[timing] {label}: {time.perf_counter() - start:.3f} s', file=sys.stderr)

# Timer: laps from one start, printing the time since the previous lap and since the start
class Timer:
    # __init__: start now
    def __init__(self, label: str) -> None:
        self.label = label
        self.start = self.last = time.perf_counter()

    # lap: report a step
    def lap(self, step: str) -> None:
        now = time.perf_counter()
        if enabled():
            print(f'[timing] {self.label}: {step} {now - self.last:.3f} s (total {now - self.start:.3f} s)', file=sys.stderr)
        self.last = now
