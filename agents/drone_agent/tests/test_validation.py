"""Unit tests for the validation node — runs without Ollama or Redis."""
from __future__ import annotations

import time

import numpy as np
import pytest

from agents.drone_agent.perception import DroneState, PerceptionBundle
from agents.drone_agent.validation import ValidationNode
from shared.contracts import RuleID


def _bundle(battery=87.0, remaining=10, zone=None):
    state = DroneState(
        drone_id="drone1",
        lat=34.0,
        lon=-118.5,
        alt=25.0,
        battery_pct=battery,
        heading_deg=0.0,
        current_task="survey",
        assigned_survey_points_remaining=remaining,
        zone_bounds=zone or {"lat_min": 33.99, "lat_max": 34.01, "lon_min": -118.51, "lon_max": -118.49},
    )
    return PerceptionBundle(frame_jpeg=b"", state=state)


def test_continue_mission_always_valid():
    v = ValidationNode()
    r = v.validate({"function": "continue_mission", "arguments": {}}, _bundle())
    assert r.valid


def test_prose_response_rejected():
    v = ValidationNode()
    r = v.validate(None, _bundle())
    assert not r.valid
    assert r.failure_reason == RuleID.PROSE_INSTEAD_OF_FUNCTION


def test_invalid_function_rejected():
    v = ValidationNode()
    r = v.validate({"function": "fly_to_moon", "arguments": {}}, _bundle())
    assert not r.valid
    assert r.failure_reason == RuleID.INVALID_FUNCTION_NAME


def test_severity_confidence_mismatch():
    v = ValidationNode()
    call = {
        "function": "report_finding",
        "arguments": {
            "type": "victim", "severity": 5, "gps_lat": 34.0, "gps_lon": -118.5,
            "confidence": 0.4, "visual_description": "person prone in rubble",
        },
    }
    r = v.validate(call, _bundle())
    assert not r.valid
    assert r.failure_reason == RuleID.SEVERITY_CONFIDENCE_MISMATCH


def test_gps_outside_zone():
    v = ValidationNode()
    call = {
        "function": "report_finding",
        "arguments": {
            "type": "fire", "severity": 3, "gps_lat": 50.0, "gps_lon": 50.0,
            "confidence": 0.7, "visual_description": "flames on rooftop visible",
        },
    }
    r = v.validate(call, _bundle())
    assert not r.valid
    assert r.failure_reason == RuleID.GPS_OUTSIDE_ZONE


def test_visual_description_too_short():
    # visual_description length is now enforced by JSON Schema (minLength).
    # The failure surfaces as STRUCTURAL_VALIDATION_FAILED, not a distinct code.
    v = ValidationNode()
    call = {
        "function": "report_finding",
        "arguments": {
            "type": "fire", "severity": 2, "gps_lat": 34.0, "gps_lon": -118.5,
            "confidence": 0.5, "visual_description": "fire",
        },
    }
    r = v.validate(call, _bundle())
    assert not r.valid
    assert r.failure_reason == RuleID.STRUCTURAL_VALIDATION_FAILED


def test_duplicate_finding():
    v = ValidationNode()
    call = {
        "function": "report_finding",
        "arguments": {
            "type": "victim", "severity": 3, "gps_lat": 34.0, "gps_lon": -118.5,
            "confidence": 0.7, "visual_description": "person partially covered debris",
        },
    }
    bundle = _bundle()
    r1 = v.validate(call, bundle)
    assert r1.valid
    v.record_success(call, bundle)
    r2 = v.validate(call, bundle)
    assert not r2.valid
    assert r2.failure_reason == RuleID.DUPLICATE_FINDING


def test_low_battery_must_actually_be_low():
    v = ValidationNode()
    call = {"function": "return_to_base", "arguments": {"reason": "low_battery"}}
    r = v.validate(call, _bundle(battery=80.0))
    assert not r.valid
    assert r.failure_reason == RuleID.RTB_LOW_BATTERY_INVALID

    r2 = v.validate(call, _bundle(battery=15.0))
    assert r2.valid


# --- 2026-05-13 mission-zone-from-egs-state migration regression tests ----
# (See docs/plans/2026-05-13-drone-zone-from-egs-state.md, plan-eng-review T1/T2.)

def _scenario_bundle(zone_bounds: dict, gps_lat: float, gps_lon: float):
    """Build a PerceptionBundle whose state.zone_bounds is set to `zone_bounds`."""
    state = DroneState(
        drone_id="drone1",
        lat=gps_lat,
        lon=gps_lon,
        alt=25.0,
        battery_pct=87.0,
        heading_deg=0.0,
        current_task="survey",
        assigned_survey_points_remaining=10,
        zone_bounds=zone_bounds,
    )
    return PerceptionBundle(frame_jpeg=b"", state=state)


def test_validation_uses_bootstrap_zone_before_first_egs_state():
    """T1 (plan-eng-review §5.4): drone boots, no egs.state has arrived yet.

    The ZoneProvider's bootstrap must produce a usable mission-wide bbox so
    the validator can correctly accept findings inside it and reject findings
    outside, without crashing on `None`/empty zone state.
    """
    from pathlib import Path
    from agents.drone_agent.zone_provider import ZoneProvider
    from sim.scenario import load_scenario

    scenario_dir = Path(__file__).resolve().parents[3] / "sim" / "scenarios"
    scenario = load_scenario(scenario_dir / "disaster_zone_v1.yaml")
    provider = ZoneProvider(scenario)
    bootstrap = provider.current()

    # Bootstrap returns a real dict with all 4 keys.
    assert set(bootstrap.keys()) == {"lat_min", "lat_max", "lon_min", "lon_max"}
    assert bootstrap["lat_min"] < bootstrap["lat_max"]
    assert bootstrap["lon_min"] < bootstrap["lon_max"]

    # A finding inside the bootstrap mission-wide zone passes validation.
    inside_call = {
        "function": "report_finding",
        "arguments": {
            "type": "victim", "severity": 3,
            "gps_lat": (bootstrap["lat_min"] + bootstrap["lat_max"]) / 2.0,
            "gps_lon": (bootstrap["lon_min"] + bootstrap["lon_max"]) / 2.0,
            "confidence": 0.7,
            "visual_description": "person prone in rubble, partial cover",
        },
    }
    v = ValidationNode()
    r = v.validate(inside_call, _scenario_bundle(bootstrap, 34.0005, -118.5))
    assert r.valid, f"finding inside bootstrap mission zone must be valid; got {r.failure_reason}"

    # A finding well outside the bootstrap zone fails with GPS_OUTSIDE_ZONE.
    outside_call = dict(inside_call)
    outside_call["arguments"] = dict(inside_call["arguments"], gps_lat=50.0, gps_lon=50.0)
    r2 = v.validate(outside_call, _scenario_bundle(bootstrap, 34.0005, -118.5))
    assert not r2.valid
    assert r2.failure_reason == RuleID.GPS_OUTSIDE_ZONE


def test_finding_inside_mission_zone_outside_old_per_drone_slice_is_valid():
    """T2 (plan-eng-review §5.5, IRON RULE regression).

    Pins the intentional semantics change of the 2026-05-13 migration:
    GPS_OUTSIDE_ZONE no longer fires for findings that are inside the
    mission-wide zone but outside one drone's old per-drone slice. A future
    code-reader who tries to restore per-drone scoping will trip this test
    and find the docstring explaining why.

    Concretely: disaster_zone_v1 places drone1 around lon -118.5002 and
    drone2 around lon -118.4992. Mission-wide bbox covers both. The old
    per-drone slice (with 50m buffer) would have rejected a finding at
    drone2's position when reported by drone1's agent. New semantics: valid.
    """
    from pathlib import Path
    from agents.drone_agent.zone_provider import ZoneProvider
    from sim.scenario import load_scenario

    scenario_dir = Path(__file__).resolve().parents[3] / "sim" / "scenarios"
    scenario = load_scenario(scenario_dir / "disaster_zone_v1.yaml")
    mission_bbox = ZoneProvider(scenario).current()

    # Reproduce the old per-drone derivation inline so this test does not
    # depend on the (deleted) `derive_zone_bounds_from_scenario` function.
    import math
    drone1 = next(d for d in scenario.drones if d.drone_id == "drone1")
    lats = [drone1.home.lat] + [w.lat for w in drone1.waypoints]
    lons = [drone1.home.lon] + [w.lon for w in drone1.waypoints]
    buffer_m = 50.0
    deg_buffer_lat = buffer_m / 111_000.0
    avg_lat_rad = math.radians((min(lats) + max(lats)) / 2.0)
    deg_buffer_lon = buffer_m / (111_000.0 * max(math.cos(avg_lat_rad), 1e-6))
    old_per_drone1 = {
        "lat_min": min(lats) - deg_buffer_lat,
        "lat_max": max(lats) + deg_buffer_lat,
        "lon_min": min(lons) - deg_buffer_lon,
        "lon_max": max(lons) + deg_buffer_lon,
    }

    # Pick a target inside drone2's territory (mission-wide bbox includes it,
    # drone1's per-drone bbox does not).
    target_lat = 34.0004
    target_lon = -118.4992
    assert mission_bbox["lon_min"] <= target_lon <= mission_bbox["lon_max"], "target must be inside mission-wide"
    assert mission_bbox["lat_min"] <= target_lat <= mission_bbox["lat_max"]
    assert not (old_per_drone1["lon_min"] <= target_lon <= old_per_drone1["lon_max"]), (
        "target must be OUTSIDE drone1's old per-drone slice; otherwise this test "
        "no longer demonstrates the semantics change"
    )

    call = {
        "function": "report_finding",
        "arguments": {
            "type": "victim", "severity": 3,
            "gps_lat": target_lat, "gps_lon": target_lon,
            "confidence": 0.7,
            "visual_description": "person prone in rubble, partial cover",
        },
    }
    bundle = _scenario_bundle(mission_bbox, target_lat, target_lon)
    r = ValidationNode().validate(call, bundle)
    assert r.valid, (
        f"Mission-wide semantics: a finding at drone2's territory must be valid "
        f"from drone1's agent. Got failure_reason={r.failure_reason}. "
        f"If this test starts failing, someone restored per-drone scoping; see "
        f"docs/plans/2026-05-13-drone-zone-from-egs-state.md §2."
    )


def test_mission_complete_must_be_complete():
    v = ValidationNode()
    call = {"function": "return_to_base", "arguments": {"reason": "mission_complete"}}
    r = v.validate(call, _bundle(remaining=5))
    assert not r.valid

    r2 = v.validate(call, _bundle(remaining=0))
    assert r2.valid


def test_mark_explored_cannot_decrease():
    v = ValidationNode()
    bundle = _bundle()
    high = {"function": "mark_explored", "arguments": {"zone_id": "z1", "coverage_pct": 60.0}}
    r1 = v.validate(high, bundle)
    assert r1.valid
    v.record_success(high, bundle)

    low = {"function": "mark_explored", "arguments": {"zone_id": "z1", "coverage_pct": 50.0}}
    r2 = v.validate(low, bundle)
    assert not r2.valid
    assert r2.failure_reason == RuleID.COVERAGE_DECREASED
