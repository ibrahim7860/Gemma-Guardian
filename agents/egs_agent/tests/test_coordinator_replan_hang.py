"""GH #32 / Bug 3 regression: replan in-flight guard must clear on hang.

Pre-fix, `_replan_impl` awaited `assign_survey_points` directly. If Ollama
hangs (VRAM eviction stall, daemon wedge) the await never returns, the
`finally` block that clears `_replan_in_flight` never fires, and every
subsequent replan trigger is dedup-skipped indefinitely. During the 240s
resilience_v1 scenario this starved the `drone_failure → drones.<id>.tasks`
chain — the EGS log showed 100+ `egs.replan skipped (already in flight)`
lines and zero per-drone tasks publishes.

Fix: wrap the await in `asyncio.wait_for(..., timeout=REPLAN_OVERALL_TIMEOUT_S)`.
On TimeoutError the `finally` clears the flag and the next replan trigger
gets a fresh attempt (which will hit the deterministic fallback path on a
sustained hang).

These tests cover three scenarios:
1. A hung `assign_survey_points` is abandoned at the configured timeout
   and the flag clears.
2. After a hung attempt, a second replan trigger CAN re-enter (proving
   the dedup guard isn't permanently stuck).
3. The timeout is bounded by `REPLAN_OVERALL_TIMEOUT_S` — patching it down
   to a tiny value lets the test run in milliseconds without flakiness.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

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


@pytest.mark.asyncio
async def test_replan_impl_clears_in_flight_flag_when_assign_hangs(monkeypatch):
    """If assign_survey_points hangs past REPLAN_OVERALL_TIMEOUT_S, the
    wait_for fires asyncio.TimeoutError, the `finally` clears the flag,
    and the coordinator is ready to accept the next replan trigger.

    Without the wait_for fix, this test hangs the whole pytest run because
    the never_returns() coroutine would await forever.
    """
    monkeypatch.setattr(coordinator_mod, "REPLAN_OVERALL_TIMEOUT_S", 0.1)

    never_returns_event = asyncio.Event()

    async def never_returns(*_args, **_kwargs):
        # Block forever until the test explicitly sets the event during
        # cleanup. The wait_for() in _replan_impl should cancel us at the
        # configured timeout.
        await never_returns_event.wait()
        return {}

    coord = EGSCoordinator(EGSValidationNode())
    coord._replan_in_flight = True  # mirror the synchronous guard in `replan()`

    with patch(
        "agents.egs_agent.coordinator.assign_survey_points",
        new=never_returns,
    ):
        await coord._replan_impl(_minimal_snapshot())

    assert coord._replan_in_flight is False, (
        "in-flight guard must clear after the wait_for timeout fires; "
        "otherwise every subsequent replan trigger is dedup-skipped forever "
        "(Bug 3 regression)."
    )
    # Release the hung coroutine so it doesn't leak into other tests.
    never_returns_event.set()


@pytest.mark.asyncio
async def test_replan_can_re_enter_after_hung_attempt_times_out(monkeypatch):
    """After a hung first attempt clears the flag via timeout, a second
    replan trigger MUST be able to re-enter (no permanent dedup lockup).

    This is the actual behaviour gap that blocked Phase D: drone_failure
    at sim_t=30s should fire replan, but the first (initial) replan was
    still hung from t=0 and the guard refused every subsequent attempt.
    """
    monkeypatch.setattr(coordinator_mod, "REPLAN_OVERALL_TIMEOUT_S", 0.05)

    hang_event = asyncio.Event()

    async def hang_then_succeed(*_args, **_kwargs):
        # First call hangs; releases when the test signals.
        await hang_event.wait()
        return {}

    coord = EGSCoordinator(EGSValidationNode())

    # First replan: simulate replan() setting the flag, then run _replan_impl.
    coord._replan_in_flight = True
    with patch(
        "agents.egs_agent.coordinator.assign_survey_points",
        new=hang_then_succeed,
    ):
        await coord._replan_impl(_minimal_snapshot())

    assert coord._replan_in_flight is False, "first attempt should clear flag on timeout"

    # Second replan: call replan() directly. It should NOT see the guard
    # as set, and should schedule a new background task.
    state = {
        "egs_state": _minimal_snapshot(),
        "incoming_telemetry": [],
        "incoming_findings": [],
        "incoming_commands": [],
        "incoming_actions": [],
        "messages_to_publish": [],
        "trigger_replan": True,
    }
    result = await coord.replan(state)
    assert coord._replan_in_flight is True, (
        "second replan must be allowed to proceed and own the in-flight slot "
        "(pre-fix: dedup-skipped because the first attempt never cleared the flag)"
    )
    assert result["trigger_replan"] is False, "replan() always clears trigger_replan"

    # Cleanup — let the second background task drain.
    hang_event.set()
    # Yield enough times to let the scheduled task progress through wait_for.
    # The new task will also time out (since assign_survey_points returns {}
    # we don't actually care — we just need to flush it).
    for _ in range(20):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_replan_impl_succeeds_normally_when_assign_returns_quickly(monkeypatch):
    """The wait_for wrapper must NOT change the happy path — a fast
    assign_survey_points still produces a normal assignment and clears
    the flag in finally. Regression guard against accidentally introducing
    a race in the wait_for plumbing.
    """
    monkeypatch.setattr(coordinator_mod, "REPLAN_OVERALL_TIMEOUT_S", 5.0)

    async def fast_assign(*_args, **_kwargs):
        # Return a minimal valid assignment shape.
        return {
            "function": "assign_survey_points",
            "arguments": {
                "assignments": [
                    {"drone_id": "drone1", "survey_point_ids": ["sp_001"]},
                    {"drone_id": "drone2", "survey_point_ids": ["sp_002"]},
                ],
            },
        }

    redis_client = AsyncMock()
    coord = EGSCoordinator(EGSValidationNode(), redis_client=redis_client)
    coord._replan_in_flight = True

    with patch(
        "agents.egs_agent.coordinator.assign_survey_points",
        new=fast_assign,
    ):
        await coord._replan_impl(_minimal_snapshot())

    assert coord._replan_in_flight is False
    # Should have published 2 per-drone task payloads + 1 replan_events envelope.
    assert redis_client.publish.await_count == 3, (
        f"expected 2 per-drone tasks + 1 replan_events publish, "
        f"got {redis_client.publish.await_count}"
    )


def test_per_attempt_timeout_fits_inside_outer_guard():
    """Iron-rule regression for GH #32 / Phase D VRAM-constrained chain.

    The deterministic round-robin fallback at the bottom of
    `agents/egs_agent/replanning.py::assign_survey_points` (after the
    `while retries <= max_retries:` loop) only runs if the retry loop
    *exhausts*. On a VRAM-stalled box every retry hits its full per-attempt
    httpx timeout (Ollama hangs waiting for `gemma4:e4b` eviction). If the
    retry loop's worst-case wall time exceeds the coordinator's outer
    `wait_for(REPLAN_OVERALL_TIMEOUT_S)` guard, the outer guard cancels
    the inner task mid-retry and the fallback is unreachable — every
    `drone_failure → drones.<id>.tasks` chain dies after the outer-guard
    window with zero tasks published.

    Pre-fix arithmetic (2026-05-13 Hazim live evidence on 8 GB VRAM box):
        timeout=180.0 × (max_retries=3 + 1) = 720s worst-case retry wall
        REPLAN_OVERALL_TIMEOUT_S = 240s
        720 > 240 → fallback unreachable → 0 drones.*.tasks publishes

    Post-fix arithmetic:
        EGS_HTTPX_PER_ATTEMPT_TIMEOUT_S=30.0 × 4 = 120s worst-case retry wall
        REPLAN_OVERALL_TIMEOUT_S = 240s, REPLAN_FALLBACK_HEADROOM_S = 30s
        120 + 30 = 150 ≤ 240 → fallback reachable

    Full live evidence at `docs/sim-resilience-run-notes.md` §"2026-05-13".

    This test reads the constants from the source modules instead of pinning
    literal numbers so any future bump to either timeout immediately surfaces
    here at unit-test time rather than at demo-capture time.
    """
    from agents.egs_agent.replanning import EGS_HTTPX_PER_ATTEMPT_TIMEOUT_S
    from agents.egs_agent.coordinator import (
        REPLAN_OVERALL_TIMEOUT_S,
        REPLAN_FALLBACK_HEADROOM_S,
    )
    from shared.contracts import CONFIG

    max_attempts = CONFIG.validation.max_retries + 1
    retry_loop_worst_case_s = EGS_HTTPX_PER_ATTEMPT_TIMEOUT_S * max_attempts
    budget_used_s = retry_loop_worst_case_s + REPLAN_FALLBACK_HEADROOM_S

    assert budget_used_s <= REPLAN_OVERALL_TIMEOUT_S, (
        f"GH #32 regression: retry-loop worst case "
        f"({EGS_HTTPX_PER_ATTEMPT_TIMEOUT_S}s × {max_attempts} attempts = "
        f"{retry_loop_worst_case_s}s) + fallback headroom "
        f"({REPLAN_FALLBACK_HEADROOM_S}s) = {budget_used_s}s exceeds the "
        f"outer guard ({REPLAN_OVERALL_TIMEOUT_S}s). The deterministic "
        f"round-robin fallback in replanning.py would be unreachable on a "
        f"VRAM-stalled box — same failure mode as the 2026-05-13 live re-run "
        f"that produced 940 'skipped' lines and 0 drones.*.tasks publishes. "
        f"Either lower EGS_HTTPX_PER_ATTEMPT_TIMEOUT_S, lower max_retries, "
        f"or raise REPLAN_OVERALL_TIMEOUT_S. See "
        f"docs/sim-resilience-run-notes.md §'2026-05-13' for context."
    )
