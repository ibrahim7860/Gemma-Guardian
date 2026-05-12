"""Build a Contract 3-compliant initial egs_state from the active scenario YAML."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from sim.scenario import Scenario, load_scenario

SCENARIOS_DIR = Path(__file__).resolve().parents[2] / "sim" / "scenarios"
ZONE_BUFFER_M = 50.0  # outset around waypoint extents
# 1 deg latitude ~ 111_320 m; lon scaling is cos(lat) * 111_320, but for
# 50m buffers at LA latitude (~34 deg N) the per-degree lon factor is ~92_300.
# We use a fixed approximation to keep this pure (no library calls).
_M_PER_DEG_LAT = 111_320.0
_M_PER_DEG_LON = 92_300.0
# NOTE: _M_PER_DEG_LON is calibrated for ~34 deg N (cos(34 deg) * 111_320 ~ 92_240).
# Every shipped scenario lands within 0.01 deg of 34.0000 so the 50m buffer is
# accurate to <1m. If a future scenario uses a very different latitude, the
# buffer width along longitude will be off; recompute then or switch to a
# proper cos(lat) factor.


def _bbox_polygon(scenario: Scenario, buffer_m: float) -> List[List[float]]:
    """Return CCW closed bounding-box polygon for all scenario waypoints, outset by buffer_m."""
    lats = [w.lat for d in scenario.drones for w in d.waypoints]
    lons = [w.lon for d in scenario.drones for w in d.waypoints]
    dlat = buffer_m / _M_PER_DEG_LAT
    dlon = buffer_m / _M_PER_DEG_LON
    lat_min, lat_max = min(lats) - dlat, max(lats) + dlat
    lon_min, lon_max = min(lons) - dlon, max(lons) + dlon
    # CCW from SW corner: SW -> SE -> NE -> NW -> SW (closed).
    return [
        [lat_min, lon_min],
        [lat_min, lon_max],
        [lat_max, lon_max],
        [lat_max, lon_min],
        [lat_min, lon_min],
    ]


def build_initial_egs_state(scenario_id: str) -> Dict[str, Any]:
    """Build a schema-valid initial egs_state from the active scenario YAML."""
    path = SCENARIOS_DIR / f"{scenario_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"scenario YAML not found: {path}")
    scenario = load_scenario(path)

    survey_points = [
        {
            "id": w.id,
            "lat": w.lat,
            "lon": w.lon,
            "assigned_to": None,
            "status": "unassigned",
        }
        for d in scenario.drones
        for w in d.waypoints
    ]

    state: Dict[str, Any] = {
        "mission_id": scenario.scenario_id,
        "mission_status": "active",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "zone_polygon": _bbox_polygon(scenario, ZONE_BUFFER_M),
        "survey_points": survey_points,
        "drones_summary": {},
        "findings_count_by_type": {
            "victim": 0,
            "fire": 0,
            "smoke": 0,
            "damaged_structure": 0,
            "blocked_route": 0,
        },
        "recent_validation_events": [],
        "active_zone_ids": [],
        "approved_findings": {},
        "replan_in_flight_attempt_log": [],
    }
    # Pass through scenario.base_image_path / base_image_extents to the
    # Flutter dashboard via egs.state. The Pydantic Scenario validator
    # already enforces both-or-neither (sim/scenario.py); we trust that
    # here. When unset, the dashboard falls back to its procedural grid
    # background (LOCKED DESIGN DECISION D2).
    if scenario.base_image_path is not None and scenario.base_image_extents is not None:
        state["base_image_path"] = scenario.base_image_path
        state["base_image_extents"] = scenario.base_image_extents.model_dump()
    return state
