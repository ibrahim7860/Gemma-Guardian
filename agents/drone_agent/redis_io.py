"""Redis I/O — RedisPublisher (sync) + async subscriber helpers.

The sync publisher implements the `Publisher` Protocol from action.py and
is used by ActionNode to emit findings, broadcasts, and cmd messages.

Async subscribers (CameraSubscriber, StateSubscriber, PeerSubscriber) wrap
`redis.asyncio` pubsub for the inbound channels. Each exposes a `run()`
coroutine intended to be scheduled as a background task by the runtime,
and a `stop()` coroutine for shutdown.
"""
from __future__ import annotations

import asyncio
import json
import logging

import numpy as np
import redis as _redis_sync
import redis.asyncio as _redis_async

from shared.contracts.topics import per_drone_camera_channel

logger = logging.getLogger(__name__)


class RedisPublisher:
    """Sync Redis publisher implementing the Publisher Protocol from action.py.

    JSON-encodes the payload and publishes on the channel. Designed for the
    drone agent's outbound side (findings, broadcasts, cmd) — small messages,
    fire-and-forget.
    """

    def __init__(self, client: _redis_sync.Redis):
        self._client = client
        self._closed = False

    def publish(self, channel: str, payload: dict) -> None:
        if self._closed:
            logger.warning("publish on closed RedisPublisher; dropped channel=%s", channel)
            return
        self._client.publish(channel, json.dumps(payload))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._client.close()
        except Exception:
            logger.debug("RedisPublisher close: client already closed", exc_info=True)


class CameraSubscriber:
    """Async subscriber for drones.<drone_id>.camera. Decodes JPEG → numpy.

    `latest()` returns the last decoded frame (numpy ndarray, BGR HxWx3) and
    the original JPEG bytes, or None if no valid frame has arrived yet.
    """

    def __init__(self, client: _redis_async.Redis, drone_id: str):
        self._client = client
        self._channel = per_drone_camera_channel(drone_id)
        self._latest: tuple[np.ndarray, bytes] | None = None
        self._stop = asyncio.Event()

    async def run(self) -> None:
        import cv2  # lazy

        pubsub = self._client.pubsub()
        await pubsub.subscribe(self._channel)
        try:
            while not self._stop.is_set():
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
                if msg is None:
                    continue
                data = msg.get("data")
                if not isinstance(data, (bytes, bytearray)):
                    continue
                arr = np.frombuffer(data, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is None:
                    logger.warning("camera: failed to decode JPEG (%d bytes)", len(data))
                    continue
                self._latest = (frame, bytes(data))
        finally:
            await pubsub.unsubscribe(self._channel)
            await pubsub.close()

    def latest(self) -> tuple[np.ndarray, bytes] | None:
        return self._latest

    async def stop(self) -> None:
        self._stop.set()
