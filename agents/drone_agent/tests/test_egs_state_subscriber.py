"""EgsStateSubscriber consumes egs.state, feeds `zone_polygon` to a ZoneProvider.

Pattern mirrors `test_link_status_subscriber.py`: fakeredis-driven, async,
short polling delays. The schema validation path is the real one (validates
against `shared/schemas/egs_state.json`).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import fakeredis.aioredis
import pytest

from agents.drone_agent.redis_io import EgsStateSubscriber
from agents.drone_agent.zone_provider import ZoneProvider
from sim.scenario import load_scenario

_SCENARIO_DIR = Path(__file__).resolve().parents[3] / "sim" / "scenarios"


def _scenario(name: str = "disaster_zone_v1"):
    return load_scenario(_SCENARIO_DIR / f"{name}.yaml")


def _valid_egs_state(**overrides) -> dict:
    base = {
        "mission_id": "test_mission",
        "mission_status": "active",
        "timestamp": "2026-05-15T14:23:11.342Z",
        "zone_polygon": [
            [34.0, -118.5],
            [34.0, -118.4],
            [34.1, -118.4],
            [34.1, -118.5],
            [34.0, -118.5],
        ],
        "survey_points": [],
        "drones_summary": {},
        "findings_count_by_type": {
            "victim": 0, "fire": 0, "smoke": 0,
            "damaged_structure": 0, "blocked_route": 0,
        },
        "recent_validation_events": [],
        "active_zone_ids": [],
    }
    base.update(overrides)
    return base


@pytest.fixture
def fake_async_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=False)


@pytest.mark.asyncio
async def test_valid_egs_state_updates_zone_provider(fake_async_redis):
    provider = ZoneProvider(_scenario())
    bootstrap = provider.current()
    sub = EgsStateSubscriber(fake_async_redis, zone_provider=provider)
    task = asyncio.create_task(sub.run())
    try:
        await asyncio.sleep(0.05)
        await fake_async_redis.publish("egs.state", json.dumps(_valid_egs_state()))
        await asyncio.sleep(0.2)
        new_zone = provider.current()
        assert new_zone != bootstrap, "provider should have updated"
        assert new_zone == {
            "polygon": [
                [34.0, -118.5], [34.0, -118.4], [34.1, -118.4],
                [34.1, -118.5], [34.0, -118.5],
            ],
        }
    finally:
        await sub.stop()
        await task


@pytest.mark.asyncio
async def test_schema_invalid_payload_dropped(fake_async_redis):
    """Missing required field — provider must stay on bootstrap."""
    provider = ZoneProvider(_scenario())
    bootstrap = provider.current()
    sub = EgsStateSubscriber(fake_async_redis, zone_provider=provider)
    task = asyncio.create_task(sub.run())
    try:
        await asyncio.sleep(0.05)
        bad = _valid_egs_state()
        del bad["zone_polygon"]
        await fake_async_redis.publish("egs.state", json.dumps(bad))
        await asyncio.sleep(0.2)
        assert provider.current() == bootstrap
    finally:
        await sub.stop()
        await task


@pytest.mark.asyncio
async def test_malformed_json_dropped(fake_async_redis):
    provider = ZoneProvider(_scenario())
    bootstrap = provider.current()
    sub = EgsStateSubscriber(fake_async_redis, zone_provider=provider)
    task = asyncio.create_task(sub.run())
    try:
        await asyncio.sleep(0.05)
        await fake_async_redis.publish("egs.state", b"not json")
        await asyncio.sleep(0.2)
        assert provider.current() == bootstrap
    finally:
        await sub.stop()
        await task


@pytest.mark.asyncio
async def test_subsequent_updates_overwrite(fake_async_redis):
    """Two valid messages with different polygons; latest wins."""
    provider = ZoneProvider(_scenario())
    sub = EgsStateSubscriber(fake_async_redis, zone_provider=provider)
    task = asyncio.create_task(sub.run())
    try:
        await asyncio.sleep(0.05)
        first = _valid_egs_state(zone_polygon=[
            [10.0, 20.0], [10.0, 21.0], [11.0, 21.0], [11.0, 20.0], [10.0, 20.0],
        ])
        await fake_async_redis.publish("egs.state", json.dumps(first))
        await asyncio.sleep(0.1)
        assert provider.current() == {"polygon": [
            [10.0, 20.0], [10.0, 21.0], [11.0, 21.0], [11.0, 20.0], [10.0, 20.0],
        ]}
        second = _valid_egs_state(zone_polygon=[
            [30.0, 40.0], [30.0, 41.0], [31.0, 41.0], [31.0, 40.0], [30.0, 40.0],
        ])
        await fake_async_redis.publish("egs.state", json.dumps(second))
        await asyncio.sleep(0.2)
        assert provider.current() == {"polygon": [
            [30.0, 40.0], [30.0, 41.0], [31.0, 41.0], [31.0, 40.0], [30.0, 40.0],
        ]}
    finally:
        await sub.stop()
        await task


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["completed", "aborted"])
async def test_non_active_mission_status_does_not_update_provider(fake_async_redis, status):
    """A completed/aborted mission may ship its last-known polygon; we don't
    want a post-mission state to redefine the live zone. Guard added per
    /review on the 2026-05-13 migration."""
    provider = ZoneProvider(_scenario())
    bootstrap = provider.current()
    sub = EgsStateSubscriber(fake_async_redis, zone_provider=provider)
    task = asyncio.create_task(sub.run())
    try:
        await asyncio.sleep(0.05)
        payload = _valid_egs_state(mission_status=status, zone_polygon=[
            [0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0],
        ])
        await fake_async_redis.publish("egs.state", json.dumps(payload))
        await asyncio.sleep(0.2)
        assert provider.current() == bootstrap, f"mission_status={status} must not update zone"
    finally:
        await sub.stop()
        await task


@pytest.mark.asyncio
async def test_stop_unsubscribes_cleanly(fake_async_redis):
    provider = ZoneProvider(_scenario())
    sub = EgsStateSubscriber(fake_async_redis, zone_provider=provider)
    task = asyncio.create_task(sub.run())
    await asyncio.sleep(0.05)
    await sub.stop()
    await asyncio.wait_for(task, timeout=1.0)  # must terminate within 1s
