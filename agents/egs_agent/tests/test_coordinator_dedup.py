"""Wave 3a (Component 4) — finding_id deduplication in EGSCoordinator.

A drone-side buffer (Wave 1 Lane A) replays buffered findings on link
restore. Without dedup, the EGS would double-increment
``findings_count_by_type`` for any finding that briefly straddled the
restore boundary. These tests pin the dedup contract:

  * first time we see a finding_id, it counts;
  * subsequent times within ``SEEN_FINDING_ID_TTL_S``, it is logged and
    silently dropped;
  * after the TTL expires, the same finding_id can count again (the deque
    actually evicts — no memory leak);
  * the deque (FIFO eviction) and the membership set (O(1) lookup) stay
    invariantly synchronized;
  * eviction is FIFO — the oldest expired entries leave first, newer
    entries that haven't expired yet stay.
"""
from __future__ import annotations

import logging
from typing import Any

import pytest

from agents.egs_agent import coordinator as coordinator_module
from agents.egs_agent.coordinator import (
    EGSCoordinator,
    SEEN_FINDING_ID_TTL_S,
)
from agents.egs_agent.validation import EGSValidationNode


def _finding(
    fid: str,
    drone_id: str = "drone1",
    ftype: str = "victim",
    lat: float = 34.0,
    lon: float = -118.0,
    ts: str = "2026-05-15T14:00:00.000Z",
) -> dict[str, Any]:
    """Minimal Contract-4-shaped finding (mirrors the helper in
    `test_main_findings_count_increment.py` but stripped to the fields
    the validator and coordinator inspect)."""
    return {
        "finding_id": fid,
        "source_drone_id": drone_id,
        "timestamp": ts,
        "type": ftype,
        "severity": 3,
        "gps_lat": lat,
        "gps_lon": lon,
        "altitude": 25.0,
        "confidence": 0.85,
        "visual_description": "Test fixture finding for dedup coverage.",
        "image_path": "/tmp/findings/test.jpg",
        "validated": True,
        "validation_retries": 0,
        "operator_status": "pending",
    }


def _empty_state(egs_state: dict | None = None) -> dict:
    return {
        "egs_state": egs_state or {},
        "incoming_telemetry": [],
        "incoming_findings": [],
        "incoming_commands": [],
        "messages_to_publish": [],
        "trigger_replan": False,
    }


@pytest.fixture
def coord() -> EGSCoordinator:
    return EGSCoordinator(EGSValidationNode())


def test_first_finding_increments(coord: EGSCoordinator) -> None:
    state = _empty_state()
    state["incoming_findings"] = [_finding("f_drone1_001", ftype="victim")]
    new_state = coord.process_findings(state)
    assert new_state["egs_state"]["findings_count_by_type"]["victim"] == 1


def test_duplicate_finding_id_does_not_increment(
    coord: EGSCoordinator, caplog: pytest.LogCaptureFixture,
) -> None:
    """Same finding_id pushed twice → counts increment by 1 total. The
    duplicate fires the "duplicate dropped" info log."""
    caplog.set_level(logging.INFO, logger=coordinator_module.__name__)

    first = _empty_state()
    first["incoming_findings"] = [_finding("f_drone1_042", ftype="fire")]
    after_first = coord.process_findings(first)

    second = _empty_state(after_first["egs_state"])
    second["incoming_findings"] = [_finding("f_drone1_042", ftype="fire")]
    new_state = coord.process_findings(second)

    assert new_state["egs_state"]["findings_count_by_type"]["fire"] == 1
    # Dedup log fired exactly once for the duplicate finding_id.
    dup_logs = [
        r for r in caplog.records
        if "egs.findings duplicate dropped" in r.getMessage()
        and "f_drone1_042" in r.getMessage()
    ]
    assert len(dup_logs) == 1, (
        f"expected exactly 1 duplicate-dropped log line for f_drone1_042; "
        f"saw {len(dup_logs)}: {[r.getMessage() for r in dup_logs]}"
    )


def test_duplicate_after_ttl_expires_re_increments(
    coord: EGSCoordinator, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same finding_id at t=0 and at t > TTL → both count.

    Verifies the deque is actually evicting (no memory leak; no
    permanent block on legitimate re-issued IDs)."""
    fake_now = {"t": 1_000_000.0}

    def _mock_time() -> float:
        return fake_now["t"]

    monkeypatch.setattr(coordinator_module.time, "time", _mock_time)

    first = _empty_state()
    first["incoming_findings"] = [_finding("f_drone1_777", ftype="smoke")]
    after_first = coord.process_findings(first)
    assert (
        coord._findings_accepted_total == 1
    ), "first insert should count"
    assert "f_drone1_777" in coord._seen_finding_id_set

    # Advance past the TTL boundary.
    fake_now["t"] += SEEN_FINDING_ID_TTL_S + 100.0  # 400s past insert

    second = _empty_state(after_first["egs_state"])
    second["incoming_findings"] = [_finding("f_drone1_777", ftype="smoke")]
    new_state = coord.process_findings(second)

    assert new_state["egs_state"]["findings_count_by_type"]["smoke"] == 2
    assert coord._findings_accepted_total == 2
    # After re-insert, the id should still be in the set (newly added).
    assert "f_drone1_777" in coord._seen_finding_id_set
    # And the deque should have exactly 1 entry — the old one evicted, the
    # new one appended.
    assert len(coord._seen_finding_ids) == 1


def test_dedup_set_and_deque_stay_synchronized(
    coord: EGSCoordinator, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After a series of inserts and TTL evictions, the membership set's
    contents must equal the set of finding_ids in the deque. Light
    invariant check — guards against future refactors that update one
    structure but forget the other."""
    fake_now = {"t": 5_000_000.0}
    monkeypatch.setattr(coordinator_module.time, "time", lambda: fake_now["t"])

    # Insert 3 findings at distinct timestamps.
    for i, fid in enumerate(["a", "b", "c"]):
        fake_now["t"] += 10.0
        state = _empty_state()
        state["incoming_findings"] = [_finding(f"f_drone1_{fid}")]
        coord.process_findings(state)

    # Sanity: invariant before any eviction.
    deque_ids = {fid for fid, _ in coord._seen_finding_ids}
    assert deque_ids == coord._seen_finding_id_set
    assert deque_ids == {"f_drone1_a", "f_drone1_b", "f_drone1_c"}

    # Advance time so the first two entries expire (they are 10s and 20s
    # before the third; TTL is 300s; jump 350s past the third's timestamp
    # to make all of them expire).
    fake_now["t"] += SEEN_FINDING_ID_TTL_S + 50.0

    # Process an empty findings tick to trigger the eviction sweep at the
    # head of process_findings.
    coord.process_findings(_empty_state())

    deque_ids = {fid for fid, _ in coord._seen_finding_ids}
    assert deque_ids == coord._seen_finding_id_set
    assert deque_ids == set(), (
        f"all 3 entries should have evicted past TTL; "
        f"deque={list(coord._seen_finding_ids)} set={coord._seen_finding_id_set}"
    )


def test_eviction_is_fifo(
    coord: EGSCoordinator, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Insert 5 findings at strictly increasing timestamps. Advance time
    so the oldest 3 are past TTL while the newest 2 are still fresh.
    Expect exactly 3 evictions (the oldest), leaving the 2 newest in the
    deque + set."""
    fake_now = {"t": 8_000_000.0}
    monkeypatch.setattr(coordinator_module.time, "time", lambda: fake_now["t"])

    # Insert 5 findings with a 30-s gap. Total span 150s — well inside
    # the 300s TTL — so all 5 still live after the inserts.
    state_step = 30.0
    timestamps = []
    egs_state: dict = {}
    for i in range(5):
        fake_now["t"] += state_step
        timestamps.append(fake_now["t"])
        state = _empty_state(egs_state)
        state["incoming_findings"] = [_finding(f"f_drone1_{i}", ftype="victim")]
        result = coord.process_findings(state)
        egs_state = result["egs_state"]

    assert len(coord._seen_finding_ids) == 5
    assert coord._seen_finding_id_set == {
        f"f_drone1_{i}" for i in range(5)
    }

    # Now jump time so that timestamps[0..2] (the oldest 3) are past TTL
    # but timestamps[3..4] (the newest 2) are still within TTL.
    # entries[2] sits at timestamps[2]; entries[3] sits at timestamps[2]+30s.
    # Advance to timestamps[2] + TTL + 1 → timestamps[2] is exactly TTL+1 old
    # (evicted), timestamps[3] is TTL-29 old (kept), timestamps[4] is
    # TTL-59 old (kept).
    fake_now["t"] = timestamps[2] + SEEN_FINDING_ID_TTL_S + 1.0

    coord.process_findings(_empty_state(egs_state))

    survivors = {fid for fid, _ in coord._seen_finding_ids}
    assert survivors == {"f_drone1_3", "f_drone1_4"}, (
        f"expected the two newest to survive; got {survivors}"
    )
    assert coord._seen_finding_id_set == survivors
