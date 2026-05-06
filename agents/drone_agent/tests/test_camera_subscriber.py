"""CameraSubscriber decodes JPEGs from drones.<id>.camera into a numpy slot."""
from __future__ import annotations

import asyncio

import cv2
import numpy as np
import pytest
import fakeredis.aioredis

from agents.drone_agent.redis_io import CameraSubscriber


@pytest.fixture
def fake_async_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=False)


def _make_jpeg(width=80, height=60, color=(0, 0, 255)) -> bytes:
    img = np.full((height, width, 3), color, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


@pytest.mark.asyncio
async def test_subscriber_decodes_published_jpeg(fake_async_redis):
    sub = CameraSubscriber(fake_async_redis, drone_id="drone1")
    task = asyncio.create_task(sub.run())
    try:
        await asyncio.sleep(0.05)
        jpeg = _make_jpeg()
        await fake_async_redis.publish("drones.drone1.camera", jpeg)
        await asyncio.sleep(0.1)

        snapshot = sub.latest()
        assert snapshot is not None
        frame, raw_bytes = snapshot
        assert isinstance(frame, np.ndarray)
        assert frame.shape == (60, 80, 3)
        assert raw_bytes == jpeg
    finally:
        await sub.stop()
        await task


@pytest.mark.asyncio
async def test_subscriber_drops_malformed_jpeg(fake_async_redis):
    sub = CameraSubscriber(fake_async_redis, drone_id="drone1")
    task = asyncio.create_task(sub.run())
    try:
        await asyncio.sleep(0.05)
        await fake_async_redis.publish("drones.drone1.camera", b"not a jpeg")
        await asyncio.sleep(0.1)
        assert sub.latest() is None
    finally:
        await sub.stop()
        await task


@pytest.mark.asyncio
async def test_subscriber_keeps_only_latest(fake_async_redis):
    sub = CameraSubscriber(fake_async_redis, drone_id="drone1")
    task = asyncio.create_task(sub.run())
    try:
        await asyncio.sleep(0.05)
        await fake_async_redis.publish("drones.drone1.camera", _make_jpeg(color=(0, 0, 255)))
        await fake_async_redis.publish("drones.drone1.camera", _make_jpeg(color=(0, 255, 0)))
        await asyncio.sleep(0.1)
        snapshot = sub.latest()
        assert snapshot is not None
        frame, _ = snapshot
        assert frame[0, 0, 1] == 255  # green channel maxed (BGR)
    finally:
        await sub.stop()
        await task
