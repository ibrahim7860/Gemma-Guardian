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
