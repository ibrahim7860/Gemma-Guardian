"""Smoke-tests every drone-side validator path emits a real RuleID."""
from __future__ import annotations

from agents.drone_agent.perception import DroneState, PerceptionBundle
from agents.drone_agent.validation import ValidationNode
from shared.contracts import RuleID


def _bundle(battery=80.0, points=5):
    return PerceptionBundle(
        frame_jpeg=b"",
        state=DroneState(
            drone_id="drone1", lat=34.0, lon=-118.0, alt=20.0,
            battery_pct=battery, heading_deg=0.0,
            current_task="survey",
            assigned_survey_points_remaining=points,
            zone_bounds={"lat_min": 33.9, "lat_max": 34.1, "lon_min": -118.1, "lon_max": -117.9},
        ),
    )


def test_prose_returns_prose_rule():
    r = ValidationNode().validate(None, _bundle())
    assert r.failure_reason == RuleID.PROSE_INSTEAD_OF_FUNCTION


def test_invalid_function_name_returns_invalid_function_rule():
    r = ValidationNode().validate({"function": "fly_to_moon", "arguments": {}}, _bundle())
    assert r.failure_reason == RuleID.INVALID_FUNCTION_NAME


def test_structural_failure_returns_structural_rule():
    # Missing required fields on report_finding -> caught structurally.
    r = ValidationNode().validate(
        {"function": "report_finding", "arguments": {}}, _bundle()
    )
    assert r.failure_reason == RuleID.STRUCTURAL_VALIDATION_FAILED


def test_severity_confidence_mismatch():
    r = ValidationNode().validate(
        {
            "function": "report_finding",
            "arguments": {
                "type": "victim", "severity": 5, "confidence": 0.4,
                "gps_lat": 34.0, "gps_lon": -118.0,
                "visual_description": "ten chars.",
            },
        },
        _bundle(),
    )
    assert r.failure_reason == RuleID.SEVERITY_CONFIDENCE_MISMATCH


def test_rtb_low_battery_invalid():
    r = ValidationNode().validate(
        {"function": "return_to_base", "arguments": {"reason": "low_battery"}},
        _bundle(battery=80.0),
    )
    assert r.failure_reason == RuleID.RTB_LOW_BATTERY_INVALID


def test_rtb_mission_complete_invalid():
    r = ValidationNode().validate(
        {"function": "return_to_base", "arguments": {"reason": "mission_complete"}},
        _bundle(points=3),
    )
    assert r.failure_reason == RuleID.RTB_MISSION_COMPLETE_INVALID


def test_continue_mission_always_valid():
    r = ValidationNode().validate(
        {"function": "continue_mission", "arguments": {}},
        _bundle(),
    )
    assert r.valid is True
