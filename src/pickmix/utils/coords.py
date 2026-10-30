'''
pickmix: conversion utilities for reconstruction voxels and RELION centred Angstrom coordinates
'''

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

# _centre: tomogram centre in Angstrom, from unbinned size
def _centre(tomo: Tomogram) -> tuple[float, float, float]:
    cx, cy, cz = (n * tomo.unbinned_pixel_size / 2 for n in tomo.size_xyz)
    return cx, cy, cz
