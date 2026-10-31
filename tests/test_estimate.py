'''
pickmix: tests for the estimator registry and passthrough
'''

# Import external dependencies
import numpy as np
from pathlib import Path

# Import internal pickmix objects
from pickmix.config import Config, Kind
from pickmix.estimate.registry import ESTIMATORS

# TestEstimateRegistry: estimator registry tests
class TestEstimateRegistry:
    # test_registered: the passthrough is available by name
    def test_registered(self) -> None:
        assert 'none' in ESTIMATORS

# TestEstimateNone: passthrough estimator tests
class TestEstimateNone:
    # test_passthrough: centre kept, size and box from the kind, no score
    def test_passthrough(self) -> None:
        kind = Kind(marker_a=100, box_a=120)
        config = Config(raw_dir=Path('/r'), tomograms_star=Path('/t.star'), kinds={'yellow': kind})
        fit = ESTIMATORS['none'](np.zeros((1, 1, 1)), (10.4, 20.0, 30.6), kind, 5.34, config)
        assert (fit.x, fit.y, fit.z) == (10.4, 20.0, 30.6)
        assert fit.radius_a == 50 and fit.box_a == 120 and fit.snr == 0.0
        assert fit.z_lo == fit.z_hi == 31 and fit.flag == ''
