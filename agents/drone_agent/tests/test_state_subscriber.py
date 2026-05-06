"""StateSubscriber consumes drones.<id>.state and publishes a DroneState slot."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import fakeredis.aioredis

from agents.drone_agent.redis_io import StateSubscriber
from sim.scenario import load_scenario


REPO_ROOT = Path(__file__).resolve().parents[3]
SCENARIO = load_scenario(REPO_ROOT / "sim" / "scenarios" / "disaster_zone_v1.yaml")
ZONE_BOUNDS = {"lat_min": 33.99, "lat_max": 34.01,
               "lon_min": -118.51, "lon_max": -118.49}


@pytest.fixture
def fake_async_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=False)


def _valid_state(**overrides) -> dict:
    base = {
        "drone_id": "drone1",
        "timestamp": "2026-05-15T14:23:11.342Z",
        "position": {"lat": 34.0005, "lon": -118.5003, "alt": 25.0},
        "velocity": {"vx": 1.0, "vy": 0.0, "vz": 0.0},
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


@pytest.mark.asyncio
async def test_subscriber_translates_valid_state(fake_async_redis):
    sub = StateSubscriber(fake_async_redis, drone_id="drone1",
                          zone_bounds=ZONE_BOUNDS, scenario=SCENARIO)
    task = asyncio.create_task(sub.run())
    try:
        await asyncio.sleep(0.05)
        await fake_async_redis.publish("drones.drone1.state", json.dumps(_valid_state()))
        await asyncio.sleep(0.1)
        state = sub.latest()
        assert state is not None
        assert state.drone_id == "drone1"
        assert state.lat == pytest.approx(34.0005)
        assert state.zone_bounds == ZONE_BOUNDS
        assert state.next_waypoint == {"id": "sp_002", "lat": 34.0004, "lon": -118.5002}
    finally:
        await sub.stop()
        await task


@pytest.mark.asyncio
async def test_subscriber_drops_malformed_json(fake_async_redis):
    sub = StateSubscriber(fake_async_redis, drone_id="drone1",
                          zone_bounds=ZONE_BOUNDS, scenario=SCENARIO)
    task = asyncio.create_task(sub.run())
    try:
        await asyncio.sleep(0.05)
        await fake_async_redis.publish("drones.drone1.state", b"not json")
        await asyncio.sleep(0.1)
        assert sub.latest() is None
    finally:
        await sub.stop()
        await task


@pytest.mark.asyncio
async def test_subscriber_drops_schema_violating_state(fake_async_redis):
    sub = StateSubscriber(fake_async_redis, drone_id="drone1",
                          zone_bounds=ZONE_BOUNDS, scenario=SCENARIO)
    task = asyncio.create_task(sub.run())
    try:
        await asyncio.sleep(0.05)
        bad = _valid_state()
        bad["battery_pct"] = 150  # > 100, violates _common.json
        await fake_async_redis.publish("drones.drone1.state", json.dumps(bad))
        await asyncio.sleep(0.1)
        assert sub.latest() is None
    finally:
        await sub.stop()
        await task


@pytest.mark.asyncio
async def test_latest_raw_sim_filters_out_agent_republishes(fake_async_redis):
    """latest_raw_sim() must only reflect sim-shaped payloads. Agent republishes
    (last_action != "none" OR findings_count >= 1) must not overwrite the cache."""
    sub = StateSubscriber(fake_async_redis, drone_id="drone1",
                          zone_bounds=ZONE_BOUNDS, scenario=SCENARIO)
    task = asyncio.create_task(sub.run())
    try:
        await asyncio.sleep(0.05)

        sim1 = _valid_state()
        await fake_async_redis.publish("drones.drone1.state", json.dumps(sim1))
        await asyncio.sleep(0.05)
        assert sub.latest_raw_sim() == sim1

        # Agent-republished payload — must NOT overwrite the raw cache.
        republish = _valid_state()
        republish["last_action"] = "report_finding"
        republish["findings_count"] = 1
        republish["last_action_timestamp"] = "2026-05-15T14:23:12.342Z"
        await fake_async_redis.publish("drones.drone1.state", json.dumps(republish))
        await asyncio.sleep(0.05)
        assert sub.latest_raw_sim() == sim1, "agent republish leaked into raw cache"

        # Next sim tick — IS sim-shaped, should overwrite.
        sim2 = _valid_state(timestamp="2026-05-15T14:23:13.342Z")
        await fake_async_redis.publish("drones.drone1.state", json.dumps(sim2))
        await asyncio.sleep(0.05)
        assert sub.latest_raw_sim() == sim2
    finally:
        await sub.stop()
        await task
