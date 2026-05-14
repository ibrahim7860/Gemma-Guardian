"""Runtime integration: LinkStateMonitor + LinkStatusSubscriber + BufferedPublisher.

Beat 5 Path A-full Component 2 (Wave 2 Lane E). Verifies the end-to-end
event-driven standalone-detection wiring against FakeStrictRedis + a mocked
Ollama response. The fourth test (`test_runtime_buffer_drains_on_link_restore`)
is the primary load-bearing test for the whole feature.
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
from agents.drone_agent.zone_provider import ZoneProvider
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
    counter = {"n": 0}

    async def _call(*args, **kwargs):
        counter["n"] += 1
        return _canned_finding_response(gps_lat=34.0005 + 0.0001 * counter["n"])

    return _call


def _link_payload(drone_id: str, link: str, reason: str = "geometric") -> dict:
    return {
        "drone_id": drone_id,
        "link": link,
        "t": 120,
        "wall_clock_iso_ms": "2026-05-15T14:23:11.342Z",
        "reason": reason,
    }


@pytest.fixture
def shared_server():
    return fakeredis.FakeServer()


@pytest.fixture
def fake_sync_redis(shared_server):
    return fakeredis.FakeStrictRedis(server=shared_server, decode_responses=False)


@pytest.fixture
def fake_async_redis(shared_server):
    return fakeredis.aioredis.FakeRedis(server=shared_server, decode_responses=False)


def _make_runtime(*, log_dir, sync, async_, scenario, zone_provider) -> DroneRuntime:
    runtime = DroneRuntime(
        drone_id="drone1",
        scenario=scenario,
        zone_provider=zone_provider,
        sync_client=sync,
        async_client=async_,
        agent_step_period_s=0.05,
        agent_state_publish_period_s=0.1,
        log_dir=log_dir,
    )
    runtime.agent.reasoning.call = AsyncMock(side_effect=_make_varying_finding_caller())
    return runtime


def _patch_paths(monkeypatch, tmp_path):
    monkeypatch.setattr("agents.drone_agent.action.FRAMES_DIR", tmp_path / "frames")
    monkeypatch.setattr(
        "agents.drone_agent.main.VALIDATION_LOG_PATH",
        tmp_path / "validation_events.jsonl",
    )


@pytest.mark.asyncio
async def test_runtime_starts_in_standalone_until_link_up_event(
    tmp_path, monkeypatch, fake_sync_redis, fake_async_redis,
):
    """Without any mesh.link_status events, the periodic 1 Hz reconciliation
    flips the BufferedPublisher into standalone mode (defensive default)."""
    _patch_paths(monkeypatch, tmp_path)
    scenario = load_scenario(SCENARIO_PATH)
    zone_provider = ZoneProvider(scenario, buffer_m=50.0)
    runtime = _make_runtime(
        log_dir=tmp_path, sync=fake_sync_redis, async_=fake_async_redis,
        scenario=scenario, zone_provider=zone_provider,
    )
    # Monitor reports standalone immediately (defensive default).
    assert runtime.link_monitor.is_standalone() is True

    runtime_task = asyncio.create_task(runtime.run())
    try:
        # Let the periodic reconciliation tick at least once
        # (republish_period_s=0.1 in this fixture).
        await asyncio.sleep(0.4)
        assert runtime.link_monitor.is_standalone() is True
        assert runtime.buffered_publisher.is_standalone is True
    finally:
        await runtime.stop()
        await runtime_task


@pytest.mark.asyncio
async def test_runtime_flips_to_active_on_link_up_event(
    tmp_path, monkeypatch, fake_sync_redis, fake_async_redis,
):
    """A mesh.link_status link='up' event flips the publisher to active and
    findings start passing through to Redis."""
    _patch_paths(monkeypatch, tmp_path)
    scenario = load_scenario(SCENARIO_PATH)
    zone_provider = ZoneProvider(scenario, buffer_m=50.0)
    runtime = _make_runtime(
        log_dir=tmp_path, sync=fake_sync_redis, async_=fake_async_redis,
        scenario=scenario, zone_provider=zone_provider,
    )

    findings_pubsub = fake_sync_redis.pubsub()
    findings_pubsub.subscribe("drones.drone1.findings")
    findings_pubsub.get_message(timeout=0.1)

    runtime_task = asyncio.create_task(runtime.run())
    try:
        await asyncio.sleep(0.1)
        # Publish a link='up' event for our drone.
        await fake_async_redis.publish(
            "mesh.link_status", json.dumps(_link_payload("drone1", "up")),
        )
        # Wait for the subscriber to consume + the callback to flip state.
        # Waiting on monitor.is_standalone() is the load-bearing signal —
        # publisher.is_standalone happens to default to False so checking
        # only that has a race window before the periodic tick has run.
        deadline = asyncio.get_event_loop().time() + 1.5
        while asyncio.get_event_loop().time() < deadline:
            if runtime.link_monitor.is_standalone() is False:
                break
            await asyncio.sleep(0.02)
        assert runtime.link_monitor.is_standalone() is False
        # Wait one more periodic tick so the publisher reconciles.
        await asyncio.sleep(0.2)
        assert runtime.buffered_publisher.is_standalone is False

        # Now drive a finding and verify it lands on Redis (not buffered).
        await fake_async_redis.publish("drones.drone1.state", json.dumps(_state_payload()))
        await fake_async_redis.publish("drones.drone1.camera", _make_jpeg())
        deadline = asyncio.get_event_loop().time() + 2.0
        seen: dict | None = None
        while asyncio.get_event_loop().time() < deadline:
            msg = findings_pubsub.get_message(timeout=0.1)
            if msg and msg["type"] == "message":
                seen = json.loads(msg["data"])
                break
            await asyncio.sleep(0.02)
        assert seen is not None, "expected a finding to land on Redis when active"
        assert seen["source_drone_id"] == "drone1"
    finally:
        await runtime.stop()
        await runtime_task


@pytest.mark.asyncio
async def test_runtime_flips_to_standalone_on_link_down_event(
    tmp_path, monkeypatch, fake_sync_redis, fake_async_redis,
):
    """After 'up' (publisher active) → 'down' must re-engage standalone mode
    and subsequent findings must buffer."""
    _patch_paths(monkeypatch, tmp_path)
    scenario = load_scenario(SCENARIO_PATH)
    zone_provider = ZoneProvider(scenario, buffer_m=50.0)
    runtime = _make_runtime(
        log_dir=tmp_path, sync=fake_sync_redis, async_=fake_async_redis,
        scenario=scenario, zone_provider=zone_provider,
    )
    runtime_task = asyncio.create_task(runtime.run())
    try:
        await asyncio.sleep(0.1)
        # Bring link up.
        await fake_async_redis.publish(
            "mesh.link_status", json.dumps(_link_payload("drone1", "up")),
        )
        # Wait for the subscriber to deliver the up event (monitor flips).
        deadline = asyncio.get_event_loop().time() + 1.5
        while asyncio.get_event_loop().time() < deadline:
            if runtime.link_monitor.is_standalone() is False:
                break
            await asyncio.sleep(0.02)
        assert runtime.link_monitor.is_standalone() is False

        # Drop it.
        await fake_async_redis.publish(
            "mesh.link_status",
            json.dumps(_link_payload("drone1", "down", reason="scripted")),
        )
        deadline = asyncio.get_event_loop().time() + 1.5
        while asyncio.get_event_loop().time() < deadline:
            if runtime.link_monitor.is_standalone() is True:
                break
            await asyncio.sleep(0.02)
        assert runtime.link_monitor.is_standalone() is True
        # Give the publisher one tick to reconcile.
        await asyncio.sleep(0.2)
        assert runtime.buffered_publisher.is_standalone is True
    finally:
        await runtime.stop()
        await runtime_task


@pytest.mark.asyncio
async def test_runtime_buffer_drains_on_link_restore(
    tmp_path, monkeypatch, fake_sync_redis, fake_async_redis,
):
    """PRIMARY LOAD-BEARING TEST: standalone → produce ≥2 buffered findings →
    publish link='up' event → both findings flush to Redis in FIFO order.
    """
    _patch_paths(monkeypatch, tmp_path)
    scenario = load_scenario(SCENARIO_PATH)
    zone_provider = ZoneProvider(scenario, buffer_m=50.0)
    runtime = _make_runtime(
        log_dir=tmp_path, sync=fake_sync_redis, async_=fake_async_redis,
        scenario=scenario, zone_provider=zone_provider,
    )

    findings_pubsub = fake_sync_redis.pubsub()
    findings_pubsub.subscribe("drones.drone1.findings")
    findings_pubsub.get_message(timeout=0.1)

    runtime_task = asyncio.create_task(runtime.run())
    try:
        await asyncio.sleep(0.1)
        # Default (no event yet) is standalone — drive findings into the buffer.
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
        n_buffered = len(runtime._finding_buffer)
        assert n_buffered >= 2, f"expected ≥2 buffered findings, got {n_buffered}"

        # Nothing should be on Redis yet.
        msg = findings_pubsub.get_message(timeout=0.1)
        if msg and msg["type"] == "message":
            pytest.fail(f"unexpected finding on wire while standalone: {msg['data']!r}")

        # Publish link='up' — runtime flips, buffer drains synchronously
        # inside set_standalone(False).
        await fake_async_redis.publish(
            "mesh.link_status", json.dumps(_link_payload("drone1", "up")),
        )

        # Wait for replay to land on the wire.
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
                await asyncio.sleep(0.02)

        assert len(replayed) >= n_buffered, (
            f"expected ≥{n_buffered} replayed findings, got {len(replayed)}"
        )
        # The first n_buffered must match the buffered counter order.
        first_chunk = replayed[:n_buffered]
        nums = [int(p["finding_id"].rsplit("_", 1)[1]) for p in first_chunk]
        assert nums == sorted(nums), f"replay out of order: {nums}"
    finally:
        await runtime.stop()
        await runtime_task


@pytest.mark.asyncio
async def test_runtime_falls_back_to_standalone_after_staleness(
    tmp_path, monkeypatch, fake_sync_redis, fake_async_redis,
):
    """REGRESSION (test gap from review): publish ONE link='up' event, then
    no more events. Use the LinkStateMonitor's clock injection to fast-
    forward synthetic time past the 10 s threshold; the monitor (and the
    publisher, on the next periodic reconciliation tick) must report
    standalone.
    """
    _patch_paths(monkeypatch, tmp_path)
    scenario = load_scenario(SCENARIO_PATH)
    zone_provider = ZoneProvider(scenario, buffer_m=50.0)
    runtime = _make_runtime(
        log_dir=tmp_path, sync=fake_sync_redis, async_=fake_async_redis,
        scenario=scenario, zone_provider=zone_provider,
    )
    # Replace the monitor with one whose clock we control. The runtime
    # holds a reference, so swapping the attribute is sufficient — the
    # subscriber callback (`_handle_link_event`) reads through
    # `self.link_monitor` each call.
    fake_now = {"t": 1000.0}
    runtime.link_monitor = type(runtime.link_monitor)(
        drone_id="drone1",
        staleness_threshold_s=10.0,
        now_fn=lambda: fake_now["t"],
    )

    runtime_task = asyncio.create_task(runtime.run())
    try:
        await asyncio.sleep(0.1)
        # Bring link up.
        await fake_async_redis.publish(
            "mesh.link_status", json.dumps(_link_payload("drone1", "up")),
        )
        # Wait for the subscriber to actually note the event (monitor flips
        # to active). Only checking the publisher is racy because its initial
        # state already happens to be False.
        deadline = asyncio.get_event_loop().time() + 1.5
        while asyncio.get_event_loop().time() < deadline:
            if runtime.link_monitor.is_standalone() is False:
                break
            await asyncio.sleep(0.02)
        assert runtime.link_monitor.is_standalone() is False
        assert runtime.buffered_publisher.is_standalone is False

        # Fast-forward synthetic time past the 10 s staleness threshold
        # WITHOUT publishing further events. The monitor itself reports
        # standalone immediately…
        fake_now["t"] += 11.0
        assert runtime.link_monitor.is_standalone() is True

        # …and the next periodic reconciliation tick (≤ republish_period_s
        # = 0.1 s in this fixture) must propagate that to the buffered
        # publisher.
        deadline = asyncio.get_event_loop().time() + 1.5
        while asyncio.get_event_loop().time() < deadline:
            if runtime.buffered_publisher.is_standalone is True:
                break
            await asyncio.sleep(0.02)
        assert runtime.buffered_publisher.is_standalone is True
    finally:
        await runtime.stop()
        await runtime_task
