"""EGS-side validation: cross-drone dedup + structural delegation."""
from __future__ import annotations

from shared.contracts import RuleID

from agents.egs_agent.validation import EGSValidationNode


def test_cross_drone_duplicate_finding_detected():
    node = EGSValidationNode()
    finding_a = {
        "finding_id": "f_drone1_001",
        "source_drone_id": "drone1",
        "type": "victim",
        "gps_lat": 34.0000,
        "gps_lon": -118.0000,
        "timestamp": "2026-05-15T14:00:00.000Z",
    }
    finding_b = dict(finding_a)
    finding_b["finding_id"] = "f_drone2_001"
    finding_b["source_drone_id"] = "drone2"
    finding_b["gps_lat"] = 34.000018  # ~2m north
    finding_b["timestamp"] = "2026-05-15T14:00:10.000Z"

    a = node.validate_finding(finding_a)
    b = node.validate_finding(finding_b)
    assert a.valid is True
    assert b.valid is False
    assert b.failure_reason == RuleID.EGS_DUPLICATE_FINDING


def test_far_apart_findings_both_accepted():
    node = EGSValidationNode()
    a = {
        "finding_id": "f_drone1_001", "source_drone_id": "drone1",
        "type": "fire", "gps_lat": 34.0, "gps_lon": -118.0,
        "timestamp": "2026-05-15T14:00:00.000Z",
    }
    b = dict(a)
    b["finding_id"] = "f_drone2_001"
    b["source_drone_id"] = "drone2"
    b["gps_lat"] = 34.001  # ~111m away
    b["timestamp"] = "2026-05-15T14:00:05.000Z"
    assert node.validate_finding(a).valid
    assert node.validate_finding(b).valid


def test_different_type_not_duplicate():
    node = EGSValidationNode()
    a = {
        "finding_id": "f_drone1_001", "source_drone_id": "drone1",
        "type": "victim", "gps_lat": 34.0, "gps_lon": -118.0,
        "timestamp": "2026-05-15T14:00:00.000Z",
    }
    b = dict(a)
    b["finding_id"] = "f_drone2_001"
    b["source_drone_id"] = "drone2"
    b["type"] = "fire"
    b["timestamp"] = "2026-05-15T14:00:05.000Z"
    assert node.validate_finding(a).valid
    assert node.validate_finding(b).valid


def test_same_drone_not_caught_here():
    """EGS dedup is cross-drone only; same-drone duplicates are caught
    at the drone-side validator (DUPLICATE_FINDING)."""
    node = EGSValidationNode()
    a = {
        "finding_id": "f_drone1_001", "source_drone_id": "drone1",
        "type": "victim", "gps_lat": 34.0, "gps_lon": -118.0,
        "timestamp": "2026-05-15T14:00:00.000Z",
    }
    b = dict(a)
    b["finding_id"] = "f_drone1_002"
    b["timestamp"] = "2026-05-15T14:00:05.000Z"
    assert node.validate_finding(a).valid
    assert node.validate_finding(b).valid  # EGS does NOT dedup same-drone


def test_layer2_structural_delegation():
    node = EGSValidationNode()
    valid = {
        "function": "assign_survey_points",
        "arguments": {
            "assignments": [{"drone_id": "drone1", "survey_point_ids": ["sp_001"]}]
        },
    }
    invalid = {"function": "assign_survey_points", "arguments": {"assignments": []}}
    assert node.validate_egs_function_call(valid).valid is True
    bad = node.validate_egs_function_call(invalid)
    assert bad.valid is False
    assert bad.failure_reason == RuleID.STRUCTURAL_VALIDATION_FAILED


def test_layer3_structural_delegation():
    node = EGSValidationNode()
    valid = {"command": "set_language", "args": {"lang_code": "en"}}
    invalid = {"command": "set_language", "args": {"lang_code": "ENGLISH"}}
    assert node.validate_operator_command(valid).valid is True
    bad = node.validate_operator_command(invalid)
    assert bad.valid is False
    assert bad.failure_reason == RuleID.STRUCTURAL_VALIDATION_FAILED
