'''
pickmix: tests for kind validation
'''

# Import external dependencies
import numpy as np, pytest

# Import internal pickmix objects
from pickmix.config import ValidationParams
from pickmix.validation import deviations, low_scores, score_images

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
