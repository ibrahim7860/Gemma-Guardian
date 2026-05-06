"""Agent republishes drones.<id>.state with merged agent-owned fields."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import fakeredis
import fakeredis.aioredis

from agents.drone_agent.runtime import DroneRuntime
from agents.drone_agent.zone_bounds import derive_zone_bounds_from_scenario
from sim.scenario import load_scenario
from shared.contracts import validate


REPO_ROOT = Path(__file__).resolve().parents[3]
SCENARIO_PATH = REPO_ROOT / "sim" / "scenarios" / "disaster_zone_v1.yaml"


def _state_payload(**overrides) -> dict:
    base = {
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
    base.update(overrides)
    return base


@pytest.fixture
def shared_server():
    return fakeredis.FakeServer()


@pytest.fixture
def fake_sync_redis(shared_server):
    return fakeredis.FakeStrictRedis(server=shared_server, decode_responses=False)


@pytest.fixture
def fake_async_redis(shared_server):
    return fakeredis.aioredis.FakeRedis(server=shared_server, decode_responses=False)


@pytest.mark.asyncio
async def test_agent_republishes_state_with_findings_count_after_finding(
    tmp_path, monkeypatch, fake_sync_redis, fake_async_redis,
):
    import cv2
    import numpy as np

    monkeypatch.setattr("agents.drone_agent.action.FRAMES_DIR", tmp_path / "frames")
    monkeypatch.setattr(
        "agents.drone_agent.main.VALIDATION_LOG_PATH",
        tmp_path / "validation_events.jsonl",
    )
    scenario = load_scenario(SCENARIO_PATH)
    zone_bounds = derive_zone_bounds_from_scenario(scenario, "drone1", buffer_m=50.0)

    canned = {
        "message": {
            "tool_calls": [{
                "function": {
                    "name": "report_finding",
                    "arguments": json.dumps({
                        "type": "fire",
                        "severity": 3,
                        "gps_lat": 34.0005,
                        "gps_lon": -118.5003,
                        "confidence": 0.85,
                        "visual_description": "rooftop flames clearly visible",
                    }),
                },
            }],
        },
    }

    runtime = DroneRuntime(
        drone_id="drone1",
        scenario=scenario, zone_bounds=zone_bounds,
        sync_client=fake_sync_redis, async_client=fake_async_redis,
        agent_step_period_s=0.05, agent_state_publish_period_s=0.05,
    )
    runtime.agent.reasoning.call = AsyncMock(return_value=canned)

    state_pubsub = fake_sync_redis.pubsub()
    state_pubsub.subscribe("drones.drone1.state")
    state_pubsub.get_message(timeout=0.1)

    img = np.full((60, 80, 3), (0, 0, 200), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok

    runtime_task = asyncio.create_task(runtime.run())
    try:
        await asyncio.sleep(0.1)
        await fake_async_redis.publish("drones.drone1.state", json.dumps(_state_payload()))
        await fake_async_redis.publish("drones.drone1.camera", buf.tobytes())

        # Wait for an agent-republished state where findings_count >= 1.
        deadline = asyncio.get_event_loop().time() + 3.0
        agent_published = None
        while asyncio.get_event_loop().time() < deadline:
            msg = state_pubsub.get_message(timeout=0.1)
            if msg and msg["type"] == "message":
                payload = json.loads(msg["data"])
                if payload.get("findings_count", 0) >= 1 and payload.get("last_action") == "report_finding":
                    agent_published = payload
                    break
            await asyncio.sleep(0.05)

        assert agent_published is not None, "agent did not republish state with findings_count>=1"
        outcome = validate("drone_state", agent_published)
        assert outcome.valid, outcome.errors
        assert agent_published["last_action"] == "report_finding"
        assert agent_published["last_action_timestamp"] is not None
    finally:
        await runtime.stop()
        await runtime_task
