"""Translate a Contract 2 drone_state dict to the agent's DroneState dataclass."""
from __future__ import annotations

from pathlib import Path

import pytest

from agents.drone_agent.state_translator import translate_drone_state
from sim.scenario import load_scenario


REPO_ROOT = Path(__file__).resolve().parents[3]
SCENARIO = load_scenario(REPO_ROOT / "sim" / "scenarios" / "disaster_zone_v1.yaml")
ZONE_BOUNDS = {"lat_min": 33.99, "lat_max": 34.01,
               "lon_min": -118.51, "lon_max": -118.49}


def _valid_payload(**overrides) -> dict:
    base = {
        "drone_id": "drone1",
        "timestamp": "2026-05-15T14:23:11.342Z",
        "position": {"lat": 34.0005, "lon": -118.5003, "alt": 25.0},
        "velocity": {"vx": 1.0, "vy": 0.0, "vz": 0.0},
        "battery_pct": 87,
        "heading_deg": 135.0,
        "current_task": None,
        "current_waypoint_id": "sp_002",
        "assigned_survey_points_remaining": 3,
        "last_action": "none",
        "last_action_timestamp": None,
        "validation_failures_total": 0,
        "findings_count": 0,
        "in_mesh_range_of": [],
        "agent_status": "active",
    }
    base.update(overrides)
    return base


def test_translates_position_to_flat_fields():
    out = translate_drone_state(_valid_payload(), zone_bounds=ZONE_BOUNDS, scenario=SCENARIO)
    assert out.lat == pytest.approx(34.0005)
    assert out.lon == pytest.approx(-118.5003)
    assert out.alt == pytest.approx(25.0)


def test_battery_pct_integer_promotes_to_float():
    out = translate_drone_state(_valid_payload(battery_pct=42), zone_bounds=ZONE_BOUNDS, scenario=SCENARIO)
    assert isinstance(out.battery_pct, float)
    assert out.battery_pct == pytest.approx(42.0)


def test_zone_bounds_attached():
    out = translate_drone_state(_valid_payload(), zone_bounds=ZONE_BOUNDS, scenario=SCENARIO)
    assert out.zone_bounds == ZONE_BOUNDS


def test_next_waypoint_resolved_from_scenario():
    out = translate_drone_state(_valid_payload(current_waypoint_id="sp_002"),
                                zone_bounds=ZONE_BOUNDS, scenario=SCENARIO)
    assert out.next_waypoint == {"id": "sp_002", "lat": 34.0004, "lon": -118.5002}


def test_unknown_waypoint_id_yields_none():
    out = translate_drone_state(_valid_payload(current_waypoint_id="sp_999"),
                                zone_bounds=ZONE_BOUNDS, scenario=SCENARIO)
    assert out.next_waypoint is None


def test_current_task_null_defaults_to_survey():
    out = translate_drone_state(_valid_payload(current_task=None),
                                zone_bounds=ZONE_BOUNDS, scenario=SCENARIO)
    assert out.current_task == "survey"


def test_current_task_passthrough():
    out = translate_drone_state(_valid_payload(current_task="investigate_finding"),
                                zone_bounds=ZONE_BOUNDS, scenario=SCENARIO)
    assert out.current_task == "investigate_finding"


def test_missing_required_field_raises_keyerror():
    payload = _valid_payload()
    del payload["position"]
    with pytest.raises(KeyError, match="position"):
        translate_drone_state(payload, zone_bounds=ZONE_BOUNDS, scenario=SCENARIO)
