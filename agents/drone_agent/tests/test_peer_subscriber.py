"""PeerSubscriber buffers broadcasts from swarm.<id>.visible_to.<id>."""
from __future__ import annotations

import asyncio
import json

import pytest
import fakeredis.aioredis

from agents.drone_agent.redis_io import PeerSubscriber


@pytest.fixture
def fake_async_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=False)


def _bcast(bid: str) -> dict:
    return {
        "broadcast_id": bid,
        "sender_id": "drone2",
        "sender_position": {"lat": 34.0, "lon": -118.5, "alt": 25.0},
        "timestamp": "2026-05-15T14:23:11.342Z",
        "broadcast_type": "task_complete",
        "payload": {"task_id": "t1", "result": "success"},
    }


@pytest.mark.asyncio
async def test_subscriber_accumulates_broadcasts(fake_async_redis):
    sub = PeerSubscriber(fake_async_redis, drone_id="drone1", max_size=10)
    task = asyncio.create_task(sub.run())
    try:
        await asyncio.sleep(0.05)
        for i in range(3):
            await fake_async_redis.publish(
                "swarm.drone1.visible_to.drone1", json.dumps(_bcast(f"b{i}")),
            )
        await asyncio.sleep(0.1)
        recent = sub.recent()
        assert [b["broadcast_id"] for b in recent] == ["b0", "b1", "b2"]
    finally:
        await sub.stop()
        await task


@pytest.mark.asyncio
async def test_subscriber_dedupes_by_broadcast_id(fake_async_redis):
    sub = PeerSubscriber(fake_async_redis, drone_id="drone1", max_size=10)
    task = asyncio.create_task(sub.run())
    try:
        await asyncio.sleep(0.05)
        await fake_async_redis.publish("swarm.drone1.visible_to.drone1", json.dumps(_bcast("dup")))
        await fake_async_redis.publish("swarm.drone1.visible_to.drone1", json.dumps(_bcast("dup")))
        await fake_async_redis.publish("swarm.drone1.visible_to.drone1", json.dumps(_bcast("other")))
        await asyncio.sleep(0.1)
        ids = [b["broadcast_id"] for b in sub.recent()]
        assert ids == ["dup", "other"]
    finally:
        await sub.stop()
        await task


@pytest.mark.asyncio
async def test_subscriber_caps_at_max_size(fake_async_redis):
    sub = PeerSubscriber(fake_async_redis, drone_id="drone1", max_size=3)
    task = asyncio.create_task(sub.run())
    try:
        await asyncio.sleep(0.05)
        for i in range(6):
            await fake_async_redis.publish(
                "swarm.drone1.visible_to.drone1", json.dumps(_bcast(f"b{i}")),
            )
        await asyncio.sleep(0.1)
        ids = [b["broadcast_id"] for b in sub.recent()]
        assert ids == ["b3", "b4", "b5"]
    finally:
        await sub.stop()
        await task
