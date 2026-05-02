"""Phase 3 outbound Redis publisher for the WebSocket bridge.

Mirrors the lifecycle pattern used by ``RedisSubscriber``: one client per
publisher instance, opened lazily on the first ``publish()`` call, closed
once on ``close()``. ``publish()`` JSON-encodes the payload and forwards to
``redis.asyncio.Redis.publish``. Connection / publish errors propagate to the
caller so the bridge can surface them to the operator via an error echo.

Concurrency: ``publish()`` is safe to call from multiple coroutines; the
lazy-init guard is protected by an ``asyncio.Lock`` so racing first-callers
share a single Redis client instance instead of orphaning one.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional

import redis.asyncio as redis_async

_LOG = logging.getLogger(__name__)


class RedisPublisher:
    """Async Redis publisher with lazy connect and idempotent close."""

    def __init__(self, *, redis_url: str) -> None:
        self._redis_url: str = redis_url
        self._client: Optional[redis_async.Redis] = None
        self._init_lock: asyncio.Lock = asyncio.Lock()

    async def publish(self, channel: str, payload: Dict[str, Any]) -> None:
        """JSON-encode ``payload`` and publish to ``channel``.

        Opens a Redis client on first call (under a lock to prevent races
        between concurrent first-callers) and reuses it for subsequent calls.
        On any exception during publish, the client is closed and nulled out
        so the next call lazy-reconnects. Without this, a transient Redis
        outage would brick every subsequent publish until the bridge restarts.
        Raises ``redis.exceptions.RedisError`` on connection failures.
        """
        if self._client is None:
            async with self._init_lock:
                if self._client is None:
                    self._client = redis_async.Redis.from_url(self._redis_url)
        encoded = json.dumps(payload)
        try:
            await self._client.publish(channel, encoded)
        except Exception:
            client = self._client
            self._client = None
            if client is not None:
                try:
                    await client.aclose()
                except Exception as exc:
                    _LOG.debug(
                        "RedisPublisher: aclose during error recovery failed: %s",
                        exc, exc_info=True,
                    )
            raise

    async def close(self) -> None:
        """Dispose of the client. Idempotent and safe pre-publish."""
        client = self._client
        self._client = None
        if client is not None:
            try:
                await client.aclose()
            except Exception as exc:
                _LOG.debug(
                    "RedisPublisher: aclose failed: %s", exc, exc_info=True,
                )
