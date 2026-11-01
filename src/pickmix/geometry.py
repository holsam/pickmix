'''
pickmix: membrane-normal geometry of picks from nearest parent fit
'''

# Import external dependencies
import math
from dataclasses import dataclass

# Import internal pickmix objects
from pickmix.config import Config
from pickmix.estimate.registry import Fit
from pickmix.estimates import EstimateStore
from pickmix.model import Pick, PickStore
from pickmix.utils.coords import normal_to_euler
from pickmix.utils.io import Tomogram

# _Item: a pick with its current fit
type _Item = tuple[Pick, Fit]

# Parent: the geometry a pick gets from its parent; normal is a unit (x, y, z) vector from the parent's centre to the pick, angles in degrees
@dataclass(frozen=True)
class Parent:
    parent_id: int
    normal: tuple[float, float, float]
    offset_a: float
    rot: float
    tilt: float
    psi: float

# match_items: for each child, the nearest parent in its tomogram whose surface lies within tolerance_a of it; children with none are left out
def match_items(children: list[_Item], parents: list[_Item], tolerance_a: float, tomos: dict[str, Tomogram]) -> dict[int, Parent]:
    out: dict[int, Parent] = {}
    for pick, fit in children:
        px = tomos[pick.tomogram].pixel_size
        best: tuple[float, Pick, tuple[float, float, float], float] | None = None
        for parent, pfit in parents:
            if parent.tomogram != pick.tomogram:
                continue
            vec = (fit.x - pfit.x, fit.y - pfit.y, fit.z - pfit.z)
            dist = math.hypot(*vec)
            # a pick on the parent's centre has no direction
            if dist == 0:
                continue
            offset = dist * px - pfit.radius_a
            if abs(offset) <= tolerance_a and (best is None or abs(offset) < abs(best[0])):
                best = (offset, parent, vec, dist)
        if best is not None:
            offset, parent, vec, dist = best
            normal = (vec[0] / dist, vec[1] / dist, vec[2] / dist)
            out[pick.id] = Parent(parent.id, normal, offset, *normal_to_euler(normal))
    return out

# match_parents: geometry for the picks of a kind that has a parent kind, optionally only in one tomogram; picks without a current fit are left out
def match_parents(
    kind_name: str, config: Config, store: PickStore, estimates: EstimateStore, tomos: dict[str, Tomogram], *, tomogram: str | None = None,
) -> dict[int, Parent]:
    kind = config.kinds[kind_name]
    if kind.parent is None:
        return {}

    # items: picks of a kind with their current fits
    def items(name: str) -> list[_Item]:
        out = []
        for pick in store.all(name):
            fit = estimates.get(pick)
            if fit is not None and (tomogram is None or pick.tomogram == tomogram):
                out.append((pick, fit))
        return out

    return match_items(items(kind_name), items(kind.parent), kind.parent_tolerance_a, tomos)
