"""Bridge aggregator must preserve egs_state.replan_in_flight_attempt_log
verbatim through deep-copy snapshot (Phase 1, GATE 4 wow moment).

Two cases per the plan:
 1. 3-attempt populated log → snapshot preserves the list verbatim.
 2. Empty log → preserved as empty list (not dropped).

Pattern mirrors test_aggregator_finding_approval_stamp.py.
"""
from __future__ import annotations

from copy import deepcopy

from frontend.ws_bridge.aggregator import StateAggregator

_SEED = {
    "type": "state_update",
    "timestamp": "2026-05-12T00:00:00.000Z",
    "contract_version": "1.1.0",
    "egs_state": {
        "mission_id": "test",
        "mission_status": "active",
        "timestamp": "2026-05-12T00:00:00.000Z",
        "zone_polygon": [],
        "survey_points": [],
        "drones_summary": {},
        "findings_count_by_type": {
            "victim": 0, "fire": 0, "smoke": 0,
            "damaged_structure": 0, "blocked_route": 0,
        },
        "recent_validation_events": [],
        "active_zone_ids": [],
        "approved_findings": {},
        "replan_in_flight_attempt_log": [],
    },
    "active_findings": [],
    "active_drones": [],
}


def _three_attempts() -> list:
    return [
        {
            "timestamp": "2026-05-12T14:23:11.342Z",
            "attempt_n": 1,
            "valid": False,
            "rule_id": "ASSIGNMENT_TOTAL_MISMATCH",
            "corrective_text": "Your assignments cover 27 points but 25 are available. Reassign so every point is covered exactly once.",
            "details": {"assigned": 27, "total": 25},
        },
        {
            "timestamp": "2026-05-12T14:23:12.100Z",
            "attempt_n": 2,
            "valid": False,
            "rule_id": "ASSIGNMENT_DUPLICATE_POINT",
            "corrective_text": "Survey point sp_004 appears in two drones' lists. Each point must belong to exactly one drone.",
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


def test_three_attempt_log_passes_through_verbatim():
    """The aggregator snapshot must preserve every field, including the
    corrective_text string the dashboard banner renders verbatim.
    """
    agg = StateAggregator(max_findings=10, seed_envelope=deepcopy(_SEED))
    egs = deepcopy(_SEED["egs_state"])
    egs["replan_in_flight_attempt_log"] = _three_attempts()
    agg.update_egs_state(egs)
    snap = agg.snapshot(timestamp_iso="2026-05-12T00:00:02.000Z")
    log = snap["egs_state"]["replan_in_flight_attempt_log"]
    assert log == _three_attempts(), (
        "aggregator must pass the replan_in_flight_attempt_log through "
        "verbatim (deep-copied but value-equal). Any mutation here breaks "
        "the wow-moment banner rendering."
    )

    # Deep-copy invariant: mutating the snapshot must not touch the
    # internal egs bucket.
    snap["egs_state"]["replan_in_flight_attempt_log"][0]["corrective_text"] = "MUTATED"
    snap2 = agg.snapshot(timestamp_iso="2026-05-12T00:00:03.000Z")
    assert snap2["egs_state"]["replan_in_flight_attempt_log"][0]["corrective_text"] != "MUTATED"


def test_empty_attempt_log_preserved_as_empty_list():
    """Empty log must surface as an empty list, not be dropped or replaced
    with None. The dashboard's banner branches on len(...) == 0.
    """
    agg = StateAggregator(max_findings=10, seed_envelope=deepcopy(_SEED))
    egs = deepcopy(_SEED["egs_state"])
    egs["replan_in_flight_attempt_log"] = []
    agg.update_egs_state(egs)
    snap = agg.snapshot(timestamp_iso="2026-05-12T00:00:02.000Z")
    assert "replan_in_flight_attempt_log" in snap["egs_state"]
    assert snap["egs_state"]["replan_in_flight_attempt_log"] == []
