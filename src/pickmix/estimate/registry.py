'''
pickmix: estimator registry and the common fit result
'''

# Import external dependencies
import numpy as np
from collections.abc import Callable
from pydantic import BaseModel

# Import internal pickmix objects
from pickmix.config import Config, Kind

# Fit: what an estimator reports for one pick; x, y, z in reconstruction voxels, radius and box in Angstrom
class Fit(BaseModel):
    x: float
    y: float
    z: float
    radius_a: float
    box_a: float
    snr: float
    # slab the fit used, as inclusive slice indices
    z_lo: int
    z_hi: int
    # comma-separated warnings, empty when fine
    flag: str = ''

# Estimator: volume (z, y, x), pick (x, y, z) in voxels, kind, pixel size in Angstrom, config
type Estimator = Callable[[np.ndarray, tuple[float, float, float], Kind, float, Config], Fit]

# ESTIMATORS: registered estimators by name
ESTIMATORS: dict[str, Estimator] = {}

# register: decorator adding an estimator to the registry
def register(name: str) -> Callable[[Estimator], Estimator]:
    # add: store fn under name
    def add(fn: Estimator) -> Estimator:
        ESTIMATORS[name] = fn
        return fn
    return add

# imported last so the module can use the names above
from pickmix.estimate import none as _none  # noqa: E402,F401
