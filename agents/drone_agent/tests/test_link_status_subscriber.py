"""LinkStatusSubscriber consumes mesh.link_status, filters by drone_id, and
calls back with the link value.

Beat 5 Component 2 / Wave 2 Lane E.
"""
from __future__ import annotations

import asyncio
import json

import fakeredis.aioredis
import pytest

from agents.drone_agent.redis_io import LinkStatusSubscriber


@pytest.fixture
def fake_async_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=False)


def _valid_payload(drone_id: str = "drone1", link: str = "up", **overrides) -> dict:
    base = {
        "drone_id": drone_id,
        "link": link,
        "t": 120,
        "wall_clock_iso_ms": "2026-05-15T14:23:11.342Z",
        "reason": "geometric",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_subscriber_receives_filtered_events_for_own_drone_id(fake_async_redis):
    """A valid in-scope event must invoke the callback exactly once."""
    received: list[str] = []
    sub = LinkStatusSubscriber(
        fake_async_redis, drone_id="drone1", on_link_event=received.append,
    )
    task = asyncio.create_task(sub.run())
    try:
        await asyncio.sleep(0.05)
        await fake_async_redis.publish(
            "mesh.link_status", json.dumps(_valid_payload(drone_id="drone1", link="up")),
        )
        await asyncio.sleep(0.15)
        assert received == ["up"]
    finally:
        await sub.stop()
        await task


@pytest.mark.asyncio
async def test_subscriber_ignores_events_for_other_drones(fake_async_redis):
    """The shared mesh.link_status channel carries events for ALL drones;
    the subscriber must drop any whose drone_id doesn't match."""
    received: list[str] = []
    sub = LinkStatusSubscriber(
        fake_async_redis, drone_id="drone1", on_link_event=received.append,
    )
    task = asyncio.create_task(sub.run())
    try:
        await asyncio.sleep(0.05)
        # Three events: only the middle one is for us.
        await fake_async_redis.publish(
            "mesh.link_status", json.dumps(_valid_payload(drone_id="drone2", link="down")),
        )
        await fake_async_redis.publish(
            "mesh.link_status", json.dumps(_valid_payload(drone_id="drone1", link="up")),
        )
        await fake_async_redis.publish(
            "mesh.link_status", json.dumps(_valid_payload(drone_id="drone3", link="down")),
        )
        await asyncio.sleep(0.2)
        assert received == ["up"]
    finally:
        await sub.stop()
        await task


@pytest.mark.asyncio
async def test_subscriber_drops_invalid_payloads(fake_async_redis):
    """Schema-invalid payloads (and malformed JSON) for our drone_id must be
    dropped, with no callback firing."""
    received: list[str] = []
    sub = LinkStatusSubscriber(
        fake_async_redis, drone_id="drone1", on_link_event=received.append,
    )
    task = asyncio.create_task(sub.run())
    try:
        await asyncio.sleep(0.05)
        # Malformed JSON.
        await fake_async_redis.publish("mesh.link_status", b"not json")
        # Schema-invalid: bad link enum value (own drone_id, so the filter
        # passes and the schema validator rejects).
        await fake_async_redis.publish(
            "mesh.link_status",
            json.dumps(_valid_payload(drone_id="drone1", link="flapping")),
        )
        # Schema-invalid: missing required `reason`.
        bad = _valid_payload(drone_id="drone1", link="up")
        del bad["reason"]
        await fake_async_redis.publish("mesh.link_status", json.dumps(bad))
        await asyncio.sleep(0.2)
        assert received == []
    finally:
        await sub.stop()
        await task


@pytest.mark.asyncio
async def test_subscriber_calls_callback_with_link_value(fake_async_redis):
    """A sequence of valid events must arrive at the callback in order with
    each event's `link` value passed through verbatim."""
    received: list[str] = []
    sub = LinkStatusSubscriber(
        fake_async_redis, drone_id="drone1", on_link_event=received.append,
    )
    task = asyncio.create_task(sub.run())
    try:
        await asyncio.sleep(0.05)
        await fake_async_redis.publish(
            "mesh.link_status", json.dumps(_valid_payload(link="up")),
        )
        await asyncio.sleep(0.05)
        await fake_async_redis.publish(
            "mesh.link_status", json.dumps(_valid_payload(link="down")),
        )
        await asyncio.sleep(0.05)
        await fake_async_redis.publish(
            "mesh.link_status", json.dumps(_valid_payload(link="up", reason="heartbeat")),
        )
        await asyncio.sleep(0.2)
        assert received == ["up", "down", "up"]
    finally:
        await sub.stop()
        await task
