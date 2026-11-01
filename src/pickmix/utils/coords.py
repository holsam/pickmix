'''
pickmix: conversion utilities for reconstruction voxels and RELION centred Angstrom coordinates
'''

# Import external dependencies
import math

# Import internal pickmix objects
from pickmix.utils.io import Tomogram

# to_centred_angstrom: (x, y, z) reconstruction voxels converted to RELION centred (x, y, z) in Angstrom
def to_centred_angstrom(xyz: tuple[float, float, float], tomo: Tomogram) -> tuple[float, float, float]:
    x, y, z = xyz
    cx, cy, cz = _centre(tomo)
    return x * tomo.pixel_size - cx, y * tomo.pixel_size - cy, z * tomo.pixel_size - cz

# from_centred_angstrom: RELION centred (x, y, z) in Angstrom converted to (x, y, z) reconstruction voxels
def from_centred_angstrom(xyz: tuple[float, float, float], tomo: Tomogram) -> tuple[float, float, float]:
    x, y, z = xyz
    cx, cy, cz = _centre(tomo)
    return (x + cx) / tomo.pixel_size, (y + cy) / tomo.pixel_size, (z + cz) / tomo.pixel_size

# normal_to_euler: (rot, tilt, psi) in degrees turning the z axis onto a unit normal; psi, the spin about the normal, is arbitrary and 0
def normal_to_euler(normal: tuple[float, float, float]) -> tuple[float, float, float]:
    nx, ny, nz = normal
    return math.degrees(math.atan2(ny, nx)), math.degrees(math.acos(max(-1.0, min(1.0, nz)))), 0.0

# euler_to_normal: the unit vector the z axis is turned onto by (rot, tilt), in degrees; the inverse of normal_to_euler
def euler_to_normal(rot: float, tilt: float) -> tuple[float, float, float]:
    r, t = math.radians(rot), math.radians(tilt)
    return math.sin(t) * math.cos(r), math.sin(t) * math.sin(r), math.cos(t)

# _centre: tomogram centre in Angstrom, from unbinned size
def _centre(tomo: Tomogram) -> tuple[float, float, float]:
    cx, cy, cz = (n * tomo.unbinned_pixel_size / 2 for n in tomo.size_xyz)
    return cx, cy, cz
