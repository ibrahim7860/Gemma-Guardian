"""Geographic helpers: haversine distance, meters↔degrees, linear interpolation.

Single source of truth used by sim/waypoint_runner.py and
agents/mesh_simulator/range_filter.py. Spherical-Earth approximation; accuracy
is well within the 200m × 200m demo grid tolerance defined in
docs/14-disaster-scene-design.md.
"""
from __future__ import annotations

import math
from typing import Tuple

# Mean Earth radius (m). Sufficient for sub-kilometer distances at low latitudes.
EARTH_RADIUS_M = 6_371_000.0
# WGS-84 equatorial-derived constant matching docs/14-disaster-scene-design.md
# ("1 meter ≈ 0.0000089°"). Used by meters_to_*_degrees so unit conversions stay
# numerically consistent with the documented authoring scale.
_METERS_PER_DEG_LAT = 111_319.0

LatLon = Tuple[float, float]
LatLonAlt = Tuple[float, float, float]


def haversine_meters(p1: LatLon, p2: LatLon) -> float:
    """Great-circle distance in meters between two (lat, lon) points."""
    lat1, lon1 = math.radians(p1[0]), math.radians(p1[1])
    lat2, lon2 = math.radians(p2[0]), math.radians(p2[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def meters_to_lat_degrees(meters: float) -> float:
    """Convert a north–south offset in meters to degrees of latitude."""
    return meters / _METERS_PER_DEG_LAT


def meters_to_lon_degrees(meters: float, latitude_deg: float) -> float:
    """Convert an east–west offset in meters to degrees of longitude at a given latitude."""
    cos_lat = math.cos(math.radians(latitude_deg))
    if cos_lat == 0:
        raise ValueError("latitude_deg of ±90° has undefined longitude scaling")
    return meters / (_METERS_PER_DEG_LAT * cos_lat)


def interpolate(a: LatLonAlt, b: LatLonAlt, frac: float) -> LatLonAlt:
    """Linearly interpolate (lat, lon, alt) between a and b. frac clamped to [0, 1]."""
    f = max(0.0, min(1.0, frac))
    return (
        a[0] + (b[0] - a[0]) * f,
        a[1] + (b[1] - a[1]) * f,
        a[2] + (b[2] - a[2]) * f,
    )
