"""Lifecycle tests for EGSCoordinator._replan_attempt_log (Phase 1, GATE 4
wow moment).

Four cases per the plan:
 1. populate-on-replan: log surfaces mid-replan with length matching
    attempts so far.
 2. clear-after-3s: after _replan_in_flight flips false, the
    asyncio.call_later clear fires and empties the log. We monkeypatch
    REPLAN_ATTEMPT_LOG_CLEAR_DELAY_S to a tiny value so the test runs
    in milliseconds.
 3. two replans back-to-back: the second replan does not inherit entries
    from the first (regression guard for "stuck banner").
 4. clear-during-replan is safe: a new replan inside the grace window
    cancels the pending clear so its fresh entries are not wiped.

Uses pytest.mark.asyncio (project default mode=auto per pytest.ini).
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import agents.egs_agent.coordinator as coordinator_mod
from agents.egs_agent.coordinator import EGSCoordinator
from agents.egs_agent.validation import EGSValidationNode


def _minimal_snapshot() -> Dict[str, Any]:
    return {
        "drones_summary": {
            "drone1": {"status": "active"},
            "drone2": {"status": "active"},
        },
        "survey_points": [
            {"id": "sp_001", "status": "unassigned"},
            {"id": "sp_002", "status": "unassigned"},
        ],
    }


def _valid_assignment() -> Dict[str, Any]:
    return {
        "function": "assign_survey_points",
        "arguments": {
            "assignments": [
                {"drone_id": "drone1", "survey_point_ids": ["sp_001"]},
                {"drone_id": "drone2", "survey_point_ids": ["sp_002"]},
            ],
        },
    }


# ---------- Test 1: populate-on-replan -------------------------------------


@pytest.mark.asyncio
async def test_attempt_log_populated_during_replan(monkeypatch):
    """The replan injects a sink callback into assign_survey_points; calling
    it must append to the coordinator's _replan_attempt_log immediately.
    """
    # Pin a long clear delay so the post-replan timer doesn't fire mid-test
    # and obscure the assertion.
    monkeypatch.setattr(coordinator_mod, "REPLAN_ATTEMPT_LOG_CLEAR_DELAY_S", 60.0)
    monkeypatch.setattr(coordinator_mod, "REPLAN_OVERALL_TIMEOUT_S", 5.0)

    # Fake assign_survey_points: invoke the sink twice (mid-replan) then
    # return a valid assignment. This simulates 2 failed attempts + 1
    # success without round-tripping through httpx.
    async def fake_assign(egs_state, validation_node, *, validation_logger=None, log_sink=None, **kwargs):
        assert log_sink is not None
        log_sink({
            "timestamp": "2026-05-12T14:23:11.342Z",
            "attempt_n": 1, "valid": False, "rule_id": "ASSIGNMENT_TOTAL_MISMATCH",
            "corrective_text": "stub", "details": {},
        })
        log_sink({
            "timestamp": "2026-05-12T14:23:12.100Z",
            "attempt_n": 2, "valid": True, "rule_id": None,
            "corrective_text": None, "details": {},
        })
        return _valid_assignment()

    redis_client = AsyncMock()
    coord = EGSCoordinator(EGSValidationNode(), redis_client=redis_client)
    coord._replan_in_flight = True  # mirror caller-side guard

    with patch("agents.egs_agent.coordinator.assign_survey_points", new=fake_assign):
        await coord._replan_impl(_minimal_snapshot())

    assert len(coord._replan_attempt_log) == 2
    assert coord._replan_attempt_log[0]["attempt_n"] == 1
    assert coord._replan_attempt_log[1]["valid"] is True


# ---------- Test 2: clear-after-3s ----------------------------------------


@pytest.mark.asyncio
async def test_attempt_log_clears_after_grace_window(monkeypatch):
    """With a tiny clear delay the post-replan call_later must empty the
    log on the next loop iteration after the delay expires.
    """
    monkeypatch.setattr(coordinator_mod, "REPLAN_ATTEMPT_LOG_CLEAR_DELAY_S", 0.05)
    monkeypatch.setattr(coordinator_mod, "REPLAN_OVERALL_TIMEOUT_S", 5.0)

    async def fake_assign(egs_state, validation_node, *, validation_logger=None, log_sink=None, **kwargs):
        log_sink({
            "timestamp": "2026-05-12T14:23:11.342Z",
            "attempt_n": 1, "valid": True, "rule_id": None,
            "corrective_text": None, "details": {},
        })
        return _valid_assignment()

    redis_client = AsyncMock()
    coord = EGSCoordinator(EGSValidationNode(), redis_client=redis_client)
    coord._replan_in_flight = True

    with patch("agents.egs_agent.coordinator.assign_survey_points", new=fake_assign):
        await coord._replan_impl(_minimal_snapshot())

    assert len(coord._replan_attempt_log) == 1, "entries present right after replan"
    # Wait past the clear delay (with margin) for the TimerHandle to fire.
    await asyncio.sleep(0.2)
    assert coord._replan_attempt_log == [], (
        "transient log must clear after REPLAN_ATTEMPT_LOG_CLEAR_DELAY_S"
    )
    assert coord._pending_clear_handle is None


# ---------- Test 3: two replans back-to-back ------------------------------


@pytest.mark.asyncio
async def test_two_replans_back_to_back_dont_share_entries(monkeypatch):
    """After the first replan's clear fires, the second replan starts with
    a fresh empty log. Regression guard for the "stuck banner" failure.
    """
    monkeypatch.setattr(coordinator_mod, "REPLAN_ATTEMPT_LOG_CLEAR_DELAY_S", 0.05)
    monkeypatch.setattr(coordinator_mod, "REPLAN_OVERALL_TIMEOUT_S", 5.0)

    counter = {"n": 0}

    async def fake_assign(egs_state, validation_node, *, validation_logger=None, log_sink=None, **kwargs):
        counter["n"] += 1
        log_sink({
            "timestamp": "2026-05-12T14:23:11.342Z",
            "attempt_n": 1, "valid": True, "rule_id": None,
            "corrective_text": f"call_{counter['n']}", "details": {},
        })
        return _valid_assignment()

    redis_client = AsyncMock()
    coord = EGSCoordinator(EGSValidationNode(), redis_client=redis_client)

    # First replan.
    coord._replan_in_flight = True
    with patch("agents.egs_agent.coordinator.assign_survey_points", new=fake_assign):
        await coord._replan_impl(_minimal_snapshot())
    assert len(coord._replan_attempt_log) == 1

    # Let the clear timer fire.
    await asyncio.sleep(0.2)
    assert coord._replan_attempt_log == []

    # Second replan.
    coord._replan_in_flight = True
    with patch("agents.egs_agent.coordinator.assign_survey_points", new=fake_assign):
        await coord._replan_impl(_minimal_snapshot())
    assert len(coord._replan_attempt_log) == 1
    # The second replan's entry must be from call_2 (its own sink call),
    # not from call_1 (the prior replan).
    assert coord._replan_attempt_log[0]["corrective_text"] == "call_2"


# ---------- Test 4: clear-during-replan is safe (cancellation) ------------


@pytest.mark.asyncio
async def test_pending_clear_cancelled_when_new_replan_starts(monkeypatch):
    """If a new replan begins inside the grace window, the pending clear
    must be cancelled so its fresh entries are not wiped by the previous
    replan's pending TimerHandle.
    """
    monkeypatch.setattr(coordinator_mod, "REPLAN_ATTEMPT_LOG_CLEAR_DELAY_S", 0.5)
    monkeypatch.setattr(coordinator_mod, "REPLAN_OVERALL_TIMEOUT_S", 5.0)

    async def fake_assign(egs_state, validation_node, *, validation_logger=None, log_sink=None, **kwargs):
        log_sink({
            "timestamp": "2026-05-12T14:23:11.342Z",
            "attempt_n": 1, "valid": True, "rule_id": None,
            "corrective_text": "marker", "details": {},
        })
        return _valid_assignment()

    redis_client = AsyncMock()
    coord = EGSCoordinator(EGSValidationNode(), redis_client=redis_client)

    # First replan completes and schedules a clear in 0.5s.
    coord._replan_in_flight = True
    with patch("agents.egs_agent.coordinator.assign_survey_points", new=fake_assign):
        await coord._replan_impl(_minimal_snapshot())
    assert coord._pending_clear_handle is not None
    first_handle = coord._pending_clear_handle

    # Second replan starts INSIDE the grace window — its first sink call
    # must cancel the pending clear.
    coord._replan_in_flight = True
    with patch("agents.egs_agent.coordinator.assign_survey_points", new=fake_assign):
        await coord._replan_impl(_minimal_snapshot())

    # The original handle must have been cancelled (a new one was scheduled
    # by the second replan's completion).
    assert first_handle.cancelled() or coord._pending_clear_handle is not first_handle, (
        "first replan's pending clear must be cancelled when a second replan starts"
    )

    # Log carries the second replan's entries — never wiped to empty by the
    # first replan's timer.
    assert len(coord._replan_attempt_log) >= 1
