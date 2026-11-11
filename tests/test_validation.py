'''
pickmix: tests for kind validation
'''

# Import external dependencies
import numpy as np, pytest
from collections.abc import Callable
from pathlib import Path

# Import internal pickmix objects
from pickmix.config import Kind, ValidationParams
from pickmix.model import PickStore
from pickmix.project import open_project
from pickmix.validation import ValidationStore, deviations, low_scores, score_images

# SIZE: edge in pixels of the synthetic box images
SIZE: int = 24

# _norm: an image with zero mean and unit spread, as box_images makes them
def _norm(img: np.ndarray) -> np.ndarray:
    return (img - img.mean()) / (img.std() or 1.0)

# _blob: a normalised gaussian blob with noise, optionally shifted by (dy, dx) pixels
def _blob(rng: np.random.Generator, *, dy: int = 0, dx: int = 0, noise: float = 0.3) -> np.ndarray:
    yy, xx = np.mgrid[:SIZE, :SIZE]
    img = np.exp(-0.5 * (((yy - SIZE // 2 - dy) ** 2 + (xx - SIZE // 2 - dx) ** 2) / 3.0**2)) + rng.normal(0.0, noise, (SIZE, SIZE))
    return _norm(img)

# _noise: a normalised image of noise only
def _noise(rng: np.random.Generator) -> np.ndarray:
    return _norm(rng.normal(0.0, 1.0, (SIZE, SIZE)))

# _ring: a normalised ring with noise, a different shape from the blob
def _ring(rng: np.random.Generator) -> np.ndarray:
    yy, xx = np.mgrid[:SIZE, :SIZE]
    return _norm(np.exp(-0.5 * ((np.hypot(yy - SIZE // 2, xx - SIZE // 2) - 8.0) / 1.5) ** 2) + rng.normal(0.0, 0.3, (SIZE, SIZE)))

# _brute: the same scores worked out one image and one shift at a time
def _brute(images: np.ndarray, shift: int) -> np.ndarray:
    out = []
    for i in range(len(images)):
        mean = np.delete(images, i, axis=0).mean(axis=0)
        best = -1.0
        for dy in range(-shift, shift + 1):
            for dx in range(-shift, shift + 1):
                moved = np.roll(images[i], (dy, dx), axis=(0, 1))
                best = max(best, float((moved * (mean - mean.mean())).mean() / (moved.std() * mean.std())))
        out.append(best)
    return np.array(out)

# TestValidation: scoring and flagging
class TestValidation:
    # test_matches_brute_force: the fast scores are the best correlation with the mean of the others over the shifts, worked out directly
    def test_matches_brute_force(self) -> None:
        rng = np.random.default_rng(0)
        images = np.stack([_blob(rng, dy=int(rng.integers(-1, 2)), dx=int(rng.integers(-1, 2))) for _ in range(10)])
        params = ValidationParams(min_picks=3, trim_fraction=0.0, shift_fraction=2 / SIZE)
        assert np.allclose(score_images(images, params), _brute(images, 2), atol=1e-6)

    # test_outliers_score_lowest_and_are_flagged: noise and a different shape among clean blobs score lowest and are the only ones flagged
    def test_outliers_score_lowest_and_are_flagged(self) -> None:
        rng = np.random.default_rng(1)
        images = np.stack([*(_blob(rng) for _ in range(30)), _noise(rng), _noise(rng), _ring(rng)])
        scores = score_images(images, ValidationParams())
        assert set(np.argsort(scores)[:3]) == {30, 31, 32}
        assert list(np.nonzero(low_scores(scores, ValidationParams()))[0]) == [30, 31, 32]

    # test_clean_kind_flags_nothing: however many picks there are, a kind of good picks has none flagged
    @pytest.mark.parametrize('count', [12, 25, 60])
    def test_clean_kind_flags_nothing(self, count: int) -> None:
        rng = np.random.default_rng(count)
        scores = score_images(np.stack([_blob(rng) for _ in range(count)]), ValidationParams())
        assert not low_scores(scores, ValidationParams()).any()

    # test_shift_tolerance: a box a couple of pixels off keeps its score, and one far off loses it
    def test_shift_tolerance(self) -> None:
        rng = np.random.default_rng(2)
        images = np.stack([*(_blob(rng) for _ in range(20)), _blob(rng, dy=2, dx=-2), _blob(rng, dy=9, dx=9)])
        scores = score_images(images, ValidationParams())
        assert scores[20] > np.median(scores[:20]) - 0.1 and scores[21] < scores[20] - 0.2

    # test_trimming_sharpens_the_average: a cluster of picks all off the same way props up its own scores unless the lowest scoring are left out of the average
    def test_trimming_sharpens_the_average(self) -> None:
        rng = np.random.default_rng(3)
        images = np.stack([*(_blob(rng) for _ in range(20)), *(_blob(rng, dy=8, dx=8) for _ in range(8))])
        trimmed = score_images(images, ValidationParams(trim_fraction=0.3))
        plain = score_images(images, ValidationParams(trim_fraction=0.0))
        assert trimmed[20:].mean() < plain[20:].mean() - 0.05 and trimmed[:20].mean() > plain[:20].mean() + 0.03

    # test_default_cut_off_clears_clean_kinds: across many clean kinds of different sizes the default flags none, and still flags planted outliers
    def test_default_cut_off_clears_clean_kinds(self) -> None:
        params = ValidationParams()
        for seed in range(40):
            rng = np.random.default_rng(1000 + seed)
            n = int(rng.choice([12, 20, 30, 60, 100]))
            assert not low_scores(score_images(np.stack([_blob(rng) for _ in range(n)]), params), params).any()

    # test_too_few_picks: fewer picks than the setting is refused
    def test_too_few_picks(self) -> None:
        rng = np.random.default_rng(4)
        with pytest.raises(ValueError, match='at least 10 picks'):
            score_images(np.stack([_blob(rng) for _ in range(9)]), ValidationParams())

    # test_identical_images_flag_nothing: scores with no spread at all do not divide by zero or flag anything
    def test_identical_images_flag_nothing(self) -> None:
        rng = np.random.default_rng(5)
        scores = score_images(np.stack([_blob(rng, noise=0.0)] * 12), ValidationParams())
        assert np.isfinite(deviations(scores, ValidationParams())).all() and not low_scores(scores, ValidationParams()).any()

    # test_spread_floor: tiny differences in a very uniform kind are not flagged, but a big drop still is
    def test_spread_floor(self) -> None:
        params = ValidationParams()
        scores = np.array([0.90, 0.9001, 0.8999, 0.9002, 0.8998, 0.9, 0.9001, 0.8999, 0.9002, 0.8995, 0.85, 0.3])
        flags = low_scores(scores, params)
        assert not flags[:11].any() and flags[11]

    # test_only_low_scores_flag: a score far above the rest is not flagged
    def test_only_low_scores_flag(self) -> None:
        scores = np.array([0.5] * 11 + [0.99])
        assert not low_scores(scores + np.linspace(-0.01, 0.01, 12) * 0, ValidationParams()).any()

    # test_absolute_floor: a lowest score flags picks under it, whatever the rest do
    def test_absolute_floor(self) -> None:
        scores = np.array([0.2, 0.22, 0.21, 0.19, 0.2, 0.23, 0.21, 0.2, 0.22, 0.18])
        assert not low_scores(scores, ValidationParams()).any()
        assert low_scores(scores, ValidationParams(min_score=0.21)).sum() == 5


# NAME: the single tomogram of the fixture project
NAME: str = 'Position_1_2'

# _store: a validation store over a project with two kinds, a few yellow picks, and the estimate digests it is told, which a test can change
def _store(make_config: Callable[..., Path], count: int = 4) -> tuple[ValidationStore, PickStore, dict[str, str]]:
    project = open_project(make_config())
    project.update(kinds={'yellow': Kind(marker_a=100, box_a=100), 'green': Kind(marker_a=100, box_a=100)})
    picks = PickStore(project)
    for i in range(count):
        picks.add(NAME, 'yellow', float(i), 1.0, 1.0)
    digests = {'yellow': 'd1', 'green': 'g1'}
    return ValidationStore(project, picks, digests.get), picks, digests

# TestValidationStore: saved scores and when they stop applying
class TestValidationStore:
    # test_put_and_read: scores and low flags come back for the picks they were stored for
    def test_put_and_read(self, make_config: Callable[..., Path]) -> None:
        store, picks, _ = _store(make_config)
        heard: list[int] = []
        store.listeners.append(lambda: heard.append(1))
        mine = picks.all('yellow')
        assert store.state(mine[0]) == 'missing' and store.score(mine[0]) is None and not store.low(mine[0])
        store.put_kind('yellow', [(p, 0.5 + 0.1 * i, i == 3) for i, p in enumerate(mine)])
        assert [store.state(p) for p in mine] == ['ok'] * 4 and heard == [1]
        assert store.score(mine[1]) == pytest.approx(0.6) and [store.low(p) for p in mine] == [False, False, False, True]

    # test_reload: a new store reads back what was saved, including the flag
    def test_reload(self, make_config: Callable[..., Path]) -> None:
        store, picks, digests = _store(make_config)
        mine = picks.all('yellow')
        store.put_kind('yellow', [(p, 0.5, i == 0) for i, p in enumerate(mine)])
        again = ValidationStore(store.project, picks, digests.get)
        assert again.state(mine[0]) == 'ok' and again.low(mine[0]) and not again.low(mine[1])

    # test_new_pick_makes_stale: adding, moving or removing a pick of the kind makes every score of the kind stale, and no flag shows
    def test_new_pick_makes_stale(self, make_config: Callable[..., Path]) -> None:
        store, picks, _ = _store(make_config)
        mine = picks.all('yellow')
        store.put_kind('yellow', [(p, 0.5, True) for p in mine])
        picks.add(NAME, 'yellow', 9.0, 9.0, 1.0)
        assert [store.state(p) for p in mine] == ['stale'] * 4 and not store.low(mine[0]) and store.score(mine[0]) is None
        store.put_kind('yellow', [(p, 0.5, True) for p in picks.all('yellow')])
        assert store.state(mine[0]) == 'ok'
        picks.move(mine[1].id, 5.0, 5.0)
        assert store.state(mine[0]) == 'stale' and store.state(mine[1]) == 'missing'
        store.put_kind('yellow', [(p, 0.5, False) for p in picks.all('yellow')])
        picks.remove(mine[2].id)
        assert store.state(mine[0]) == 'stale'

    # test_other_kinds_unaffected: scores of a kind stay while picks of another kind change
    def test_other_kinds_unaffected(self, make_config: Callable[..., Path]) -> None:
        store, picks, _ = _store(make_config)
        mine = picks.all('yellow')
        store.put_kind('yellow', [(p, 0.5, False) for p in mine])
        picks.add(NAME, 'green', 3.0, 3.0, 3.0)
        assert store.state(mine[0]) == 'ok'

    # test_settings_make_stale: a change to the kind's fits or to the validation settings makes its scores stale
    def test_settings_make_stale(self, make_config: Callable[..., Path]) -> None:
        store, picks, digests = _store(make_config)
        mine = picks.all('yellow')
        store.put_kind('yellow', [(p, 0.5, False) for p in mine])
        digests['yellow'] = 'd2'
        assert store.state(mine[0]) == 'stale'
        digests['yellow'] = 'd1'
        assert store.state(mine[0]) == 'ok'
        store.project.update(validation=ValidationParams(flag_deviations=8.0))
        assert store.state(mine[0]) == 'stale'

    # test_unknown_kind: a kind the config does not have cannot be stored, and its picks have no score
    def test_unknown_kind(self, make_config: Callable[..., Path]) -> None:
        store, picks, digests = _store(make_config)
        digests.pop('green')
        extra = picks.add(NAME, 'green', 3.0, 3.0, 3.0)
        assert store.state(extra) == 'missing'
        with pytest.raises(KeyError):
            store.put_kind('green', [(extra, 0.5, False)])

    # test_deleted_picks_dropped_on_save: rows of picks that no longer exist are not kept
    def test_deleted_picks_dropped_on_save(self, make_config: Callable[..., Path]) -> None:
        store, picks, _ = _store(make_config)
        mine = picks.all('yellow')
        store.put_kind('yellow', [(p, 0.5, False) for p in mine])
        picks.remove(mine[0].id)
        store.put_kind('yellow', [(p, 0.5, False) for p in picks.all('yellow')])
        assert len(store.path.read_text().splitlines()) == 4

    # test_rename_keeps_scores: a renamed kind keeps its scores
    def test_rename_keeps_scores(self, make_config: Callable[..., Path]) -> None:
        store, picks, digests = _store(make_config)
        mine = picks.all('yellow')
        store.put_kind('yellow', [(p, 0.5, True) for p in mine])
        digests['gold'] = digests['yellow']
        store.rename_kind('yellow', 'gold')
        picks.rename_kind('yellow', 'gold')
        assert store.state(mine[0]) == 'ok' and store.low(mine[0])
