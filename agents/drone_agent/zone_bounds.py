"""Derive a per-drone zone bounding box from a scenario YAML.

Every drone is assigned a survey area equal to the bounding box of (home,
waypoint_1, ..., waypoint_n) plus a configurable buffer in meters. The
ValidationNode's GPS_OUTSIDE_ZONE check uses these bounds; per-drone bounds
also keep the validator from rejecting cross-drone findings during
multi-drone coordination — each drone is responsible for its own slice.

For GATE 4 (multi-drone coordination), this can be replaced by an
EGS-published mission polygon consumed via egs.state. For GATE 2, the
scenario YAML is the single source of truth.
"""
from __future__ import annotations

import math

from sim.scenario import Scenario


def derive_zone_bounds_from_scenario(
    scenario: Scenario, drone_id: str, *, buffer_m: float = 50.0
) -> dict:
    """Return {lat_min, lat_max, lon_min, lon_max} for `drone_id`.

    Raises KeyError if the drone_id is not present in the scenario.
    """
    drone = next((d for d in scenario.drones if d.drone_id == drone_id), None)
    if drone is None:
        known = sorted(d.drone_id for d in scenario.drones)
        raise KeyError(
            f"drone_id {drone_id!r} not in scenario {scenario.scenario_id!r} "
            f"(known: {known})"
        )

    lats = [drone.home.lat] + [w.lat for w in drone.waypoints]
    lons = [drone.home.lon] + [w.lon for w in drone.waypoints]

    deg_buffer_lat = buffer_m / 111_000.0
    avg_lat_rad = math.radians((min(lats) + max(lats)) / 2.0)
    deg_buffer_lon = buffer_m / (111_000.0 * max(math.cos(avg_lat_rad), 1e-6))

    return {
        "lat_min": min(lats) - deg_buffer_lat,
        "lat_max": max(lats) + deg_buffer_lat,
        "lon_min": min(lons) - deg_buffer_lon,
        "lon_max": max(lons) + deg_buffer_lon,
    }
