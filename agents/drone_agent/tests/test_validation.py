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

    The ZoneProvider's bootstrap must produce a usable mission-wide polygon
    so the validator can correctly accept findings inside it and reject
    findings outside, without crashing on `None`/empty zone state.

    Post-2026-05-13 PIP migration: bootstrap returns `{"polygon": [...]}`,
    not a bbox dict.
    """
    from pathlib import Path
    from agents.drone_agent.zone_provider import ZoneProvider
    from sim.scenario import load_scenario

    scenario_dir = Path(__file__).resolve().parents[3] / "sim" / "scenarios"
    scenario = load_scenario(scenario_dir / "disaster_zone_v1.yaml")
    provider = ZoneProvider(scenario)
    bootstrap = provider.current()

    # Bootstrap returns the polygon-shaped dict.
    assert set(bootstrap.keys()) == {"polygon"}
    polygon = bootstrap["polygon"]
    assert len(polygon) >= 4, "mission polygon must have at least 4 points"
    lats = [p[0] for p in polygon]
    lons = [p[1] for p in polygon]
    centroid_lat = (min(lats) + max(lats)) / 2.0
    centroid_lon = (min(lons) + max(lons)) / 2.0

    # A finding inside the bootstrap mission-wide zone passes validation.
    inside_call = {
        "function": "report_finding",
        "arguments": {
            "type": "victim", "severity": 3,
            "gps_lat": centroid_lat,
            "gps_lon": centroid_lon,
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
    mission_zone = ZoneProvider(scenario).current()  # {"polygon": [...]}
    polygon = mission_zone["polygon"]

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

    # Pick a target inside drone2's territory (mission-wide polygon includes
    # it, drone1's per-drone bbox does not).
    target_lat = 34.0004
    target_lon = -118.4992
    poly_lats = [p[0] for p in polygon]
    poly_lons = [p[1] for p in polygon]
    assert min(poly_lons) <= target_lon <= max(poly_lons), "target must be inside mission-wide"
    assert min(poly_lats) <= target_lat <= max(poly_lats)
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
    bundle = _scenario_bundle(mission_zone, target_lat, target_lon)
    r = ValidationNode().validate(call, bundle)
    assert r.valid, (
        f"Mission-wide semantics: a finding at drone2's territory must be valid "
        f"from drone1's agent. Got failure_reason={r.failure_reason}. "
        f"If this test starts failing, someone restored per-drone scoping; see "
        f"docs/plans/2026-05-13-drone-zone-from-egs-state.md §2."
    )


# --- 2026-05-13 point-in-polygon `_within_zone` migration regression tests --
# (See docs/plans/2026-05-13-drone-within-zone-point-in-polygon.md, §5.2.)

def test_finding_inside_bbox_but_outside_l_polygon_is_rejected():
    """T3 (PIP migration §5.2 — IRON RULE).

    Pins the intentional tightening of the 2026-05-13 PIP migration. Before:
    `ZoneProvider.update_from_polygon` ran `polygon_to_bbox` and the
    validator used a 4-corner bbox, so a finding inside the bbox-of-polygon
    but outside the actual polygon shape was wrongly accepted. After: the
    polygon is stored verbatim and `_within_zone` rejects the finding.

    Concretely: an L-shape with the concave corner at (1, 1) has bbox
    [0..2]×[0..2]. The point (1.5, 1.5) is inside the bbox but outside the
    L's body. Validator must return GPS_OUTSIDE_ZONE.

    Synthetic small-numerics polygon — the 50m → ~4.5e-4 deg tolerance is
    far smaller than the 0.5-unit margin between (1.5, 1.5) and the L's
    edges, so tolerance does not pollute the test.
    """
    l_shape = [
        [0.0, 0.0], [0.0, 2.0], [1.0, 2.0], [1.0, 1.0], [2.0, 1.0], [2.0, 0.0], [0.0, 0.0],
    ]
    bundle = _scenario_bundle({"polygon": l_shape}, gps_lat=1.5, gps_lon=1.5)
    call = {
        "function": "report_finding",
        "arguments": {
            "type": "fire", "severity": 2,
            "gps_lat": 1.5, "gps_lon": 1.5,
            "confidence": 0.7,
            "visual_description": "smoke column visible above structure",
        },
    }
    r = ValidationNode().validate(call, bundle)
    assert not r.valid, (
        "Finding inside the L-shape's enclosing bbox but outside the L itself "
        "must fail GPS_OUTSIDE_ZONE. If this test passes (valid), someone "
        "restored bbox-compression in ZoneProvider — see "
        "docs/plans/2026-05-13-drone-within-zone-point-in-polygon.md §2."
    )
    assert r.failure_reason == RuleID.GPS_OUTSIDE_ZONE


def test_polygon_edge_distance_tolerance_accepts_30m_outside_rejects_80m():
    """T4 (PIP migration §5.2).

    The bbox path outsets the rectangle by `tolerance_m`. The polygon path
    must match — a point ~30m outside an edge midpoint passes (within 50m
    tolerance); a point ~80m outside fails. Uses real lat/lon spacing
    around 34°N, where 1° lat ≈ 111.32 km and 1° lon ≈ 92.3 km.
    """
    # 0.01° square centered at (34.0, -118.5). At ~34°N this is roughly a
    # 1.1km × 0.9km rectangle — plenty of margin around the 50m tolerance.
    square = [
        [33.995, -118.505], [33.995, -118.495], [34.005, -118.495],
        [34.005, -118.505], [33.995, -118.505],
    ]
    # 30m north of the northern edge: 30 / 111_320 ≈ 0.000270°.
    near_lat = 34.005 + 30.0 / 111_320.0
    # 80m north of the northern edge: 80 / 111_320 ≈ 0.000718°.
    far_lat = 34.005 + 80.0 / 111_320.0

    inside_call = {
        "function": "report_finding",
        "arguments": {
            "type": "fire", "severity": 2,
            "gps_lat": near_lat, "gps_lon": -118.500,
            "confidence": 0.7,
            "visual_description": "smoke column visible above structure",
        },
    }
    outside_call = dict(inside_call)
    outside_call["arguments"] = dict(inside_call["arguments"], gps_lat=far_lat)

    v = ValidationNode()
    r_near = v.validate(inside_call, _scenario_bundle({"polygon": square}, near_lat, -118.500))
    assert r_near.valid, f"30m outside edge must pass under 50m tolerance; got {r_near.failure_reason}"

    r_far = v.validate(outside_call, _scenario_bundle({"polygon": square}, far_lat, -118.500))
    assert not r_far.valid
    assert r_far.failure_reason == RuleID.GPS_OUTSIDE_ZONE


def test_polygon_shape_validates_inside_point():
    """T5 (PIP migration §5.2). End-to-end: scenario -> polygon -> validator."""
    from pathlib import Path
    from shared.contracts.zones import mission_zone_polygon
    from sim.scenario import load_scenario

    scenario_dir = Path(__file__).resolve().parents[3] / "sim" / "scenarios"
    scenario = load_scenario(scenario_dir / "disaster_zone_v1.yaml")
    polygon = mission_zone_polygon(scenario)
    lats = [p[0] for p in polygon]
    lons = [p[1] for p in polygon]
    centroid_lat = (min(lats) + max(lats)) / 2.0
    centroid_lon = (min(lons) + max(lons)) / 2.0
    call = {
        "function": "report_finding",
        "arguments": {
            "type": "victim", "severity": 3,
            "gps_lat": centroid_lat, "gps_lon": centroid_lon,
            "confidence": 0.7,
            "visual_description": "person prone in debris field",
        },
    }
    bundle = _scenario_bundle({"polygon": polygon}, centroid_lat, centroid_lon)
    r = ValidationNode().validate(call, bundle)
    assert r.valid, f"finding at mission centroid must validate; got {r.failure_reason}"


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


# --- 2026-05-13 PIP `_within_zone` dispatcher + helper unit tests -----------
# Direct coverage of the internal helpers so future refactors can't silently
# regress them.

def test_within_zone_polygon_wins_when_both_keys_present():
    """Dispatcher precedence: polygon path beats bbox path.

    No caller passes both keys today, but the dispatcher's docstring promises
    polygon-wins; this test pins the contract so a future refactor that
    swaps the order trips this test.
    """
    from agents.drone_agent.validation import _within_zone

    # Tiny polygon that EXCLUDES (1.5, 1.5); bbox that INCLUDES it.
    bounds = {
        "polygon": [[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]],
        "lat_min": 0.0, "lat_max": 2.0, "lon_min": 0.0, "lon_max": 2.0,
    }
    # Tolerance 0 to remove edge-distance noise.
    assert _within_zone(1.5, 1.5, bounds, tolerance_m=0.0) is False, (
        "polygon path must be evaluated first; bbox would have accepted (1.5, 1.5)"
    )


def test_point_to_segment_m_distance_zero_on_endpoint():
    from agents.drone_agent.validation import _point_to_segment_m
    a = [34.0, -118.5]
    b = [34.0, -118.4]
    assert _point_to_segment_m(34.0, -118.5, a, b) == 0.0
    assert _point_to_segment_m(34.0, -118.4, a, b) == 0.0


def test_point_to_segment_m_perpendicular_drop_matches_lat_metres():
    """A point ~100m north of an east-west edge is computed as ~100m away."""
    from agents.drone_agent.validation import _point_to_segment_m
    a = [34.0, -118.5]
    b = [34.0, -118.4]  # east-west segment at lat=34.0
    target_lat = 34.0 + 100.0 / 111_320.0  # 100m north
    target_lon = -118.45  # midway along the segment in lon
    d = _point_to_segment_m(target_lat, target_lon, a, b)
    assert 99.0 <= d <= 101.0, f"expected ~100m, got {d:.2f}m"


def test_point_to_segment_m_past_endpoint_uses_vertex_distance():
    """A point off the end of a segment uses distance to the nearest vertex,
    not the (infinite-line) perpendicular projection."""
    from agents.drone_agent.validation import _point_to_segment_m
    a = [34.0, -118.5]
    b = [34.0, -118.4]
    # Target is 100m west of vertex `a` (past the segment's western end).
    target_lat = 34.0
    target_lon = -118.5 - 100.0 / 92_300.0  # 100m west at ~34°N
    d = _point_to_segment_m(target_lat, target_lon, a, b)
    assert 99.0 <= d <= 101.0, f"expected ~100m (to vertex a), got {d:.2f}m"


def test_point_to_segment_m_degenerate_segment_uses_vertex_distance():
    """If a==b (degenerate segment), distance is just the point-to-point distance."""
    from agents.drone_agent.validation import _point_to_segment_m
    a = [34.0, -118.5]
    b = [34.0, -118.5]
    # 100m north of the degenerate "segment".
    target_lat = 34.0 + 100.0 / 111_320.0
    target_lon = -118.5
    d = _point_to_segment_m(target_lat, target_lon, a, b)
    assert 99.0 <= d <= 101.0, f"expected ~100m, got {d:.2f}m"
