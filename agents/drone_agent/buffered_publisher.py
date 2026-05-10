"""BufferedPublisher — drone-side publisher that buffers while standalone.

Wraps any `Publisher` (Protocol from `agents.drone_agent.action`) and
intercepts publishes on channels selected by the `should_buffer` predicate
when the drone is operating standalone (EGS link severed). On link restore
(set_standalone(False)), the buffer is drained to the inner publisher in
strict FIFO order so the EGS sees exactly the same sequence the drone
produced — just delayed.

This module deliberately does NOT detect link state. The runtime owns that
(eventually via Wave 2 Lane E's LinkStateMonitor). For now `set_standalone`
is the sole toggle; tests flip it directly.

Design rationale (from /plan-eng-review):
  - Decoupled from MemoryStore so counter durability (Lane B) and buffer
    persistence (this module) evolve independently. (finding #5)
  - `should_buffer` is INJECTED rather than hardcoded so the policy is
    visible in wiring code; default keeps the common case ergonomic.
    (finding #6 — explicit > clever)
"""
from __future__ import annotations

import logging
from typing import Callable

from agents.drone_agent.action import Publisher
from agents.drone_agent.finding_buffer import FindingBuffer

logger = logging.getLogger(__name__)


def _default_should_buffer(channel: str) -> bool:
    """By default, buffer ONLY drones.<id>.findings.

    Peer broadcasts (`swarm.*`) and command channels (`drones.<id>.cmd`) pass
    through even while standalone — they're either local-mesh-scoped or
    operator-scoped and don't share the EGS link's failure mode.
    """
    return channel.endswith(".findings")


class BufferedPublisher:
    """Publisher that buffers when standalone, flushes on link restore.

    Only buffers channels for which `should_buffer(channel)` returns True.
    Other channels pass through to `inner` even while standalone.
    """

    def __init__(
        self,
        inner: Publisher,
        buffer: FindingBuffer,
        should_buffer: Callable[[str], bool] = _default_should_buffer,
    ):
        self._inner = inner
        self._buffer = buffer
        self._should_buffer = should_buffer
        self._is_standalone = False

    @property
    def is_standalone(self) -> bool:
        return self._is_standalone

    def publish(self, channel: str, payload: dict) -> None:
        if self._is_standalone and self._should_buffer(channel):
            self._buffer.append(channel, payload)
            logger.debug(
                "BufferedPublisher: buffered (standalone) channel=%s buffer_len=%d",
                channel,
                len(self._buffer),
            )
            return
        self._inner.publish(channel, payload)

    def set_standalone(self, value: bool) -> None:
        """Toggle standalone mode.

        On a True→False transition, drain the buffer and publish each entry
        through the inner publisher in FIFO order.
        Idempotent: setting the same value twice is a no-op.
        """
        if value == self._is_standalone:
            return
        self._is_standalone = value
        if value is False:
            entries = self._buffer.drain()
            if entries:
                logger.info(
                    "BufferedPublisher: link restored — flushing %d buffered entries",
                    len(entries),
                )
            for channel, payload in entries:
                self._inner.publish(channel, payload)

    def close(self) -> None:
        """Close the inner publisher.

        Buffered entries on disk are NOT cleared — a subsequent process can
        instantiate a fresh BufferedPublisher pointing at the same persist_path,
        call `restore_from_disk()`, and replay them via set_standalone(False).
        """
        close = getattr(self._inner, "close", None)
        if callable(close):
            close()
