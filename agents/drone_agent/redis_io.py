"""Redis I/O — RedisPublisher (sync) + async subscriber helpers.

The sync publisher implements the `Publisher` Protocol from action.py and
is used by ActionNode to emit findings, broadcasts, and cmd messages.

Async subscriber classes (CameraSubscriber, StateSubscriber, PeerSubscriber)
will be added in subsequent tasks to handle the inbound side.
"""
from __future__ import annotations

import json
import logging

import redis as _redis_sync

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
