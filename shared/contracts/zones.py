"""Mission-zone math shared between EGS and the drone agent.

Single source of truth for the bbox-of-all-waypoints + buffer derivation that
both `agents/egs_agent/scenario_state.py` and `agents/drone_agent/zone_provider.py`
need. Extracted 2026-05-13 to close the duplication flagged by /plan-eng-review
on `docs/plans/2026-05-13-drone-zone-from-egs-state.md` (issue A1).

The buffer math here is calibrated for ~34 deg N (cos(34 deg) * 111_320 ~ 92_240).
Every shipped scenario lands within 0.01 deg of 34.0000 so the 50m buffer is
accurate to <1m. If a future scenario uses a very different latitude, the
buffer width along longitude will be off; recompute then or switch to a
proper cos(lat) factor.
"""
from __future__ import annotations

from typing import Dict, List

from sim.scenario import Scenario

ZONE_BUFFER_M = 50.0
"""Default buffer outset around the scenario waypoint extents, in meters.

EGS uses this as its scenario-state buffer policy (re-exported by
`agents/egs_agent/scenario_state.py`). The drone agent's bootstrap path
uses it so its initial zone matches what EGS will publish on first
`egs.state` tick.
"""

_M_PER_DEG_LAT = 111_320.0
_M_PER_DEG_LON = 92_300.0  # cos(34 deg) * 111_320; see module docstring


def mission_zone_polygon(scenario: Scenario, buffer_m: float = ZONE_BUFFER_M) -> List[List[float]]:
    """CCW closed bounding-box polygon of every drone's waypoints, outset by `buffer_m`.

    Returns five [lat, lon] points: SW, SE, NE, NW, SW (closed). Shape matches
    `shared/schemas/_common.json#/$defs/polygon` and is what EGS publishes on
    `egs.state.zone_polygon`.
    """
    lats = [w.lat for d in scenario.drones for w in d.waypoints]
    lons = [w.lon for d in scenario.drones for w in d.waypoints]
    dlat = buffer_m / _M_PER_DEG_LAT
    dlon = buffer_m / _M_PER_DEG_LON
    lat_min, lat_max = min(lats) - dlat, max(lats) + dlat
    lon_min, lon_max = min(lons) - dlon, max(lons) + dlon
    return [
        [lat_min, lon_min],
        [lat_min, lon_max],
        [lat_max, lon_max],
        [lat_max, lon_min],
        [lat_min, lon_min],
    ]


def polygon_to_bbox(polygon: List[List[float]]) -> Dict[str, float]:
    """Enclosing axis-aligned bbox of a polygon, as `{lat_min, lat_max, lon_min, lon_max}`.

    Used by `ZoneProvider.update_from_polygon` to derive the bbox the
    drone-agent ValidationNode uses for `GPS_OUTSIDE_ZONE`. For rectangular
    polygons (today's only kind) this is exact; for arbitrary polygons it is
    a strict superset, so validation stays *safe* (no false-negatives) but
    loose. Tightening to true point-in-polygon containment is tracked in
    `TODOS.md` under "Drone-Agent Follow-ups".
    """
    if not isinstance(polygon, list) or len(polygon) < 3:
        raise ValueError(f"polygon must be a list of >=3 [lat,lon] points; got {polygon!r}")
    lats: List[float] = []
    lons: List[float] = []
    for point in polygon:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError(f"each polygon point must be [lat, lon]; got {point!r}")
        lats.append(float(point[0]))
        lons.append(float(point[1]))
    return {
        "lat_min": min(lats),
        "lat_max": max(lats),
        "lon_min": min(lons),
        "lon_max": max(lons),
    }


def mission_zone_bbox(scenario: Scenario, buffer_m: float = ZONE_BUFFER_M) -> Dict[str, float]:
    """Convenience: bbox of the mission-zone polygon. Used by `ZoneProvider` bootstrap."""
    return polygon_to_bbox(mission_zone_polygon(scenario, buffer_m=buffer_m))
