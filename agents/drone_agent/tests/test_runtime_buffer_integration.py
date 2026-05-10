"""Integration: DroneRuntime + BufferedPublisher across an EGS-link drop.

Beat 5 Path A-full Component 1. Wires the full runtime against FakeStrictRedis
+ a mocked Ollama response and verifies the end-to-end shape of the
buffer-and-replay mechanism.

Restart regression covers the test gap "drone-restart-replays-jsonl-without-
double-publish" from the eng-review.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import cv2
import fakeredis
import fakeredis.aioredis
import numpy as np
import pytest

from agents.drone_agent.runtime import DroneRuntime
from agents.drone_agent.zone_bounds import derive_zone_bounds_from_scenario
from sim.scenario import load_scenario


REPO_ROOT = Path(__file__).resolve().parents[3]
SCENARIO_PATH = REPO_ROOT / "sim" / "scenarios" / "disaster_zone_v1.yaml"


def _make_jpeg() -> bytes:
    img = np.full((60, 80, 3), (0, 0, 200), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


def _state_payload() -> dict:
    return {
        "drone_id": "drone1",
        "timestamp": "2026-05-15T14:23:11.342Z",
        "position": {"lat": 34.0005, "lon": -118.5003, "alt": 25.0},
        "velocity": {"vx": 0.0, "vy": 0.0, "vz": 0.0},
        "battery_pct": 87,
        "heading_deg": 135.0,
        "current_task": None,
        "current_waypoint_id": "sp_002",
        "assigned_survey_points_remaining": 3,
        "last_action": "none",
        "last_action_timestamp": None,
        "validation_failures_total": 0,
        "findings_count": 0,
        "in_mesh_range_of": [],
        "agent_status": "active",
    }


def _canned_finding_response(severity: int = 4, gps_lat: float = 34.0005) -> dict:
    return {
        "message": {
            "tool_calls": [{
                "function": {
                    "name": "report_finding",
                    "arguments": json.dumps({
                        "type": "victim",
                        "severity": severity,
                        "gps_lat": gps_lat,
                        "gps_lon": -118.5003,
                        "confidence": 0.78,
                        "visual_description": "person prone in rubble, partial cover",
                    }),
                },
            }],
        },
    }


def _make_varying_finding_caller():
    """Yields a fresh finding response per call with monotonically shifted GPS
    so the duplicate-distance validator doesn't reject subsequent emissions."""
    counter = {"n": 0}

    async def _call(*args, **kwargs):
        counter["n"] += 1
        # ~2 m per step; enough to clear DUPLICATE_DISTANCE_M while staying
        # inside the per-drone zone bounds.
        return _canned_finding_response(gps_lat=34.0005 + 0.0001 * counter["n"])

    return _call


@pytest.fixture
def shared_server():
    return fakeredis.FakeServer()


@pytest.fixture
def fake_sync_redis(shared_server):
    return fakeredis.FakeStrictRedis(server=shared_server, decode_responses=False)


@pytest.fixture
def fake_async_redis(shared_server):
    return fakeredis.aioredis.FakeRedis(server=shared_server, decode_responses=False)


def _make_runtime(
    *, log_dir: Path, sync, async_, scenario, zone_bounds, varying: bool = True,
) -> DroneRuntime:
    runtime = DroneRuntime(
        drone_id="drone1",
        scenario=scenario,
        zone_bounds=zone_bounds,
        sync_client=sync,
        async_client=async_,
        agent_step_period_s=0.05,
        log_dir=log_dir,
    )
    if varying:
        runtime.agent.reasoning.call = AsyncMock(side_effect=_make_varying_finding_caller())
    else:
        runtime.agent.reasoning.call = AsyncMock(return_value=_canned_finding_response())
    return runtime


async def _drive_one_finding(runtime, fake_async_redis, findings_pubsub, *, want: bool):
    """Publish a state+frame pair and wait for either a finding to land
    on Redis (`want=True`) or for the buffer to grow (`want=False`)."""
    await fake_async_redis.publish("drones.drone1.state", json.dumps(_state_payload()))
    await fake_async_redis.publish("drones.drone1.camera", _make_jpeg())

    deadline = asyncio.get_event_loop().time() + 2.0
    while asyncio.get_event_loop().time() < deadline:
        msg = findings_pubsub.get_message(timeout=0.1)
        if msg and msg["type"] == "message":
            return json.loads(msg["data"])
        if not want and len(runtime._finding_buffer) > 0:
            return None
        await asyncio.sleep(0.05)
    return None


@pytest.mark.asyncio
async def test_runtime_findings_pass_through_normally(
    tmp_path, monkeypatch, fake_sync_redis, fake_async_redis,
):
    """Default state is is_standalone=False — findings hit Redis directly."""
    monkeypatch.setattr("agents.drone_agent.action.FRAMES_DIR", tmp_path / "frames")
    monkeypatch.setattr(
        "agents.drone_agent.main.VALIDATION_LOG_PATH",
        tmp_path / "validation_events.jsonl",
    )

    scenario = load_scenario(SCENARIO_PATH)
    zone_bounds = derive_zone_bounds_from_scenario(scenario, "drone1", buffer_m=50.0)

    runtime = _make_runtime(
        log_dir=tmp_path,
        sync=fake_sync_redis,
        async_=fake_async_redis,
        scenario=scenario,
        zone_bounds=zone_bounds,
    )
    assert runtime.buffered_publisher.is_standalone is False

    findings_pubsub = fake_sync_redis.pubsub()
    findings_pubsub.subscribe("drones.drone1.findings")
    findings_pubsub.get_message(timeout=0.1)

    runtime_task = asyncio.create_task(runtime.run())
    try:
        await asyncio.sleep(0.1)
        payload = await _drive_one_finding(
            runtime, fake_async_redis, findings_pubsub, want=True,
        )
        assert payload is not None, "expected finding on findings channel"
        assert payload["source_drone_id"] == "drone1"
    finally:
        await runtime.stop()
        await runtime_task


@pytest.mark.asyncio
async def test_runtime_findings_buffer_during_standalone(
    tmp_path, monkeypatch, fake_sync_redis, fake_async_redis,
):
    monkeypatch.setattr("agents.drone_agent.action.FRAMES_DIR", tmp_path / "frames")
    monkeypatch.setattr(
        "agents.drone_agent.main.VALIDATION_LOG_PATH",
        tmp_path / "validation_events.jsonl",
    )

    scenario = load_scenario(SCENARIO_PATH)
    zone_bounds = derive_zone_bounds_from_scenario(scenario, "drone1", buffer_m=50.0)

    runtime = _make_runtime(
        log_dir=tmp_path,
        sync=fake_sync_redis,
        async_=fake_async_redis,
        scenario=scenario,
        zone_bounds=zone_bounds,
    )
    runtime.buffered_publisher.set_standalone(True)

    findings_pubsub = fake_sync_redis.pubsub()
    findings_pubsub.subscribe("drones.drone1.findings")
    findings_pubsub.get_message(timeout=0.1)

    runtime_task = asyncio.create_task(runtime.run())
    try:
        await asyncio.sleep(0.1)
        # Drive two state+frame ticks. We only need ≥1 buffered finding to
        # prove the gating; standalone is True so nothing should reach Redis.
        await fake_async_redis.publish("drones.drone1.state", json.dumps(_state_payload()))
        await fake_async_redis.publish("drones.drone1.camera", _make_jpeg())

        # Wait for the buffer to accumulate at least 2 entries.
        deadline = asyncio.get_event_loop().time() + 3.0
        while asyncio.get_event_loop().time() < deadline:
            if len(runtime._finding_buffer) >= 2:
                break
            await fake_async_redis.publish("drones.drone1.state", json.dumps(_state_payload()))
            await fake_async_redis.publish("drones.drone1.camera", _make_jpeg())
            await asyncio.sleep(0.1)

        assert len(runtime._finding_buffer) >= 2, (
            f"expected ≥2 buffered findings, got {len(runtime._finding_buffer)}"
        )
        # Nothing on the Redis findings channel.
        msg = findings_pubsub.get_message(timeout=0.2)
        if msg and msg["type"] == "message":
            pytest.fail(
                f"unexpected finding on Redis while standalone: {msg['data']!r}"
            )

        # JSONL has the same entries persisted.
        jsonl_path = tmp_path / "drone1_findings_queue.jsonl"
        assert jsonl_path.exists()
        lines = [
            line for line in jsonl_path.read_text().splitlines() if line.strip()
        ]
        assert len(lines) == len(runtime._finding_buffer)
    finally:
        await runtime.stop()
        await runtime_task


@pytest.mark.asyncio
async def test_runtime_findings_replay_on_link_restore(
    tmp_path, monkeypatch, fake_sync_redis, fake_async_redis,
):
    monkeypatch.setattr("agents.drone_agent.action.FRAMES_DIR", tmp_path / "frames")
    monkeypatch.setattr(
        "agents.drone_agent.main.VALIDATION_LOG_PATH",
        tmp_path / "validation_events.jsonl",
    )

    scenario = load_scenario(SCENARIO_PATH)
    zone_bounds = derive_zone_bounds_from_scenario(scenario, "drone1", buffer_m=50.0)

    runtime = _make_runtime(
        log_dir=tmp_path,
        sync=fake_sync_redis,
        async_=fake_async_redis,
        scenario=scenario,
        zone_bounds=zone_bounds,
    )
    runtime.buffered_publisher.set_standalone(True)

    findings_pubsub = fake_sync_redis.pubsub()
    findings_pubsub.subscribe("drones.drone1.findings")
    findings_pubsub.get_message(timeout=0.1)

    runtime_task = asyncio.create_task(runtime.run())
    try:
        await asyncio.sleep(0.1)
        # Accumulate at least 2 buffered findings.
        deadline = asyncio.get_event_loop().time() + 3.0
        while (
            asyncio.get_event_loop().time() < deadline
            and len(runtime._finding_buffer) < 2
        ):
            await fake_async_redis.publish(
                "drones.drone1.state", json.dumps(_state_payload()),
            )
            await fake_async_redis.publish("drones.drone1.camera", _make_jpeg())
            await asyncio.sleep(0.1)
        assert len(runtime._finding_buffer) >= 2
        n_buffered = len(runtime._finding_buffer)

        # Link restored — drain.
        runtime.buffered_publisher.set_standalone(False)

        # The drain happens synchronously inside set_standalone, so all
        # buffered findings should be on Redis essentially immediately.
        replayed: list[dict] = []
        deadline = asyncio.get_event_loop().time() + 2.0
        while (
            asyncio.get_event_loop().time() < deadline
            and len(replayed) < n_buffered
        ):
            msg = findings_pubsub.get_message(timeout=0.1)
            if msg and msg["type"] == "message":
                replayed.append(json.loads(msg["data"]))
            else:
                await asyncio.sleep(0.05)

        assert len(replayed) == n_buffered, (
            f"expected {n_buffered} replayed findings, got {len(replayed)}"
        )
        # Order is preserved (monotonic finding_ids by counter).
        ids = [p["finding_id"] for p in replayed]
        # Order must match the natural counter order (numeric, not lexical).
        nums = [int(fid.rsplit("_", 1)[1]) for fid in ids]
        assert nums == sorted(nums), f"replay out of order: {ids}"
    finally:
        await runtime.stop()
        await runtime_task


@pytest.mark.asyncio
async def test_runtime_drone_restart_replays_jsonl_without_double_publish(
    tmp_path, monkeypatch, fake_sync_redis, fake_async_redis,
):
    """REGRESSION: kills runtime mid-standalone, instantiates a fresh one in
    the same log_dir, set_standalone(False), asserts EXACTLY the buffered
    count is published — not double.

    Closes test gap "drone-restart-replays-jsonl-without-double-publish"
    from the eng-review.
    """
    monkeypatch.setattr("agents.drone_agent.action.FRAMES_DIR", tmp_path / "frames")
    monkeypatch.setattr(
        "agents.drone_agent.main.VALIDATION_LOG_PATH",
        tmp_path / "validation_events.jsonl",
    )

    scenario = load_scenario(SCENARIO_PATH)
    zone_bounds = derive_zone_bounds_from_scenario(scenario, "drone1", buffer_m=50.0)

    # First incarnation — produce 2 findings into the buffer.
    runtime1 = _make_runtime(
        log_dir=tmp_path,
        sync=fake_sync_redis,
        async_=fake_async_redis,
        scenario=scenario,
        zone_bounds=zone_bounds,
    )
    runtime1.buffered_publisher.set_standalone(True)

    findings_pubsub = fake_sync_redis.pubsub()
    findings_pubsub.subscribe("drones.drone1.findings")
    findings_pubsub.get_message(timeout=0.1)

    task1 = asyncio.create_task(runtime1.run())
    try:
        await asyncio.sleep(0.1)
        deadline = asyncio.get_event_loop().time() + 3.0
        while (
            asyncio.get_event_loop().time() < deadline
            and len(runtime1._finding_buffer) < 2
        ):
            await fake_async_redis.publish(
                "drones.drone1.state", json.dumps(_state_payload()),
            )
            await fake_async_redis.publish("drones.drone1.camera", _make_jpeg())
            await asyncio.sleep(0.1)
        n_buffered = len(runtime1._finding_buffer)
        assert n_buffered >= 2, f"expected ≥2 buffered, got {n_buffered}"
    finally:
        await runtime1.stop()
        await task1

    # JSONL persists across the runtime tear-down with exactly the entries
    # the in-memory deque held — same count, no drift.
    jsonl_path = tmp_path / "drone1_findings_queue.jsonl"
    assert jsonl_path.exists()
    lines_after_crash = [
        line for line in jsonl_path.read_text().splitlines() if line.strip()
    ]
    assert len(lines_after_crash) == n_buffered

    # Drain Redis pubsub of any backlog from runtime1 (should be empty since
    # standalone gated everything — but flush defensively before assertion).
    while True:
        msg = findings_pubsub.get_message(timeout=0.05)
        if msg is None:
            break

    # Second incarnation: same log_dir. Should rehydrate the persisted
    # entries and replay them on link restore.
    #
    # We instantiate the runtime but do NOT start `runtime.run()`. The
    # restart-replay mechanic is purely a function of FindingBuffer +
    # BufferedPublisher behavior at __init__ time and on set_standalone
    # transitions; the async step loop is irrelevant here and would only
    # add interleaving noise (the agent would produce NEW findings as it
    # ticks, not double-publish the rehydrated ones — but easier to
    # isolate the regression by not running it at all).
    runtime2 = _make_runtime(
        log_dir=tmp_path,
        sync=fake_sync_redis,
        async_=fake_async_redis,
        scenario=scenario,
        zone_bounds=zone_bounds,
    )
    assert len(runtime2._finding_buffer) == n_buffered, (
        f"fresh runtime should rehydrate exactly the {n_buffered} persisted entries"
    )
    # Restoration auto-puts the publisher in standalone mode (we resumed
    # mid-window). Flipping False drains.
    assert runtime2.buffered_publisher.is_standalone is True
    runtime2.buffered_publisher.set_standalone(False)

    replayed: list[dict] = []
    # set_standalone(False) drains synchronously, but Redis pubsub delivery
    # to a subscriber is still async — give it a short window.
    deadline = asyncio.get_event_loop().time() + 1.0
    while asyncio.get_event_loop().time() < deadline:
        msg = findings_pubsub.get_message(timeout=0.05)
        if msg and msg["type"] == "message":
            replayed.append(json.loads(msg["data"]))
        else:
            await asyncio.sleep(0.02)

    # CRITICAL: exactly n_buffered, NOT 2*n_buffered. The whole point of
    # the regression is that a restart-then-restore must not double-emit
    # the persisted entries (e.g. once on rehydrate, once on drain).
    assert len(replayed) == n_buffered, (
        f"expected EXACTLY {n_buffered} replayed findings (no double-publish), "
        f"got {len(replayed)}"
    )
    ids = [p["finding_id"] for p in replayed]
    # Order must match the natural counter order (numeric, not lexical).
    nums = [int(fid.rsplit("_", 1)[1]) for fid in ids]
    assert nums == sorted(nums), f"replay out of order: {ids}"

    # And the buffer + JSONL are now empty.
    assert len(runtime2._finding_buffer) == 0
    assert (tmp_path / "drone1_findings_queue.jsonl").read_text() == ""
