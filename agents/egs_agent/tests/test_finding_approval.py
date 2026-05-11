"""Gate 4 tests — finding_approval consumer, drone_failure replan, standalone tolerance.

Covers TODOS.md:19 (finding_approval branch), Gate 4 pass criteria
(drone_failure replan, standalone tolerance), and the approved_findings
schema extension.
"""
import asyncio
import json
import logging
import pytest

from agents.egs_agent.coordinator import EGSCoordinator
from agents.egs_agent.scenario_state import build_initial_egs_state
from agents.egs_agent.validation import EGSValidationNode
from shared.contracts import validate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def coordinator():
    return EGSCoordinator(EGSValidationNode())


def _base_state(extra_egs=None):
    """Minimal EGSState dict with defaults."""
    egs = {
        "drones_summary": {},
        "approved_findings": {},
    }
    if extra_egs:
        egs.update(extra_egs)
    return {
        "egs_state": egs,
        "incoming_telemetry": [],
        "incoming_findings": [],
        "incoming_commands": [],
        "incoming_actions": [],
        "messages_to_publish": [],
        "trigger_replan": False,
    }


# ---------------------------------------------------------------------------
# 1. finding_approval — approve
# ---------------------------------------------------------------------------

def test_finding_approval_approve_updates_egs_state(coordinator):
    """An 'approve' action on a finding_id writes 'approved' into
    egs_state.approved_findings."""
    state = _base_state()
    state["incoming_actions"] = [
        {
            "kind": "finding_approval",
            "command_id": "fa_001",
            "finding_id": "f_drone1_001",
            "action": "approve",
            "bridge_received_at_iso_ms": "2026-05-11T10:00:00.000Z",
            "contract_version": "1.0.0",
        }
    ]
    new = coordinator.process_actions(state)
    assert new["egs_state"]["approved_findings"]["f_drone1_001"] == "approved"


# ---------------------------------------------------------------------------
# 2. finding_approval — dismiss
# ---------------------------------------------------------------------------

def test_finding_approval_dismiss_updates_egs_state(coordinator):
    """A 'dismiss' action writes 'dismissed' into approved_findings."""
    state = _base_state()
    state["incoming_actions"] = [
        {
            "kind": "finding_approval",
            "command_id": "fa_002",
            "finding_id": "f_drone2_003",
            "action": "dismiss",
            "bridge_received_at_iso_ms": "2026-05-11T10:01:00.000Z",
            "contract_version": "1.0.0",
        }
    ]
    new = coordinator.process_actions(state)
    assert new["egs_state"]["approved_findings"]["f_drone2_003"] == "dismissed"


# ---------------------------------------------------------------------------
# 3. finding_approval — dedup on command_id
# ---------------------------------------------------------------------------

def test_finding_approval_dedup_on_command_id(coordinator, caplog):
    """Replayed finding_approval (same command_id) is silently dropped;
    approved_findings stays at the first write."""
    action = {
        "kind": "finding_approval",
        "command_id": "fa_dup",
        "finding_id": "f_drone1_005",
        "action": "approve",
        "bridge_received_at_iso_ms": "2026-05-11T10:02:00.000Z",
        "contract_version": "1.0.0",
    }
    # First time — should apply.
    state = _base_state()
    state["incoming_actions"] = [action]
    new = coordinator.process_actions(state)
    assert new["egs_state"]["approved_findings"]["f_drone1_005"] == "approved"

    # Second time — same command_id, different action value (dismiss).
    # Should be dropped because command_id already seen.
    action2 = {**action, "action": "dismiss"}
    state2 = {**new, "incoming_actions": [action2]}
    with caplog.at_level(logging.INFO, logger="agents.egs_agent.coordinator"):
        new2 = coordinator.process_actions(state2)
    assert new2["egs_state"]["approved_findings"]["f_drone1_005"] == "approved"
    dup_records = [
        r for r in caplog.records if "duplicate dropped" in r.getMessage()
    ]
    assert len(dup_records) >= 1


# ---------------------------------------------------------------------------
# 4. finding_approval — malformed payload (missing action)
# ---------------------------------------------------------------------------

def test_finding_approval_malformed_is_logged(coordinator, caplog):
    """An action with missing or invalid 'action' field is logged as a
    warning, not added to approved_findings."""
    state = _base_state()
    state["incoming_actions"] = [
        {
            "kind": "finding_approval",
            "command_id": "fa_bad",
            "finding_id": "f_drone1_099",
            "action": "invalid_value",
            "bridge_received_at_iso_ms": "2026-05-11T10:03:00.000Z",
            "contract_version": "1.0.0",
        }
    ]
    with caplog.at_level(logging.WARNING, logger="agents.egs_agent.coordinator"):
        new = coordinator.process_actions(state)
    assert "f_drone1_099" not in new["egs_state"].get("approved_findings", {})
    warn_records = [
        r for r in caplog.records if "malformed" in r.getMessage()
    ]
    assert len(warn_records) >= 1


# ---------------------------------------------------------------------------
# 5. finding_approval — does NOT trigger replan
# ---------------------------------------------------------------------------

def test_finding_approval_does_not_trigger_replan(coordinator):
    """Approving/dismissing a finding should not trigger replan — replan is
    only for zone/drone/command changes."""
    state = _base_state()
    state["incoming_actions"] = [
        {
            "kind": "finding_approval",
            "command_id": "fa_nrp",
            "finding_id": "f_drone1_010",
            "action": "approve",
            "bridge_received_at_iso_ms": "2026-05-11T10:04:00.000Z",
            "contract_version": "1.0.0",
        }
    ]
    new = coordinator.process_actions(state)
    assert new["trigger_replan"] is False


# ---------------------------------------------------------------------------
# 6. finding_approval — mixed batch with operator_command_dispatch
# ---------------------------------------------------------------------------

def test_finding_approval_mixed_with_dispatch(coordinator):
    """Both action kinds can appear in the same batch. Each applies
    independently."""
    state = _base_state(extra_egs={
        "pending_commands": {
            "c99": {"command": "exclude_zone", "args": {"zone_id": "z1"}},
        },
    })
    state["incoming_actions"] = [
        {
            "kind": "finding_approval",
            "command_id": "fa_mix",
            "finding_id": "f_drone1_020",
            "action": "approve",
        },
        {
            "type": "operator_command_dispatch",
            "command_id": "c99",
        },
    ]
    new = coordinator.process_actions(state)
    # Approval recorded.
    assert new["egs_state"]["approved_findings"]["f_drone1_020"] == "approved"
    # Dispatch popped pending_commands and triggered replan (exclude_zone).
    assert "c99" not in new["egs_state"].get("pending_commands", {})
    assert new["trigger_replan"] is True


# ---------------------------------------------------------------------------
# 7. approved_findings in egs_state passes schema validation
# ---------------------------------------------------------------------------

def test_approved_findings_passes_egs_state_schema():
    """The egs_state with approved_findings must validate against Contract 3."""
    egs_state = build_initial_egs_state("disaster_zone_v1")
    egs_state["approved_findings"] = {
        "f_drone1_001": "approved",
        "f_drone2_005": "dismissed",
    }
    outcome = validate("egs_state", egs_state)
    assert outcome.valid, outcome.errors


# ---------------------------------------------------------------------------
# 8. standalone transition triggers replan
# ---------------------------------------------------------------------------

def test_standalone_transition_triggers_replan(coordinator):
    """When a drone transitions from active to standalone, the EGS must
    trigger replan so survey points are redistributed to reachable drones.
    Gate 4 standalone tolerance."""
    state = _base_state(extra_egs={
        "drones_summary": {"drone1": {"status": "active", "battery": 80}},
    })
    state["incoming_telemetry"] = [
        {"drone_id": "drone1", "agent_status": "standalone", "battery_pct": 75},
    ]
    new = coordinator.process_telemetry(state)
    assert new["trigger_replan"] is True
    assert new["egs_state"]["drones_summary"]["drone1"]["status"] == "standalone"


# ---------------------------------------------------------------------------
# 9. standalone → active does NOT trigger replan (already seen)
# ---------------------------------------------------------------------------

def test_standalone_to_active_does_not_double_replan(coordinator):
    """A drone returning from standalone to active should not trigger replan
    if it was already known (prev_status == standalone)."""
    state = _base_state(extra_egs={
        "drones_summary": {"drone1": {"status": "standalone", "battery": 60}},
    })
    state["incoming_telemetry"] = [
        {"drone_id": "drone1", "agent_status": "active", "battery_pct": 55},
    ]
    new = coordinator.process_telemetry(state)
    # standalone → active is a recovery, not an initial appearance — no replan.
    assert new["trigger_replan"] is False


# ---------------------------------------------------------------------------
# 10. drone_failure scripted event injects synthetic offline telemetry
# ---------------------------------------------------------------------------

def test_drone_failure_scripted_event_triggers_replan(coordinator):
    """Simulates the main.py routing: a drone_failure scripted event produces
    synthetic offline telemetry which, when fed through process_telemetry,
    triggers replan. This covers Gate 4 criterion: 'EGS replanning
    successfully reassigns survey points after scripted drone failure event'."""
    # Pre-condition: drone2 is known as active.
    state = _base_state(extra_egs={
        "drones_summary": {"drone2": {"status": "active", "battery": 90}},
    })
    # main.py would inject this synthetic telemetry when it receives:
    #   {"t": 30, "type": "drone_failure", "drone_id": "drone2", ...}
    state["incoming_telemetry"] = [
        {"drone_id": "drone2", "agent_status": "offline", "battery_pct": 0},
    ]
    new = coordinator.process_telemetry(state)
    assert new["trigger_replan"] is True
    assert new["egs_state"]["drones_summary"]["drone2"]["status"] == "offline"


# ---------------------------------------------------------------------------
# 11. standalone drones excluded from replan assignments
# ---------------------------------------------------------------------------

def test_standalone_drone_excluded_from_replan_assignments():
    """replanning.assign_survey_points only considers active drones. A
    standalone drone must not receive new assignments (it can't receive
    Redis task messages)."""
    from agents.egs_agent.replanning import assign_survey_points as _assign
    from shared.contracts import AdapterError
    from unittest.mock import AsyncMock, patch, MagicMock

    egs_state = {
        "drones_summary": {
            "drone1": {"status": "active", "battery": 80},
            "drone2": {"status": "standalone", "battery": 60},
        },
        "survey_points": [
            {"id": "sp_001", "lat": 34.0, "lon": -118.5, "status": "unassigned"},
            {"id": "sp_002", "lat": 34.01, "lon": -118.5, "status": "unassigned"},
        ],
    }

    async def run():
        # Make the LLM call fail with AdapterError so retries exhaust and
        # the function falls through to the deterministic round-robin.
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"bad": "json"}

        with patch("agents.egs_agent.replanning.normalize", side_effect=AdapterError("test")):
            with patch("agents.egs_agent.replanning.httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.post = AsyncMock(return_value=mock_response)
                mock_cls.return_value = mock_client
                result = await _assign(egs_state, EGSValidationNode())

        # Fallback only assigns to active drones.
        assert result, "expected fallback assignment"
        assignments = result.get("arguments", {}).get("assignments", [])
        assigned_drone_ids = [a["drone_id"] for a in assignments]
        assert "drone2" not in assigned_drone_ids, (
            f"standalone drone2 should not receive assignments: {assignments}"
        )
        # All points should go to drone1.
        total_pts = sum(len(a["survey_point_ids"]) for a in assignments)
        assert total_pts == 2

    asyncio.run(run())


# ---------------------------------------------------------------------------
# 12. approved_findings empty dict validates (backward compat)
# ---------------------------------------------------------------------------

def test_approved_findings_empty_dict_validates():
    """An empty approved_findings dict must be valid (initial state)."""
    egs_state = build_initial_egs_state("disaster_zone_v1")
    assert egs_state["approved_findings"] == {}
    outcome = validate("egs_state", egs_state)
    assert outcome.valid, outcome.errors


# ---------------------------------------------------------------------------
# 13. finding_approval — TTL evicts stale command_ids (defensive bound)
# ---------------------------------------------------------------------------

def test_approval_dedup_ttl_evicts_stale_command_ids(coordinator, monkeypatch):
    """Without TTL eviction the dedup set leaks linearly. Monkeypatch the TTL
    down to make the test fast."""
    from agents.egs_agent import coordinator as coord_mod
    monkeypatch.setattr(coord_mod, "SEEN_FINDING_ID_TTL_S", 0.001)
    # First action with command_id "c1" lands.
    state = _base_state()
    state["incoming_actions"] = [
        {"kind": "finding_approval", "command_id": "c1",
         "finding_id": "f_drone1_001", "action": "approve"},
    ]
    coordinator.process_actions(state)
    assert "c1" in coordinator._seen_approval_command_id_set
    # Sleep past TTL.
    import time
    time.sleep(0.05)
    # Next process_actions call's TTL sweep must evict c1.
    state["incoming_actions"] = [
        {"kind": "finding_approval", "command_id": "c2",
         "finding_id": "f_drone1_002", "action": "approve"},
    ]
    coordinator.process_actions(state)
    assert "c1" not in coordinator._seen_approval_command_id_set
    assert "c2" in coordinator._seen_approval_command_id_set


# ---------------------------------------------------------------------------
# 14. approved_findings cap evicts oldest FIFO entry (defensive bound)
# ---------------------------------------------------------------------------

def test_approved_findings_cap_evicts_oldest_fifo(coordinator, monkeypatch):
    """Cap kicks in at MAX_APPROVED_FINDINGS; oldest-inserted entry evicts."""
    from agents.egs_agent import coordinator as coord_mod
    monkeypatch.setattr(coord_mod, "MAX_APPROVED_FINDINGS", 3)
    state = _base_state()
    # Fill the cap.
    state["incoming_actions"] = [
        {"kind": "finding_approval", "command_id": f"c-{i}",
         "finding_id": f"f_drone1_{i:03d}", "action": "approve"}
        for i in range(3)
    ]
    coordinator.process_actions(state)
    assert set(state["egs_state"]["approved_findings"].keys()) == {
        "f_drone1_000", "f_drone1_001", "f_drone1_002",
    }
    # 4th unique finding evicts the oldest (f_drone1_000).
    state["incoming_actions"] = [
        {"kind": "finding_approval", "command_id": "c-3",
         "finding_id": "f_drone1_003", "action": "approve"},
    ]
    coordinator.process_actions(state)
    assert set(state["egs_state"]["approved_findings"].keys()) == {
        "f_drone1_001", "f_drone1_002", "f_drone1_003",
    }


# ---------------------------------------------------------------------------
# 15. approved_findings cap does NOT evict on rewrite/flip (defensive bound)
# ---------------------------------------------------------------------------

def test_approved_findings_cap_does_not_evict_on_rewrite(
    coordinator, monkeypatch,
):
    """Re-approving an already-recorded finding (or flipping approve↔dismiss)
    must NOT trigger eviction — it's a rewrite, not a new entry."""
    from agents.egs_agent import coordinator as coord_mod
    monkeypatch.setattr(coord_mod, "MAX_APPROVED_FINDINGS", 2)
    state = _base_state()
    state["incoming_actions"] = [
        {"kind": "finding_approval", "command_id": "c-a",
         "finding_id": "f_drone1_A", "action": "approve"},
        {"kind": "finding_approval", "command_id": "c-b",
         "finding_id": "f_drone1_B", "action": "approve"},
    ]
    coordinator.process_actions(state)
    # Flip f_drone1_A from approve to dismiss — should NOT evict f_drone1_B.
    state["incoming_actions"] = [
        {"kind": "finding_approval", "command_id": "c-a2",
         "finding_id": "f_drone1_A", "action": "dismiss"},
    ]
    coordinator.process_actions(state)
    assert set(state["egs_state"]["approved_findings"].keys()) == {
        "f_drone1_A", "f_drone1_B",
    }
    assert state["egs_state"]["approved_findings"]["f_drone1_A"] == "dismissed"


# ---------------------------------------------------------------------------
# 16. approved_findings cap evicts FIFO order under sustained pressure
# ---------------------------------------------------------------------------

def test_approved_findings_cap_evicts_in_fifo_order_under_sustained_pressure(
    coordinator, monkeypatch,
):
    """Multi-eviction regression: cap=3, then add 5 unique findings one at a
    time. After each add past the cap, the OLDEST surviving entry must
    evict next — not a random or stack-order victim. Asserts the
    `next(iter(approved))` insertion-order guarantee holds across
    multiple evictions, not just one."""
    from agents.egs_agent import coordinator as coord_mod
    monkeypatch.setattr(coord_mod, "MAX_APPROVED_FINDINGS", 3)
    state = _base_state()
    expected_after = [
        # After adding f_drone1_000: {000}
        {"f_drone1_000"},
        # After adding f_drone1_001: {000, 001}
        {"f_drone1_000", "f_drone1_001"},
        # After adding f_drone1_002: {000, 001, 002} (cap reached)
        {"f_drone1_000", "f_drone1_001", "f_drone1_002"},
        # After adding f_drone1_003: 000 evicts → {001, 002, 003}
        {"f_drone1_001", "f_drone1_002", "f_drone1_003"},
        # After adding f_drone1_004: 001 evicts → {002, 003, 004}
        {"f_drone1_002", "f_drone1_003", "f_drone1_004"},
    ]
    for i, expected in enumerate(expected_after):
        state["incoming_actions"] = [
            {"kind": "finding_approval", "command_id": f"c-{i}",
             "finding_id": f"f_drone1_{i:03d}", "action": "approve"},
        ]
        coordinator.process_actions(state)
        assert set(state["egs_state"]["approved_findings"].keys()) == expected, (
            f"after add #{i} expected {expected} got "
            f"{set(state['egs_state']['approved_findings'].keys())}"
        )


# ---------------------------------------------------------------------------
# 17. approved_findings cap does NOT evict on idempotent same-action re-approve
# ---------------------------------------------------------------------------

def test_approved_findings_cap_does_not_evict_on_idempotent_same_action(
    coordinator, monkeypatch,
):
    """Idempotency under cap pressure: cap=2, fill it, then re-approve an
    already-approved finding with a fresh command_id. The cap must not
    fire (no new entry is being added), and the older non-rewritten
    finding must remain in the map. Symmetric counterpart to
    `test_approved_findings_cap_does_not_evict_on_rewrite` which covers
    approve↔dismiss flips."""
    from agents.egs_agent import coordinator as coord_mod
    monkeypatch.setattr(coord_mod, "MAX_APPROVED_FINDINGS", 2)
    state = _base_state()
    state["incoming_actions"] = [
        {"kind": "finding_approval", "command_id": "c-x",
         "finding_id": "f_drone1_X", "action": "approve"},
        {"kind": "finding_approval", "command_id": "c-y",
         "finding_id": "f_drone1_Y", "action": "approve"},
    ]
    coordinator.process_actions(state)
    # Re-approve X with a fresh cmd_id. Should be a no-op write (idempotent),
    # NOT trigger eviction of Y.
    state["incoming_actions"] = [
        {"kind": "finding_approval", "command_id": "c-x2",
         "finding_id": "f_drone1_X", "action": "approve"},
    ]
    coordinator.process_actions(state)
    assert set(state["egs_state"]["approved_findings"].keys()) == {
        "f_drone1_X", "f_drone1_Y",
    }
    assert state["egs_state"]["approved_findings"]["f_drone1_X"] == "approved"
    assert state["egs_state"]["approved_findings"]["f_drone1_Y"] == "approved"
