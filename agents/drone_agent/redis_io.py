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
from collections import deque

import numpy as np
import redis as _redis_sync
import redis.asyncio as _redis_async

from agents.drone_agent.perception import DroneState
from agents.drone_agent.state_translator import translate_drone_state
from shared.contracts import validate as schema_validate
from shared.contracts.topics import (
    per_drone_camera_channel,
    per_drone_state_channel,
    swarm_visible_to_channel,
)
from sim.scenario import Scenario

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


class StateSubscriber:
    """Async subscriber for drones.<drone_id>.state. Validates Contract 2, translates.

    Caches BOTH the raw sim-published payload (`latest_raw_sim()`) and the
    translated DroneState (`latest()`). The raw cache only updates for payloads
    that look sim-shaped (last_action == "none" AND findings_count == 0) so the
    agent's own republishes never overwrite the sim's kinematic ground truth.
    """

    def __init__(self, client: _redis_async.Redis, drone_id: str, *,
                 zone_bounds: dict, scenario: Scenario):
        self._client = client
        self._drone_id = drone_id
        self._channel = per_drone_state_channel(drone_id)
        self._zone_bounds = zone_bounds
        self._scenario = scenario
        self._latest: DroneState | None = None
        self._latest_raw_sim: dict | None = None
        self._stop = asyncio.Event()

    async def run(self) -> None:
        pubsub = self._client.pubsub()
        await pubsub.subscribe(self._channel)
        try:
            while not self._stop.is_set():
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
                if msg is None:
                    continue
                data = msg.get("data")
                if isinstance(data, (bytes, bytearray)):
                    text = data.decode("utf-8", errors="replace")
                else:
                    text = data
                try:
                    payload = json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    logger.warning("state: malformed JSON dropped")
                    continue
                outcome = schema_validate("drone_state", payload)
                if not outcome.valid:
                    logger.warning("state: schema invalid dropped: %s",
                                   outcome.errors[0].message if outcome.errors else "?")
                    continue
                try:
                    translated = translate_drone_state(
                        payload, zone_bounds=self._zone_bounds, scenario=self._scenario,
                    )
                except KeyError as e:
                    logger.warning("state: translator missing field %s", e)
                    continue
                # Identify sim-shaped payloads so agent republishes never
                # overwrite the kinematic ground truth.
                is_sim_shape = (
                    payload.get("last_action") == "none"
                    and payload.get("findings_count", 0) == 0
                )
                if is_sim_shape:
                    self._latest_raw_sim = payload
                self._latest = translated
        finally:
            await pubsub.unsubscribe(self._channel)
            await pubsub.close()

    def latest(self) -> DroneState | None:
        return self._latest

    def latest_raw_sim(self) -> dict | None:
        """Last sim-shaped payload (agent republishes are filtered out)."""
        return self._latest_raw_sim

    async def stop(self) -> None:
        self._stop.set()


class PeerSubscriber:
    """Async subscriber for swarm.<drone_id>.visible_to.<drone_id>.

    Buffers incoming peer broadcasts in a bounded ring keyed by
    `broadcast_id`. Duplicates (re-deliveries from the mesh layer) are
    silently dropped. The buffer caps at `max_size`; oldest entries fall off.
    """

    def __init__(self, client: _redis_async.Redis, drone_id: str, *, max_size: int = 10):
        self._client = client
        self._channel = swarm_visible_to_channel(drone_id)
        self._buf: deque[dict] = deque(maxlen=max_size)
        self._seen_ids: set[str] = set()
        self._stop = asyncio.Event()

    async def run(self) -> None:
        pubsub = self._client.pubsub()
        await pubsub.subscribe(self._channel)
        try:
            while not self._stop.is_set():
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
                if msg is None:
                    continue
                data = msg.get("data")
                text = data.decode("utf-8", errors="replace") if isinstance(data, (bytes, bytearray)) else data
                try:
                    payload = json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    continue
                bid = payload.get("broadcast_id")
                if not isinstance(bid, str) or bid in self._seen_ids:
                    continue
                self._seen_ids.add(bid)
                self._buf.append(payload)
        finally:
            await pubsub.unsubscribe(self._channel)
            await pubsub.close()

    def recent(self) -> list[dict]:
        return list(self._buf)

    async def stop(self) -> None:
        self._stop.set()
