"""Translate a Contract 2 drone_state JSON dict to the agent-internal DroneState dataclass.

Sim publishes Contract 2 (shared/schemas/drone_state.json). The drone agent's
internal DroneState (perception.py) is a flatter shape with zone_bounds and a
resolved next_waypoint added — neither is on the wire.
"""
from __future__ import annotations

from typing import Optional

from agents.drone_agent.perception import DroneState
from sim.scenario import Scenario


def translate_drone_state(
    payload: dict, *, zone_bounds: dict, scenario: Scenario
) -> DroneState:
    """Build a DroneState from a Contract 2 dict.

    Raises KeyError for any missing required Contract 2 field.
    """
    required = ("drone_id", "position", "battery_pct", "heading_deg",
                "current_task", "current_waypoint_id",
                "assigned_survey_points_remaining")
    for key in required:
        if key not in payload:
            raise KeyError(f"drone_state payload missing required field: {key!r}")

    drone_id = payload["drone_id"]
    position = payload["position"]
    next_waypoint = _resolve_waypoint(scenario, drone_id, payload["current_waypoint_id"])
    current_task = payload["current_task"] or "survey"

    return DroneState(
        drone_id=drone_id,
        lat=float(position["lat"]),
        lon=float(position["lon"]),
        alt=float(position["alt"]),
        battery_pct=float(payload["battery_pct"]),
        heading_deg=float(payload["heading_deg"]),
        current_task=current_task,
        assigned_survey_points_remaining=int(payload["assigned_survey_points_remaining"]),
        zone_bounds=zone_bounds,
        next_waypoint=next_waypoint,
    )


def _resolve_waypoint(scenario: Scenario, drone_id: str, wp_id: Optional[str]) -> Optional[dict]:
    if wp_id is None:
        return None
    drone = next((d for d in scenario.drones if d.drone_id == drone_id), None)
    if drone is None:
        return None
    wp = next((w for w in drone.waypoints if w.id == wp_id), None)
    if wp is None:
        return None
    return {"id": wp.id, "lat": wp.lat, "lon": wp.lon}
