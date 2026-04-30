"""Unit tests for the validation node — runs without Ollama or Redis."""
from __future__ import annotations

import time

import numpy as np
import pytest

from agents.drone_agent.perception import DroneState, PerceptionBundle
from agents.drone_agent.validation import ValidationNode


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
    assert r.failure_reason == "prose_instead_of_function"


def test_invalid_function_rejected():
    v = ValidationNode()
    r = v.validate({"function": "fly_to_moon", "arguments": {}}, _bundle())
    assert not r.valid
    assert r.failure_reason == "invalid_function_name"


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
    assert r.failure_reason == "severity_confidence_mismatch"


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
    assert r.failure_reason == "gps_outside_zone"


def test_visual_description_too_short():
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
    assert r.failure_reason == "visual_description_too_short"


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
    assert r2.failure_reason == "duplicate_finding"


def test_low_battery_must_actually_be_low():
    v = ValidationNode()
    call = {"function": "return_to_base", "arguments": {"reason": "low_battery"}}
    r = v.validate(call, _bundle(battery=80.0))
    assert not r.valid
    assert r.failure_reason == "return_to_base_low_battery_invalid"

    r2 = v.validate(call, _bundle(battery=15.0))
    assert r2.valid


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
    assert r2.failure_reason == "coverage_decreased"
