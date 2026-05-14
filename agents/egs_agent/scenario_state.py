"""Build a Contract 3-compliant initial egs_state from the active scenario YAML."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from shared.contracts.zones import ZONE_BUFFER_M, mission_zone_polygon
from sim.scenario import load_scenario

SCENARIOS_DIR = Path(__file__).resolve().parents[2] / "sim" / "scenarios"


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
        "zone_polygon": mission_zone_polygon(scenario, buffer_m=ZONE_BUFFER_M),
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
