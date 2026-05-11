"""Unit tests for the LDD-2 snapshot-time approval stamp.

The bridge aggregator joins `egs_state.approved_findings` (a {finding_id: "approved"|
"dismissed"} map shipped by Qasim's PR #45) against active_findings[] at snapshot time
and stamps `approved` (bool, what the dashboard reads at mission_state.dart:542) and
`operator_status` (enum, matches Contract 4 _common.json#/$defs/operator_status) onto
matching findings WITHOUT mutating the internal _findings bucket.

See docs/superpowers/plans/2026-05-11-finding-approval-egs-consumer.md LDD-2.
"""
from __future__ import annotations

from copy import deepcopy

from frontend.ws_bridge.aggregator import StateAggregator

_SEED = {
    "type": "state_update",
    "timestamp": "2026-05-11T00:00:00.000Z",
    "contract_version": "1.0.0",
    "egs_state": {
        "mission_id": "test",
        "mission_status": "active",
        "timestamp": "2026-05-11T00:00:00.000Z",
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
    },
    "active_findings": [],
    "active_drones": [],
}


def _finding(fid: str) -> dict:
    return {
        "finding_id": fid,
        "source_drone_id": "drone1",
        "timestamp": "2026-05-11T00:00:01.000Z",
        "type": "victim",
        "severity": 3,
        "gps_lat": 34.0,
        "gps_lon": -118.5,
        "altitude": 25.0,
        "confidence": 0.8,
        "visual_description": "test",
        "image_path": "/tmp/x.jpg",
        "validated": True,
        "validation_retries": 0,
        "operator_status": "pending",
    }


def test_snapshot_stamps_approved_for_finding_in_approved_findings_map():
    agg = StateAggregator(max_findings=10, seed_envelope=deepcopy(_SEED))
    agg.add_finding(_finding("f_drone1_001"))
    egs = deepcopy(_SEED["egs_state"])
    egs["approved_findings"] = {"f_drone1_001": "approved"}
    agg.update_egs_state(egs)
    snap = agg.snapshot(timestamp_iso="2026-05-11T00:00:02.000Z")
    [f] = snap["active_findings"]
    # NOTE: the `approved: bool` form was removed after the Task 6 e2e
    # surfaced that Contract 4 (`shared/schemas/finding.json:7`) sets
    # `additionalProperties: false`, so any extra property silently
    # killed `_emit_loop`. Stamp is now `operator_status` only.
    assert f["operator_status"] == "approved"


def test_snapshot_stamps_dismissed_for_finding_in_approved_findings_map():
    agg = StateAggregator(max_findings=10, seed_envelope=deepcopy(_SEED))
    agg.add_finding(_finding("f_drone1_002"))
    egs = deepcopy(_SEED["egs_state"])
    egs["approved_findings"] = {"f_drone1_002": "dismissed"}
    agg.update_egs_state(egs)
    snap = agg.snapshot(timestamp_iso="2026-05-11T00:00:02.000Z")
    [f] = snap["active_findings"]
    assert f["operator_status"] == "dismissed"


def test_snapshot_leaves_pending_finding_untouched():
    """A finding NOT in approved_findings keeps operator_status=pending and
    gets no `approved` key (we don't inject for the pending case to minimize
    wire churn)."""
    agg = StateAggregator(max_findings=10, seed_envelope=deepcopy(_SEED))
    agg.add_finding(_finding("f_drone1_003"))
    snap = agg.snapshot(timestamp_iso="2026-05-11T00:00:02.000Z")
    [f] = snap["active_findings"]
    assert f["operator_status"] == "pending"
    assert "approved" not in f


def test_snapshot_handles_orphan_id_silently():
    """Regression: egs_state.approved_findings may reference a finding_id
    that is NOT in self._findings (bridge restart drops the finding cache
    but egs.state retains the approval registry). The snapshot must
    silently skip the orphan id — no crash, no extra entry in
    active_findings, no error log."""
    agg = StateAggregator(max_findings=10, seed_envelope=deepcopy(_SEED))
    egs = deepcopy(_SEED["egs_state"])
    egs["approved_findings"] = {"f_drone1_orphan": "approved"}
    agg.update_egs_state(egs)
    snap = agg.snapshot(timestamp_iso="2026-05-11T00:00:02.000Z")
    assert snap["active_findings"] == []


def test_snapshot_handles_missing_or_none_approved_findings_field():
    """The egs_state schema field is OPTIONAL — the bridge must accept
    payloads where the key is missing OR explicitly None and treat both
    identically to {}."""
    agg = StateAggregator(max_findings=10, seed_envelope=deepcopy(_SEED))
    agg.add_finding(_finding("f_drone1_004"))
    egs_missing = deepcopy(_SEED["egs_state"])
    del egs_missing["approved_findings"]
    agg.update_egs_state(egs_missing)
    snap1 = agg.snapshot(timestamp_iso="2026-05-11T00:00:02.000Z")
    assert "approved" not in snap1["active_findings"][0]
    egs_none = deepcopy(_SEED["egs_state"])
    egs_none["approved_findings"] = None
    agg.update_egs_state(egs_none)
    snap2 = agg.snapshot(timestamp_iso="2026-05-11T00:00:03.000Z")
    assert "approved" not in snap2["active_findings"][0]


def test_snapshot_stamp_does_not_mutate_internal_bucket():
    """LDD-2: aggregator only mutates the deep-copied output, never the
    internal _findings bucket."""
    agg = StateAggregator(max_findings=10, seed_envelope=deepcopy(_SEED))
    agg.add_finding(_finding("f_drone1_005"))
    egs_approved = deepcopy(_SEED["egs_state"])
    egs_approved["approved_findings"] = {"f_drone1_005": "approved"}
    agg.update_egs_state(egs_approved)
    snap1 = agg.snapshot(timestamp_iso="2026-05-11T00:00:02.000Z")
    assert snap1["active_findings"][0]["operator_status"] == "approved"
    egs_clear = deepcopy(_SEED["egs_state"])
    egs_clear["approved_findings"] = {}
    agg.update_egs_state(egs_clear)
    snap2 = agg.snapshot(timestamp_iso="2026-05-11T00:00:03.000Z")
    assert "approved" not in snap2["active_findings"][0]
    assert snap2["active_findings"][0]["operator_status"] == "pending"
