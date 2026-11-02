'''
pickmix: tests for parent geometry
'''

# Import external dependencies
import pytest
from pathlib import Path

# Import internal pickmix objects
from pickmix.estimate.registry import Fit
from pickmix.geometry import match_items
from pickmix.model import Pick
from pickmix.utils.io import Tomogram

# TOMOS: one tomogram at 5.36 A per voxel
TOMOS: dict[str, Tomogram] = {'T': Tomogram('T', 'T', Path('r.mrc'), None, 5.36, (4, 6, 8), 1.34, (32, 24, 16))}

# _item: a pick with a fit at the same place; radius_a is the fit's radius
def _item(i: int, kind: str, x: float, y: float, z: float, radius_a: float = 0.0, tomogram: str = 'T') -> tuple[Pick, Fit]:
    return Pick(i, tomogram, kind, x, y, z), Fit(x=x, y=y, z=z, radius_a=radius_a, box_a=100, snr=0, z_lo=round(z), z_hi=round(z))

# TestGeometry: parent finding and normals
class TestGeometry:
    # test_on_surface: a pick one radius from the centre gets the outward normal
    def test_on_surface(self) -> None:
        cage = _item(1, 'cage', 100, 100, 50, radius_a=536.0)
        green = _item(2, 'green', 200, 100, 50)
        [(pick_id, g)] = match_items([green], [cage], 100.0, TOMOS).items()
        assert pick_id == 2 and g.parent_id == 1
        assert g.normal == pytest.approx((1.0, 0.0, 0.0))
        assert (g.rot, g.tilt, g.psi) == pytest.approx((0.0, 90.0, 0.0))
        assert g.offset_a == pytest.approx(0.0, abs=1.0)

    # test_outside_tolerance: a pick far from the surface has no parent
    def test_outside_tolerance(self) -> None:
        cage = _item(1, 'cage', 100, 100, 50, radius_a=536.0)
        assert match_items([_item(2, 'green', 150, 100, 50)], [cage], 100.0, TOMOS) == {}

    # test_nearest_surface_wins: of two cages in range, the one whose surface is closer
    def test_nearest_surface_wins(self) -> None:
        a = _item(1, 'cage', 100, 100, 50, radius_a=536.0)
        b = _item(2, 'cage', 300, 100, 50, radius_a=536.0 + 40.0)
        green = _item(3, 'green', 200, 100, 50)
        assert match_items([green], [a, b], 100.0, TOMOS)[3].parent_id == 1

    # test_other_tomogram_ignored: parents in another tomogram do not count
    def test_other_tomogram_ignored(self) -> None:
        cage = _item(1, 'cage', 100, 100, 50, radius_a=536.0, tomogram='U')
        assert match_items([_item(2, 'green', 200, 100, 50)], [cage], 100.0, TOMOS) == {}

    # test_on_centre: a pick exactly on the parent's centre has no direction
    def test_on_centre(self) -> None:
        cage = _item(1, 'cage', 100, 100, 50, radius_a=0.0)
        assert match_items([_item(2, 'green', 100, 100, 50)], [cage], 100.0, TOMOS) == {}
