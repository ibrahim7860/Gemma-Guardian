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
from typing import Callable

import numpy as np
import redis as _redis_sync
import redis.asyncio as _redis_async

from agents.drone_agent.perception import DroneState
from agents.drone_agent.state_translator import translate_drone_state
from agents.drone_agent.zone_provider import ZoneProvider
from shared.contracts import validate as schema_validate
from shared.contracts.topics import (
    EGS_STATE,
    MESH_LINK_STATUS,
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
                 zone_provider: ZoneProvider, scenario: Scenario):
        self._client = client
        self._drone_id = drone_id
        self._channel = per_drone_state_channel(drone_id)
        self._zone_provider = zone_provider
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
                        payload,
                        zone_bounds=self._zone_provider.current(),
                        scenario=self._scenario,
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


class EgsStateSubscriber:
    """Async subscriber for `egs.state`. Pushes `zone_polygon` into a ZoneProvider.

    Per `docs/plans/2026-05-13-drone-zone-from-egs-state.md`: the drone agent
    no longer derives its survey bbox from the scenario YAML at boot. Instead,
    the EGS publishes a mission-wide `zone_polygon` on `egs.state`, and this
    subscriber feeds every valid one into the runtime's shared `ZoneProvider`
    so `ValidationNode._within_zone` evaluates against the canonical
    mission zone.
    """

    def __init__(self, client: _redis_async.Redis, zone_provider: ZoneProvider):
        self._client = client
        self._channel = EGS_STATE
        self._zone_provider = zone_provider
        self._stop = asyncio.Event()
        self._first_update_logged = False

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
                    logger.warning("egs_state: malformed JSON dropped")
                    continue
                outcome = schema_validate("egs_state", payload)
                if not outcome.valid:
                    logger.warning(
                        "egs_state: schema invalid dropped: %s",
                        outcome.errors[0].message if outcome.errors else "?",
                    )
                    continue
                # Only honor zone updates from an active mission; a completed
                # or aborted mission may still ship its last-known polygon and
                # we don't want a post-mission state to redefine the zone.
                if payload.get("mission_status") != "active":
                    continue
                polygon = payload.get("zone_polygon")
                if not self._zone_provider.update_from_polygon(polygon):
                    continue
                if not self._first_update_logged:
                    logger.info("egs_state: first zone_polygon applied to ZoneProvider")
                    self._first_update_logged = True
        finally:
            await pubsub.unsubscribe(self._channel)
            await pubsub.close()

    async def stop(self) -> None:
        self._stop.set()


class LinkStatusSubscriber:
    """Async subscriber for `mesh.link_status`. Filters by drone_id.

    Beat 5 Path A-full Component 2 (Wave 2 Lane E). Lane D publishes a
    single shared `mesh.link_status` channel covering all drones; this
    subscriber drops any payload whose `drone_id` is not ours, validates
    the in-scope ones against the `mesh_link_status` schema, and on a
    valid event invokes `on_link_event(link)` so the runtime can update
    its `LinkStateMonitor` and reconcile `BufferedPublisher`.
    """

    def __init__(
        self,
        client: _redis_async.Redis,
        drone_id: str,
        on_link_event: Callable[[str], None],
    ):
        self._client = client
        self._drone_id = drone_id
        self._channel = MESH_LINK_STATUS
        self._on_link_event = on_link_event
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
                    logger.warning("link_status: malformed JSON dropped")
                    continue
                if not isinstance(payload, dict):
                    continue
                # Filter to events for *our* drone before paying schema cost.
                if payload.get("drone_id") != self._drone_id:
                    continue
                outcome = schema_validate("mesh_link_status", payload)
                if not outcome.valid:
                    logger.warning(
                        "link_status: schema invalid dropped: %s",
                        outcome.errors[0].message if outcome.errors else "?",
                    )
                    continue
                link = payload.get("link")
                if not isinstance(link, str):
                    continue
                try:
                    self._on_link_event(link)
                except Exception:
                    logger.exception("link_status: callback raised; continuing")
        finally:
            await pubsub.unsubscribe(self._channel)
            await pubsub.close()

    async def stop(self) -> None:
        self._stop.set()
