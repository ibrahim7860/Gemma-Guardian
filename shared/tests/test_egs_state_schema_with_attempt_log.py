"""JSON Schema validation for the Contract 3 replan_in_flight_attempt_log
field (Phase 1, GATE 4 wow moment).

Four cases per the plan:
 1. validates payload with empty replan_in_flight_attempt_log
 2. validates payload with 3-attempt populated list
 3. rejects payload where the field is None (must be list)
 4. backward-compatibility: validates an old envelope missing the field
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from shared.contracts import validate

FIXTURE = (
    Path(__file__).parent.parent
    / "schemas" / "fixtures" / "valid" / "egs_state" / "01_active.json"
)


def _base_payload() -> dict:
    """Schema-valid baseline egs_state — reused across cases."""
    return json.loads(FIXTURE.read_text())


def test_empty_attempt_log_validates():
    """The default/cleared shape: empty list. This is what the dashboard
    sees on every tick when no replan is in flight."""
    payload = _base_payload()
    payload["replan_in_flight_attempt_log"] = []
    outcome = validate("egs_state", payload)
    assert outcome.valid is True, outcome.errors


def test_three_attempt_populated_list_validates():
    """The wow-moment shape: 3 attempts, two failed + one success."""
    payload = _base_payload()
    payload["replan_in_flight_attempt_log"] = [
        {
            "timestamp": "2026-05-12T14:23:11.342Z",
            "attempt_n": 1,
            "valid": False,
            "rule_id": "ASSIGNMENT_TOTAL_MISMATCH",
            "corrective_text": (
                "Your assignments cover 27 points but 25 are available. "
                "Reassign so every point is covered exactly once."
            ),
            "details": {"assigned": 27, "total": 25},
        },
        {
            "timestamp": "2026-05-12T14:23:12.100Z",
            "attempt_n": 2,
            "valid": False,
            "rule_id": "ASSIGNMENT_DUPLICATE_POINT",
            "corrective_text": "Survey point sp_004 appears in two drones' lists.",
            "details": {"duplicate_point_id": "sp_004"},
        },
        {
            "timestamp": "2026-05-12T14:23:13.050Z",
            "attempt_n": 3,
            "valid": True,
            "rule_id": None,
            "corrective_text": None,
            "details": {},
        },
    ]
    outcome = validate("egs_state", payload)
    assert outcome.valid is True, outcome.errors


def test_rejects_null_attempt_log():
    """The schema declares the field as array (or absent). Explicit null
    must be rejected — a missing field defaults to empty, a present null
    is a wire-shape error.
    """
    payload = _base_payload()
    payload["replan_in_flight_attempt_log"] = None
    outcome = validate("egs_state", payload)
    assert outcome.valid is False
    assert outcome.errors, "rejected payload must report at least one error"


def test_backwards_compat_missing_field_validates():
    """An old envelope from before the contract bump must still validate.
    The field is OPTIONAL on the wire (default_factory=[] on the Pydantic
    side handles construction).
    """
    payload = _base_payload()
    assert "replan_in_flight_attempt_log" not in payload, (
        "fixture must not pre-include the new field; this test guards the "
        "pre-bump envelope shape"
    )
    outcome = validate("egs_state", payload)
    assert outcome.valid is True, outcome.errors
