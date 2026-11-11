'''
pickmix: kind validation, scores of each pick against the average of its kind
'''

# Import external dependencies
import numpy as np

# Import internal pickmix objects
from pickmix.config import ValidationParams

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
