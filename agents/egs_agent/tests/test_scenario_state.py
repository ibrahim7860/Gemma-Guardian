"""Tests for agents.egs_agent.scenario_state."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from agents.egs_agent import scenario_state as scenario_state_module
from agents.egs_agent.scenario_state import (
    SCENARIOS_DIR,
    ZONE_BUFFER_M,
    build_initial_egs_state,
)
from shared.contracts import validate
from sim.scenario import load_scenario


def test_build_initial_state_disaster_zone_v1():
    state = build_initial_egs_state("disaster_zone_v1")
    assert state["mission_id"] == "disaster_zone_v1"
    # disaster_zone_v1.yaml: 4 + 3 + 3 = 10 waypoints
    assert len(state["survey_points"]) == 10

    scenario = load_scenario(SCENARIOS_DIR / "disaster_zone_v1.yaml")
    expected_ids = [w.id for d in scenario.drones for w in d.waypoints]
    actual_ids = [sp["id"] for sp in state["survey_points"]]
    assert sorted(actual_ids) == sorted(expected_ids)
    assert len(set(actual_ids)) == len(actual_ids)  # no duplicates

    for sp in state["survey_points"]:
        assert sp["status"] == "unassigned"
        assert sp["assigned_to"] is None
    assert state["drones_summary"] == {}


def test_build_initial_state_passes_egs_state_schema():
    outcome = validate("egs_state", build_initial_egs_state("single_drone_smoke"))
    assert outcome.valid is True, outcome.errors


def test_zone_polygon_encloses_all_waypoints():
    state = build_initial_egs_state("disaster_zone_v1")
    polygon = state["zone_polygon"]
    # SW corner is polygon[0]; NE corner is polygon[2]
    lat_min, lon_min = polygon[0]
    lat_max, lon_max = polygon[2]

    scenario = load_scenario(SCENARIOS_DIR / "disaster_zone_v1.yaml")
    for drone in scenario.drones:
        for w in drone.waypoints:
            assert lat_min <= w.lat <= lat_max
            assert lon_min <= w.lon <= lon_max


def test_zone_polygon_is_closed_ccw():
    state = build_initial_egs_state("disaster_zone_v1")
    polygon = state["zone_polygon"]
    assert polygon[0] == polygon[-1]  # closed

    # Signed shoelace area; positive = CCW under a standard right-handed
    # coordinate frame where x grows east (lon) and y grows north (lat).
    # Our polygon is stored as [lat, lon], so x = lon, y = lat.
    area2 = 0.0
    for i in range(len(polygon) - 1):
        y1, x1 = polygon[i]
        y2, x2 = polygon[i + 1]
        area2 += (x1 * y2) - (x2 * y1)
    assert area2 > 0, f"polygon should be CCW (signed area > 0); got {area2}"


def test_unknown_scenario_id_raises():
    with pytest.raises(FileNotFoundError):
        build_initial_egs_state("does_not_exist")


def test_build_initial_state_single_drone_smoke_degenerate_bbox():
    """T-GAP-2: single-drone scenario with tightly clustered waypoints must
    still yield a non-degenerate bbox after the 50m buffer is applied."""
    state = build_initial_egs_state("single_drone_smoke")
    polygon = state["zone_polygon"]
    lat_min, lon_min = polygon[0]
    lat_max, lon_max = polygon[2]
    assert lat_max - lat_min > 0
    assert lon_max - lon_min > 0


class TestBaseImagePassThrough:
    """Task 8 of fixtures-swap plan: scenario YAML carries an optional
    `base_image_path` + `base_image_extents` pair. When set, the EGS surfaces
    them on egs.state so the Flutter map_panel can lock its bbox to the
    aerial overlay (LOCKED DESIGN DECISION D1)."""

    def test_disaster_zone_v1_includes_base_image_fields(self):
        """disaster_zone_v1 ships a static aerial after PR #35; egs.state
        must expose it so MissionState can plumb it to MapPanel."""
        state = build_initial_egs_state("disaster_zone_v1")
        assert "base_image_path" in state
        assert state["base_image_path"] == (
            "sim/fixtures/base_images/disaster_zone_v1_base.jpg"
        )
        assert state["base_image_extents"] == {
            "lat_min": 33.9990,
            "lat_max": 34.0010,
            "lon_min": -118.5010,
            "lon_max": -118.4990,
        }
        # Schema-validity check: the new fields don't violate Contract 3.
        outcome = validate("egs_state", state)
        assert outcome.valid is True, outcome.errors

    def test_single_drone_smoke_omits_base_image_fields(self):
        """single_drone_smoke has no static aerial — the fields stay omitted
        (NOT set to null), so the Flutter side falls back to the procedural
        grid (D2 universal fallback path)."""
        state = build_initial_egs_state("single_drone_smoke")
        assert "base_image_path" not in state
        assert "base_image_extents" not in state
        outcome = validate("egs_state", state)
        assert outcome.valid is True, outcome.errors


def test_malformed_scenario_yaml_raises_clean_error(tmp_path, monkeypatch):
    """T-GAP-3: a YAML missing a required Scenario field must raise
    pydantic.ValidationError, not silently produce a half-built state."""
    # Construct a YAML missing the `origin` field (required by Scenario).
    bad_payload = {
        "scenario_id": "broken_scenario",
        "area_m": 200,
        "drones": [
            {
                "drone_id": "drone1",
                "home": {"lat": 34.0, "lon": -118.5, "alt": 0},
                "waypoints": [{"id": "sp_x", "lat": 34.0, "lon": -118.5, "alt": 25}],
                "speed_mps": 5,
            }
        ],
    }
    bad_path = tmp_path / "broken_scenario.yaml"
    bad_path.write_text(yaml.safe_dump(bad_payload))

    monkeypatch.setattr(scenario_state_module, "SCENARIOS_DIR", tmp_path)
    with pytest.raises(ValidationError):
        build_initial_egs_state("broken_scenario")
