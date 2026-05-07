"""Tests for Task 3: initial-replan-on-first-active-telemetry + fire-and-forget replan."""
from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.egs_agent.coordinator import EGSCoordinator
from agents.egs_agent.scenario_state import build_initial_egs_state
from agents.egs_agent.validation import EGSValidationNode


def _telemetry(drone_id: str, status: str = "active", battery: float = 95.0,
               ts: str = "2026-05-07T10:00:00.000Z"):
    return {
        "drone_id": drone_id,
        "agent_status": status,
        "battery_pct": battery,
        "timestamp": ts,
    }


def _empty_state(egs_state):
    return {
        "egs_state": egs_state,
        "incoming_telemetry": [],
        "incoming_findings": [],
        "incoming_commands": [],
        "messages_to_publish": [],
        "trigger_replan": False,
    }


def test_first_telemetry_active_triggers_replan():
    """absent -> active is the new initial-replan trigger."""
    coord = EGSCoordinator(EGSValidationNode())
    state = _empty_state({"drones_summary": {}})
    state["incoming_telemetry"] = [_telemetry("drone1", "active")]

    new_state = coord.process_telemetry(state)

    assert new_state["trigger_replan"] is True
    assert new_state["egs_state"]["drones_summary"]["drone1"]["status"] == "active"


def test_subsequent_active_telemetry_does_not_retrigger():
    """active -> active is a no-op for trigger_replan."""
    coord = EGSCoordinator(EGSValidationNode())
    state = _empty_state({
        "drones_summary": {"drone1": {"status": "active", "battery": 90, "last_seen": "earlier"}}
    })
    state["incoming_telemetry"] = [_telemetry("drone1", "active")]

    new_state = coord.process_telemetry(state)

    assert new_state["trigger_replan"] is False


def test_active_to_offline_still_triggers_replan():
    """Regression: the existing path active -> offline still flips trigger_replan."""
    coord = EGSCoordinator(EGSValidationNode())
    state = _empty_state({
        "drones_summary": {"drone1": {"status": "active", "battery": 90, "last_seen": "earlier"}}
    })
    state["incoming_telemetry"] = [_telemetry("drone1", "offline", battery=0)]

    new_state = coord.process_telemetry(state)

    assert new_state["trigger_replan"] is True
    assert new_state["egs_state"]["drones_summary"]["drone1"]["status"] == "offline"


def test_full_graph_first_active_publishes_task_via_background():
    """T-GAP-1: critical regression-adjacent — first-active telemetry produces
    per-drone task publishes via the fire-and-forget background task without
    blocking the graph tick."""
    async def run():
        fake_redis = AsyncMock()
        validation_node = EGSValidationNode()
        coord = EGSCoordinator(validation_node, redis_client=fake_redis)

        mock_assignment = {
            "function": "assign_survey_points",
            "arguments": {
                "assignments": [
                    {"drone_id": "drone1", "survey_point_ids": ["sp_001"]},
                    {"drone_id": "drone2", "survey_point_ids": ["sp_002"]},
                ]
            },
        }

        egs_state = build_initial_egs_state("disaster_zone_v1")
        state = _empty_state(egs_state)
        state["incoming_telemetry"] = [_telemetry("drone1", "active")]

        with patch(
            "agents.egs_agent.coordinator.assign_survey_points",
            new=AsyncMock(return_value=mock_assignment),
        ):
            t0 = time.perf_counter()
            new_state = await coord.graph.ainvoke(state)
            elapsed = time.perf_counter() - t0

            # (a) The graph tick itself returns quickly because replan is fire-and-forget.
            # 500ms is loose enough to be reliable on a busy CI box.
            assert elapsed < 0.5, f"graph.ainvoke blocked for {elapsed:.3f}s"
            assert new_state["trigger_replan"] is False

            # (b) Allow the background task to finish.
            await asyncio.sleep(0.1)

        # (c) Both drone task channels were published with survey-task payloads.
        # Plus a loop-back on egs.replan_events for the survey-points status
        # mutation. Total: 3 publishes (2 drone tasks + 1 loop-back).
        assert fake_redis.publish.await_count >= 3
        published = {
            call.args[0]: json.loads(call.args[1])
            for call in fake_redis.publish.await_args_list
        }
        assert "drones.drone1.tasks" in published
        assert "drones.drone2.tasks" in published
        assert "egs.replan_events" in published
        for ch in ("drones.drone1.tasks", "drones.drone2.tasks"):
            payload = published[ch]
            assert payload["task_type"] == "survey"
            assert payload["drone_id"] in ("drone1", "drone2")
        loopback = published["egs.replan_events"]
        assert loopback["type"] == "survey_assignments"

    asyncio.run(run())


def test_replan_reentrancy_guard_skips_concurrent_calls():
    """Two replan calls in flight: the second one must short-circuit and not
    spawn an additional background task."""
    async def run():
        coord = EGSCoordinator(EGSValidationNode(), redis_client=AsyncMock())
        state = _empty_state(build_initial_egs_state("disaster_zone_v1"))
        # Pretend a replan is already running.
        coord._replan_in_flight = True

        # When patching `asyncio.create_task`, any coroutine handed to the
        # mock would otherwise be GC'd unawaited and trigger
        # `RuntimeWarning: coroutine '_replan_impl' was never awaited`. The
        # side_effect closes the coroutine so the mock observes the call but
        # the coroutine resource is released cleanly.
        def _close_coro(coro, *args, **kwargs):
            coro.close()
            return MagicMock()

        with patch(
            "agents.egs_agent.coordinator.asyncio.create_task",
            side_effect=_close_coro,
        ) as mock_create_task:
            await coord.replan(state)
            await coord.replan(state)
            assert mock_create_task.call_count == 0, (
                "expected re-entrancy guard to skip create_task while in-flight"
            )

        # Now release the guard and confirm a single call would spawn one task.
        coord._replan_in_flight = False
        with patch(
            "agents.egs_agent.coordinator.asyncio.create_task",
            side_effect=_close_coro,
        ) as mock_create_task:
            await coord.replan(state)
            assert mock_create_task.call_count == 1

    asyncio.run(run())


def test_replan_reentrancy_guard_holds_across_back_to_back_calls_without_mocking_create_task():
    """Real race-condition test: call coord.replan() twice in quick succession
    WITHOUT patching asyncio.create_task. The flag must be set synchronously
    inside replan() so that the second call's guard fires.

    The previous test (`test_replan_reentrancy_guard_skips_concurrent_calls`)
    patched create_task and only proved the in-flight read works under that
    mock. This test proves the SET happens in the right place.
    """
    async def run():
        coord = EGSCoordinator(EGSValidationNode(), redis_client=AsyncMock())
        # Slow-roll the LLM so _replan_impl awaits long enough for us to
        # fire the second replan() call before _replan_impl even starts.
        slow_event = asyncio.Event()

        async def slow_assign(*args, **kwargs):
            await slow_event.wait()
            return {"function": "assign_survey_points", "arguments": {"assignments": []}}

        with patch("agents.egs_agent.coordinator.assign_survey_points", new=slow_assign):
            state = _empty_state({"drones_summary": {}})
            # First replan: should set in_flight=True synchronously and spawn task.
            r1 = await coord.replan(state)
            assert r1["trigger_replan"] is False
            assert coord._replan_in_flight is True, (
                "in_flight must be set synchronously inside replan() to gate "
                "the next call before _replan_impl gets a chance to run"
            )
            # Second replan immediately: should hit the guard, NOT spawn a 2nd task.
            r2 = await coord.replan(state)
            assert r2["trigger_replan"] is False
            # Release the slow assign so the background task can finish.
            slow_event.set()
            # Give the loop a moment to drain.
            await asyncio.sleep(0.05)
            assert coord._replan_in_flight is False, (
                "in_flight must be cleared in _replan_impl's finally block"
            )

    asyncio.run(run())


def test_replan_impl_publishes_survey_assignments_loopback():
    """After publishing per-drone tasks, _replan_impl must also publish a
    {type: 'survey_assignments', ...} envelope on egs.replan_events so the
    main loop can flip survey_points[*].status from 'unassigned' to 'assigned'.
    """
    async def run():
        fake_redis = AsyncMock()
        coord = EGSCoordinator(EGSValidationNode(), redis_client=fake_redis)
        with patch("agents.egs_agent.coordinator.assign_survey_points",
                   new=AsyncMock(return_value={
                       "function": "assign_survey_points",
                       "arguments": {"assignments": [
                           {"drone_id": "drone1", "survey_point_ids": ["sp_001", "sp_002"]},
                           {"drone_id": "drone2", "survey_point_ids": ["sp_010"]},
                       ]},
                   })):
            await coord._replan_impl({"survey_points": [], "drones_summary": {}})
        # 2 drone task publishes + 1 loop-back publish
        assert fake_redis.publish.await_count == 3
        loopback_call = fake_redis.publish.await_args_list[-1]
        assert loopback_call.args[0] == "egs.replan_events"
        envelope = json.loads(loopback_call.args[1])
        assert envelope["type"] == "survey_assignments"
        assert {a["drone_id"] for a in envelope["assignments"]} == {"drone1", "drone2"}
        assert "issued_at" in envelope
    asyncio.run(run())


def test_apply_survey_assignments_flips_status_and_assigned_to():
    """The main.py-side handler mutates survey_points entries in place."""
    from agents.egs_agent.main import _apply_survey_assignments
    egs_state = {
        "survey_points": [
            {"id": "sp_001", "lat": 0, "lon": 0, "assigned_to": None, "status": "unassigned"},
            {"id": "sp_002", "lat": 0, "lon": 0, "assigned_to": None, "status": "unassigned"},
            {"id": "sp_010", "lat": 0, "lon": 0, "assigned_to": None, "status": "unassigned"},
            {"id": "sp_999", "lat": 0, "lon": 0, "assigned_to": None, "status": "unassigned"},
        ],
    }
    _apply_survey_assignments(egs_state, [
        {"drone_id": "drone1", "survey_point_ids": ["sp_001", "sp_002"]},
        {"drone_id": "drone2", "survey_point_ids": ["sp_010"]},
    ])
    by_id = {p["id"]: p for p in egs_state["survey_points"]}
    assert by_id["sp_001"]["status"] == "assigned"
    assert by_id["sp_001"]["assigned_to"] == "drone1"
    assert by_id["sp_002"]["assigned_to"] == "drone1"
    assert by_id["sp_010"]["assigned_to"] == "drone2"
    # Untouched point left alone.
    assert by_id["sp_999"]["status"] == "unassigned"
    assert by_id["sp_999"]["assigned_to"] is None
