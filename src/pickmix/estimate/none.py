'''
pickmix: passthrough estimator
'''

# Import external dependencies
import numpy as np

# Import internal pickmix objects
from pickmix.config import Config, Kind
from pickmix.estimate.registry import Fit, register

# passthrough: the pick as its own centre, size and box from the kind, no score
@register('none')
def passthrough(vol: np.ndarray, xyz: tuple[float, float, float], kind: Kind, pixel_size_a: float, config: Config) -> Fit:
    x, y, z = xyz
    return Fit(x=x, y=y, z=z, radius_a=kind.marker_a / 2, box_a=kind.box_a, snr=0.0, z_lo=round(z), z_hi=round(z))
