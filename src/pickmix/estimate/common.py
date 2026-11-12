'''
pickmix: helpers shared by the estimators that fit a z slab projection
'''

# Import external dependencies
import numpy as np
from scipy import ndimage

# prepare: a projection smoothed by smooth_sigma_a and flattened by subtracting a copy smoothed by highpass_sigma_a, both in Angstrom
def prepare(slab: np.ndarray, smooth_sigma_a: float, highpass_sigma_a: float, px: float) -> np.ndarray:
    smoothed = ndimage.gaussian_filter(slab, smooth_sigma_a / px)
    return smoothed - ndimage.gaussian_filter(smoothed, highpass_sigma_a / px)

# crop: sub-volume (z range clipped) round (y, x) with edge padding, the xy mask of real voxels, and the first z index
def crop(vol: np.ndarray, z0: int, z1: int, y: int, x: int, half: int) -> tuple[np.ndarray, np.ndarray, int]:
    z0, z1 = max(z0, 0), min(z1, vol.shape[0] - 1)
    ys = slice(max(y - half, 0), min(y + half + 1, vol.shape[1]))
    xs = slice(max(x - half, 0), min(x + half + 1, vol.shape[2]))
    block = np.asarray(vol[z0 : z1 + 1, ys, xs], dtype=np.float32)
    pad_y = (ys.start - (y - half), (y + half + 1) - ys.stop)
    pad_x = (xs.start - (x - half), (x + half + 1) - xs.stop)
    valid = np.pad(np.ones(block.shape[1:], dtype=bool), (pad_y, pad_x))
    return np.pad(block, ((0, 0), pad_y, pad_x), mode='edge'), valid, z0
