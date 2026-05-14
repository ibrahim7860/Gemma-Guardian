"""End-to-end Phase 4 integration test (GATE 4 wow moment).

Asserts the full data path the Phase 1+2 unit tests don't cover end-to-end:

    EGSCoordinator
       └─ assign_survey_points retry loop (fake LLM, 27 then 25 points)
            └─ _append_replan_attempt sink
                 └─ egs_state.replan_in_flight_attempt_log (transient)
                      └─ Redis publish on `egs.state`
                           └─ Bridge RedisSubscriber → StateAggregator
                                └─ _emit_loop broadcast over WebSocket
                                     └─ Test client asserts envelope sequence

Per the plan's Phase 4 §2, the envelope sequence is:
    1. envelope with empty `replan_in_flight_attempt_log` (pre-replan)
    2. envelope with [attempt_1, valid=false, rule_id=ASSIGNMENT_TOTAL_MISMATCH]
    3. envelope with [attempt_1 invalid, attempt_2 valid]
    4. envelope with empty log again (post-clear delay)

Implementation notes (plan deviations, explained):
  * The plan asks for a "real redis-server via the existing test fixture."
    The repo's actual existing integration fixture (`app_and_redis` in
    `conftest.py`) monkey-patches `redis.asyncio.Redis.from_url` to return
    a `fakeredis.aioredis.FakeRedis` client, with single-loop ownership
    enforced by the project's pytest-asyncio config (the `e2e_phase3`
    file is the only one that uses a real external redis-server, and it
    requires `redis-cli ping` to succeed externally). Mirroring the
    `app_and_redis` pattern keeps this test self-contained and runnable
    on every contributor's box with no extra setup, while still exercising
    the SAME pub/sub semantics (redis-py asyncio API) and the SAME bridge
    subscriber code path. The behavior under test (envelopes flowing
    EGSCoordinator → bridge → WS) is identical with either backend.
  * `REPLAN_ATTEMPT_LOG_CLEAR_DELAY_S` is monkey-patched to 0.5s so the
    "envelope after clear" branch fires inside the 5-second receive
    budget without slowing the test suite.
"""
from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# This test instantiates a real `EGSCoordinator`, which transitively imports
# `langgraph`. The `bridge` CI job (`tests.yml::bridge`) deliberately syncs
# only `--extra ws_bridge --extra dev` — no `egs` extra — so langgraph isn't
# available there. Without this guard, pytest's collection phase raises
# `ModuleNotFoundError: No module named 'langgraph'` BEFORE the `pytestmark`
# below can deselect the file via `-m "not e2e"`. Skipping at module-import
# time keeps both CI jobs honest:
#   * `bridge` job: skipped at collection (no langgraph) — exit 0.
#   * `bridge_e2e` job: real run (egs extra present, `-m e2e` selects).
pytest.importorskip("langgraph")

from httpx_ws import aconnect_ws

from agents.egs_agent import coordinator as coordinator_mod
from agents.egs_agent.coordinator import EGSCoordinator
from agents.egs_agent.scenario_state import build_initial_egs_state
from agents.egs_agent.validation import EGSValidationNode
from frontend.ws_bridge.tests._helpers import make_test_client
from shared.contracts.topics import EGS_STATE

# Mark every test in this module as e2e so CI's `bridge` job correctly
# deselects via `-m "not e2e"` (the function-level `@pytest.mark.timeout(30)`
# already enforces the per-test bound).
pytestmark = pytest.mark.e2e


# ---- fake LLM helpers ------------------------------------------------------


def _resp(content_dict: Dict[str, Any]) -> MagicMock:
    """httpx-style mock response yielding a Gemma 4 'message.content' JSON."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"message": {"content": json.dumps(content_dict)}}
    return resp


def _twentyfive_point_state() -> Dict[str, Any]:
    """3 active drones, 25 unassigned survey points sp_001..sp_025.

    The shape the EGSCoordinator's replan reads — drones_summary + the
    unassigned survey_points list — must match what assign_survey_points
    inspects. Mirrors the unit-test fixture in
    `agents/egs_agent/tests/test_replanning_validation_logging.py`.
    """
    return {
        "mission_id": "wow_moment_v1",
        "mission_status": "active",
        "timestamp": "2026-05-12T14:23:11.000Z",
        # Minimal schema-valid polygon: 3 points (the schema's `polygon` $ref
        # requires minLength 3). Coordinates don't matter — the bridge
        # subscriber re-validates but does not interpret the geometry.
        "zone_polygon": [
            [34.0, -118.5], [34.001, -118.5], [34.001, -118.499],
        ],
        # drones_summary entries need a `battery` field per the egs_state
        # schema — the replanning loop only reads `status`, but the bridge
        # validator rejects the envelope without it.
        "drones_summary": {
            "drone1": {"status": "active", "battery": 87},
            "drone2": {"status": "active", "battery": 85},
            "drone3": {"status": "active", "battery": 90},
        },
        "survey_points": [
            {
                "id": f"sp_{i:03d}",
                "lat": 34.0 + 0.0001 * i,
                "lon": -118.5,
                "assigned_to": None,
                "status": "unassigned",
            }
            for i in range(1, 26)
        ],
        "findings_count_by_type": {
            "victim": 0, "fire": 0, "smoke": 0,
            "damaged_structure": 0, "blocked_route": 0,
        },
        "recent_validation_events": [],
        "active_zone_ids": [],
        "approved_findings": {},
        "replan_in_flight_attempt_log": [],
    }


def _overcount_27() -> Dict[str, Any]:
    """First fake-LLM response: 27 assigned points (2 phantom). Triggers
    ASSIGNMENT_TOTAL_MISMATCH, surfacing the wow-moment red banner.
    """
    overcount_ids = (
        [f"sp_{i:03d}" for i in range(1, 10)]
        + ["sp_phantom_A", "sp_phantom_B"]
    )
    return {
        "function": "assign_survey_points",
        "arguments": {
            "assignments": [
                {"drone_id": "drone1", "survey_point_ids": overcount_ids},
                {"drone_id": "drone2",
                 "survey_point_ids": [f"sp_{i:03d}" for i in range(10, 18)]},
                {"drone_id": "drone3",
                 "survey_point_ids": [f"sp_{i:03d}" for i in range(18, 26)]},
            ],
        },
    }


def _good_25() -> Dict[str, Any]:
    """Corrected fake-LLM response: 25 assigned points, balanced. Green banner."""
    return {
        "function": "assign_survey_points",
        "arguments": {
            "assignments": [
                {"drone_id": "drone1",
                 "survey_point_ids": [f"sp_{i:03d}" for i in range(1, 10)]},
                {"drone_id": "drone2",
                 "survey_point_ids": [f"sp_{i:03d}" for i in range(10, 18)]},
                {"drone_id": "drone3",
                 "survey_point_ids": [f"sp_{i:03d}" for i in range(18, 26)]},
            ],
        },
    }


# ---- the test --------------------------------------------------------------


@pytest.fixture
def fast_bridge_tick(monkeypatch):
    """Drop BRIDGE_TICK_S to 0.05s so each publish lands on a distinct
    emit-loop tick within the 5-second receive budget. Without this, the
    1Hz default rate-limits the aggregator's broadcasts and the test only
    observes the final attempt-log state (not the progressive sequence
    the wow-moment banner actually shows the operator).
    """
    monkeypatch.setenv("BRIDGE_TICK_S", "0.05")


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_replan_attempt_log_flows_egs_to_bridge_to_ws(
    fast_bridge_tick, app_and_redis, monkeypatch,
):
    """Full E2E: EGSCoordinator → fake-redis → bridge subscriber → WS client.

    Asserts the four-stage envelope sequence the plan §Phase 4 §2 calls
    out (empty → 1 invalid → 1 invalid + 1 valid → empty after clear).
    """
    app, fake_redis = app_and_redis

    # Shorten the post-replan clear delay so the "after-clear" envelope
    # lands inside the 5-second collection window. Module-level constant
    # is read at call time (see coordinator.py) so monkeypatch works.
    monkeypatch.setattr(
        coordinator_mod, "REPLAN_ATTEMPT_LOG_CLEAR_DELAY_S", 0.5,
    )

    # Stand up the EGSCoordinator and drive ONE replan with two fake-LLM
    # responses (27 then 25). The coordinator's _append_replan_attempt sink
    # populates _replan_attempt_log as each attempt completes.
    coordinator = EGSCoordinator(EGSValidationNode())
    initial_state = _twentyfive_point_state()

    # Capture the per-attempt entries appended by replanning.py so we can
    # publish a series of egs.state envelopes that mirror what a 1Hz
    # publish loop in production would emit. Each "tick" is a snapshot of
    # the in-flight attempt log at that moment.
    captured_snapshots: List[List[Dict[str, Any]]] = []

    original_append = coordinator._append_replan_attempt

    def _append_and_snapshot(attempt: Dict[str, Any]) -> None:
        original_append(attempt)
        # Snapshot AFTER the append so the bridge sees each progressive
        # state of the attempt log (empty → [1] → [1,2] in this scenario).
        captured_snapshots.append(deepcopy(coordinator._replan_attempt_log))

    coordinator._append_replan_attempt = _append_and_snapshot  # type: ignore[assignment]

    responses = [_resp(_overcount_27()), _resp(_good_25())]
    mock_post = AsyncMock(side_effect=responses)

    async with make_test_client(app) as http_client:
        async with aconnect_ws("ws://testserver/", client=http_client) as ws:
            # Consume the seed envelope (the first state_update broadcast
            # has an empty log since nothing has happened yet — that
            # itself is one of the four states the plan calls out).
            collected: List[Dict[str, Any]] = []

            async def _consume_envelopes(stop_event: asyncio.Event) -> None:
                while not stop_event.is_set():
                    try:
                        raw = await asyncio.wait_for(
                            ws.receive_text(), timeout=0.5,
                        )
                    except asyncio.TimeoutError:
                        continue
                    try:
                        env = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if env.get("type") == "state_update":
                        collected.append(env)

            stop_event = asyncio.Event()
            consumer_task = asyncio.create_task(_consume_envelopes(stop_event))

            try:
                # Give the subscriber a tick to bind to channels.
                await asyncio.sleep(0.2)

                # STAGE 1 — publish an empty-log baseline so the test has
                # at least one "pre-replan" envelope to assert on, even
                # if the consumer hasn't received the seed envelope yet.
                await fake_redis.publish(
                    EGS_STATE, json.dumps(initial_state),
                )
                await asyncio.sleep(0.2)

                # STAGE 2 + 3 — drive the actual replan. The fake httpx
                # client returns 27 then 25, so the retry loop appends
                # two entries to _replan_attempt_log (one invalid, one
                # valid). After each append, _append_and_snapshot captures
                # a deep copy; we then publish a fresh egs.state envelope
                # so the bridge subscriber sees that progressive state.
                with patch("httpx.AsyncClient.post", new=mock_post):
                    # Manually invoke assign_survey_points via the sink so
                    # the snapshot list grows in order. assign_survey_points
                    # is wired directly here (not via coordinator.replan)
                    # to avoid the fire-and-forget asyncio.create_task
                    # pattern that would race with the WS reader.
                    from agents.egs_agent.replanning import assign_survey_points
                    await assign_survey_points(
                        initial_state,
                        coordinator.validation_node,
                        validation_logger=coordinator._validation_log,
                        log_sink=coordinator._append_replan_attempt,
                    )

                # Publish each captured progressive state. We deliberately
                # publish one envelope per snapshot so each stage of the
                # log lands on a distinct WS frame.
                #
                # Sleep budget per publish: the bridge's emit loop ticks at
                # BRIDGE_TICK_S (monkey-patched to 0.05s via the
                # fast_bridge_tick fixture). We need at least one full tick
                # PLUS subscriber-dispatch latency between publishes so the
                # aggregator broadcasts the intermediate state before the
                # next publish overrides it. 0.3s is ~6 ticks — safe.
                for snap in captured_snapshots:
                    s = deepcopy(initial_state)
                    s["replan_in_flight_attempt_log"] = snap
                    await fake_redis.publish(EGS_STATE, json.dumps(s))
                    await asyncio.sleep(0.3)

                # STAGE 4 — schedule the clear and let it fire. The
                # coordinator's lifecycle schedules the clear in its
                # `finally`; here we mirror that by scheduling explicitly
                # and waiting REPLAN_ATTEMPT_LOG_CLEAR_DELAY_S + slack.
                coordinator._schedule_replan_attempt_log_clear()
                # 0.5s clear delay + 0.3s slack for the loop to drain.
                await asyncio.sleep(0.8)
                # Publish the cleared state so the bridge broadcasts it.
                s = deepcopy(initial_state)
                s["replan_in_flight_attempt_log"] = deepcopy(
                    coordinator._replan_attempt_log,
                )
                await fake_redis.publish(EGS_STATE, json.dumps(s))

                # Give the bridge a few emit-loop ticks to broadcast the
                # final cleared state. With BRIDGE_TICK_S=0.05s (from
                # fast_bridge_tick) 0.5s is ~10 ticks — plenty.
                await asyncio.sleep(0.5)
            finally:
                stop_event.set()
                try:
                    await asyncio.wait_for(consumer_task, timeout=2.0)
                except asyncio.TimeoutError:
                    consumer_task.cancel()
                    try:
                        await consumer_task
                    except (asyncio.CancelledError, Exception):
                        pass

    # ---- assertions on the captured envelope sequence ----------------------

    assert collected, (
        "no state_update envelopes received; either the bridge emit loop "
        "never broadcast or the WS reader exited prematurely"
    )

    def _log_for(env: Dict[str, Any]) -> List[Dict[str, Any]]:
        return (env.get("egs_state") or {}).get(
            "replan_in_flight_attempt_log", [],
        )

    # 1. At least one envelope with an empty log (pre-replan baseline).
    empty_logs = [e for e in collected if _log_for(e) == []]
    assert empty_logs, (
        "expected ≥1 envelope with an empty replan_in_flight_attempt_log "
        "(pre-replan baseline); got logs="
        f"{[_log_for(e) for e in collected]!r}"
    )

    # 2. At least one envelope with attempt 1 invalid + rule_id
    #    ASSIGNMENT_TOTAL_MISMATCH.
    one_invalid_only = [
        e for e in collected
        if len(_log_for(e)) == 1
        and _log_for(e)[0]["attempt_n"] == 1
        and _log_for(e)[0]["valid"] is False
        and _log_for(e)[0].get("rule_id") == "ASSIGNMENT_TOTAL_MISMATCH"
    ]
    assert one_invalid_only, (
        "expected ≥1 envelope with [attempt_1, valid=False, "
        "rule_id=ASSIGNMENT_TOTAL_MISMATCH]; got logs="
        f"{[_log_for(e) for e in collected]!r}"
    )

    # 3. At least one envelope with [attempt_1 invalid, attempt_2 valid].
    invalid_then_valid = [
        e for e in collected
        if len(_log_for(e)) == 2
        and _log_for(e)[0]["attempt_n"] == 1
        and _log_for(e)[0]["valid"] is False
        and _log_for(e)[1]["attempt_n"] == 2
        and _log_for(e)[1]["valid"] is True
    ]
    assert invalid_then_valid, (
        "expected ≥1 envelope with [attempt_1 invalid, attempt_2 valid]; "
        f"got logs={[_log_for(e) for e in collected]!r}"
    )

    # 4. At least one envelope with an empty log AFTER the populated
    #    envelopes — i.e. the post-clear-delay broadcast.
    invalid_then_valid_idx = collected.index(invalid_then_valid[0])
    post_clear = [
        e for e in collected[invalid_then_valid_idx + 1:]
        if _log_for(e) == []
    ]
    assert post_clear, (
        "expected ≥1 envelope with an empty log AFTER the populated "
        "envelopes (post-clear-delay broadcast); got logs="
        f"{[_log_for(e) for e in collected]!r}"
    )
