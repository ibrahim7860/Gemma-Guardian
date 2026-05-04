"""Phase 2 Redis subscribe loop for the WebSocket bridge.

Owns one asyncio task that connects to Redis, psubscribes to the channels the
bridge cares about, validates each inbound payload against its contract
schema, and dispatches valid payloads into a `StateAggregator`. Invalid JSON
or schema-invalid payloads are dropped and reported via
`ValidationEventLogger`.

The subscriber runs in an outer reconnect loop with exponential backoff so a
Redis outage at startup or mid-stream simply pauses delivery without crashing
the bridge process. The Phase 1A WebSocket emit loop continues to broadcast
the seeded `state_update` envelope while the subscriber retries.

Channel-to-schema mapping:
- ``egs.state`` -> ``egs_state`` -> ``aggregator.update_egs_state``
- ``drones.<id>.state`` -> ``drone_state`` -> ``aggregator.update_drone_state``
- ``drones.<id>.findings`` -> ``finding`` -> ``aggregator.add_finding``

Channel constants come from ``shared.contracts.topics``; subscribe patterns
are derived by replacing ``{drone_id}`` with ``*``. Do not hard-code channel
strings.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional, Tuple

import redis.asyncio as redis_async
from redis.exceptions import RedisError

from shared.contracts import topics, validate
from shared.contracts.logging import ValidationEventLogger

from frontend.ws_bridge.aggregator import StateAggregator
from frontend.ws_bridge.config import BridgeConfig

_LOG = logging.getLogger(__name__)

# Subscribe patterns derived from the locked topic constants. We use
# psubscribe for the per-drone wildcard channels; the literal ``egs.state`` is
# subscribed via plain ``subscribe`` (it carries no glob metacharacters).
_DRONE_STATE_PATTERN: str = topics.PER_DRONE_STATE.replace("{drone_id}", "*")
_DRONE_FINDINGS_PATTERN: str = topics.PER_DRONE_FINDINGS.replace("{drone_id}", "*")
_EGS_STATE_CHANNEL: str = topics.EGS_STATE
_EGS_COMMAND_TRANSLATIONS_CHANNEL: str = topics.EGS_COMMAND_TRANSLATIONS

# Polling timeout for ``pubsub.get_message``. Small enough that the loop
# checks ``self._stopping`` frequently for clean shutdown; large enough that
# we don't spin a hot loop on an idle channel.
_GET_MESSAGE_TIMEOUT_S: float = 0.1


def _next_backoff(current: float, cap: float) -> float:
    """Double the current backoff, capped at ``cap``. Pure helper for testability."""
    if current <= 0:
        return min(1.0, cap)
    return min(current * 2.0, cap)


def _classify_channel(channel: str) -> Tuple[Optional[str], Optional[str]]:
    """Map a raw Redis channel name to (schema_name, drone_id_or_none).

    Returns ``(None, None)`` for channels we don't handle. ``drone_id`` is
    returned only for per-drone channels and is the second dotted segment.
    """
    if channel == _EGS_STATE_CHANNEL:
        return "egs_state", None
    if channel == _EGS_COMMAND_TRANSLATIONS_CHANNEL:
        return "command_translations_envelope", None
    if channel.startswith("drones.") and channel.endswith(".state"):
        parts = channel.split(".")
        if len(parts) == 3:
            return "drone_state", parts[1]
    if channel.startswith("drones.") and channel.endswith(".findings"):
        parts = channel.split(".")
        if len(parts) == 3:
            return "finding", parts[1]
    return None, None


class RedisSubscriber:
    """Async Redis subscribe loop with reconnect/backoff.

    Lifecycle:
      * Construct with a ``BridgeConfig``, a ``StateAggregator``, and a
        ``ValidationEventLogger``.
      * Start with ``asyncio.create_task(subscriber.run())``.
      * Stop with ``subscriber.signal_stop()``, await the task, then ``await subscriber.close()``.
    """

    def __init__(
        self,
        *,
        config: BridgeConfig,
        aggregator: StateAggregator,
        validation_logger: ValidationEventLogger,
        translation_queue: Optional[asyncio.Queue] = None,
    ) -> None:
        self._config: BridgeConfig = config
        self._aggregator: StateAggregator = aggregator
        self._validation_logger: ValidationEventLogger = validation_logger
        # Adversarial finding #1 / spec §5.1: command_translations are not
        # broadcast synchronously from this loop. Instead, the subscriber
        # ``put_nowait`` onto this queue and a dedicated lifespan task in
        # ``main.py`` drains and broadcasts. A slow WS client therefore
        # cannot back-pressure Redis ingestion (which would otherwise risk
        # Redis disconnecting us as a slow consumer).
        self._translation_queue: Optional[asyncio.Queue] = translation_queue
        self._stopping: bool = False
        # Held across reconnect attempts so ``close()`` can tear them down.
        self._client: Optional[redis_async.Redis] = None
        self._pubsub: Optional[Any] = None

    # ---- public API -------------------------------------------------------

    async def run(self) -> None:
        """Run the connect / subscribe / dispatch loop until ``signal_stop()``.

        Outer try catches RedisError + ConnectionError to drive reconnect with
        exponential backoff. Backoff resets to 0 after a successful connect
        (i.e., once we've made it through psubscribe without raising).
        """
        backoff: float = 0.0
        while not self._stopping:
            try:
                await self._connect_and_dispatch()
                # Clean exit (signal_stop() was called) — leave the loop.
                if self._stopping:
                    return
                # Loop body returned without an exception and without stopping;
                # treat as a transient and retry on the next iteration.
                backoff = _next_backoff(backoff, self._config.reconnect_max_s)
            except (RedisError, ConnectionError, OSError) as exc:
                if self._stopping:
                    return
                _LOG.warning(
                    "RedisSubscriber: connection error (%s: %s); reconnecting in %.2fs",
                    type(exc).__name__, exc, max(backoff, 0.1),
                )
                await asyncio.sleep(max(backoff, 0.1))
                backoff = _next_backoff(backoff, self._config.reconnect_max_s)
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover — defensive
                _LOG.exception("RedisSubscriber: unexpected error; reconnecting")
                await asyncio.sleep(max(backoff, 0.1))
                backoff = _next_backoff(backoff, self._config.reconnect_max_s)

    def signal_stop(self) -> None:
        """Set the stop flag. Does NOT close the pubsub.

        The run loop checks ``self._stopping`` on every iteration of
        ``_connect_and_dispatch``'s read loop and on every iteration of
        ``run()``'s reconnect loop. Once this is True, the run task
        exits cleanly on its next read-timeout boundary
        (``_GET_MESSAGE_TIMEOUT_S``).

        Synchronous so callers can fire it from a non-async context
        (e.g., signal handlers) without ceremony.
        """
        self._stopping = True

    async def close(self) -> None:
        """Tear down the pubsub and client. Idempotent.

        Must be called AFTER the run task has exited; otherwise the run
        task may be mid-``pubsub.get_message()`` when ``aclose()`` runs,
        producing ``RuntimeError: Event loop is closed`` on shutdown.
        """
        pubsub = self._pubsub
        client = self._client
        self._pubsub = None
        self._client = None
        if pubsub is not None:
            try:
                await pubsub.unsubscribe()
            except Exception:
                pass
            try:
                await pubsub.punsubscribe()
            except Exception:
                pass
            try:
                await pubsub.aclose()
            except Exception:
                pass
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass

    # ---- internals --------------------------------------------------------

    async def _connect_and_dispatch(self) -> None:
        """One connect + subscribe + read-loop attempt. Raises on failure.

        Resets the per-attempt backoff implicitly: by the time control reaches
        the read loop, the connection succeeded; an exception from inside the
        loop propagates to ``run()`` which decides whether to back off.
        """
        client = redis_async.Redis.from_url(self._config.redis_url)
        self._client = client
        pubsub = client.pubsub()
        self._pubsub = pubsub

        await pubsub.subscribe(
            _EGS_STATE_CHANNEL, _EGS_COMMAND_TRANSLATIONS_CHANNEL,
        )
        await pubsub.psubscribe(_DRONE_STATE_PATTERN)
        await pubsub.psubscribe(_DRONE_FINDINGS_PATTERN)

        # Read loop: poll get_message so the loop checks self._stopping
        # frequently (vs. ``async for ... in pubsub.listen()`` which can park
        # indefinitely on an idle channel).
        while not self._stopping:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=_GET_MESSAGE_TIMEOUT_S,
            )
            if message is None:
                continue
            await self._handle_message(message)

    async def _handle_message(self, message: Dict[str, Any]) -> None:
        """Decode one pubsub message and dispatch into the aggregator.

        Catches and reports both JSON parse errors and schema-validation
        failures via ``ValidationEventLogger``. Never raises.
        """
        channel_raw = message.get("channel")
        if isinstance(channel_raw, (bytes, bytearray)):
            channel = channel_raw.decode("utf-8", errors="replace")
        else:
            channel = str(channel_raw) if channel_raw is not None else ""

        schema_name, drone_id = _classify_channel(channel)
        if schema_name is None:
            _LOG.warning("RedisSubscriber: unhandled channel %r; dropping", channel)
            return

        data_raw = message.get("data")
        if isinstance(data_raw, (bytes, bytearray)):
            data_bytes = bytes(data_raw)
        elif isinstance(data_raw, str):
            data_bytes = data_raw.encode("utf-8")
        else:
            data_bytes = b""

        # ---- decode --------------------------------------------------------
        try:
            payload = json.loads(data_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._log_validation_failure(
                schema_name=schema_name,
                drone_id=drone_id,
                channel=channel,
                rule_id="STRUCTURAL_VALIDATION_FAILED",
                detail=f"json_decode_error: {exc}",
                raw_call=None,
            )
            return

        if not isinstance(payload, dict):
            self._log_validation_failure(
                schema_name=schema_name,
                drone_id=drone_id,
                channel=channel,
                rule_id="STRUCTURAL_VALIDATION_FAILED",
                detail=f"payload_root_not_object: {type(payload).__name__}",
                raw_call=None,
            )
            return

        # ---- validate ------------------------------------------------------
        outcome = validate(schema_name, payload)
        if not outcome.valid:
            first_err = outcome.errors[0] if outcome.errors else None
            detail = (
                f"{first_err.field_path}: {first_err.message}"
                if first_err is not None else "schema_invalid"
            )
            self._log_validation_failure(
                schema_name=schema_name,
                drone_id=drone_id,
                channel=channel,
                rule_id="STRUCTURAL_VALIDATION_FAILED",
                detail=detail,
                raw_call=payload,
            )
            return

        # ---- dispatch ------------------------------------------------------
        if schema_name == "egs_state":
            self._aggregator.update_egs_state(payload)
        elif schema_name == "drone_state":
            # drone_id parsed from the channel name is authoritative for the
            # bucket key; payload's drone_id field is validated by the schema.
            assert drone_id is not None  # narrowed by _classify_channel
            self._aggregator.update_drone_state(drone_id, payload)
        elif schema_name == "finding":
            self._aggregator.add_finding(payload)
        elif schema_name == "command_translations_envelope":
            # Strip bridge-only fields and re-shape ``kind`` -> ``type`` for
            # the WS contract. Then enqueue for the broadcaster task. We do
            # NOT call ``registry.broadcast`` here — see the constructor
            # docstring on ``_translation_queue`` for the rationale.
            if self._translation_queue is not None:
                ws_frame: Dict[str, Any] = {
                    "type": "command_translation",
                    "command_id": payload["command_id"],
                    "structured": payload["structured"],
                    "valid": payload["valid"],
                    "preview_text": payload["preview_text"],
                    "preview_text_in_operator_language": payload[
                        "preview_text_in_operator_language"
                    ],
                    "contract_version": payload["contract_version"],
                }
                try:
                    self._translation_queue.put_nowait(ws_frame)
                except asyncio.QueueFull:
                    # Adversarial finding #1: under broadcaster slowness,
                    # drop the OLDEST queued translation so the subscriber
                    # keeps draining Redis. The operator gets the freshest
                    # translation; back-pressure to Redis is what we must
                    # never tolerate.
                    try:
                        self._translation_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    try:
                        self._translation_queue.put_nowait(ws_frame)
                    except asyncio.QueueFull:
                        # Pathological: still full after evict (race with
                        # another producer). Drop this frame outright and
                        # log so we notice in production.
                        _LOG.warning(
                            "RedisSubscriber: translation queue persistently "
                            "full; dropped command_id=%s",
                            payload.get("command_id"),
                        )
        # else: unreachable — _classify_channel returned a known schema_name.

    def _log_validation_failure(
        self,
        *,
        schema_name: str,
        drone_id: Optional[str],
        channel: str,
        rule_id: str,
        detail: str,
        raw_call: Optional[Dict[str, Any]],
    ) -> None:
        """Best-effort write to the validation event log.

        Schema constraint: ``agent_id`` must be a drone_id or the literal
        ``"egs"``; ``layer`` must be ``drone`` / ``egs`` / ``operator``. We
        attribute drone-channel failures to the source drone and EGS-channel
        failures to ``egs``. ``raw_call`` carries the offending payload (or
        None for JSON-decode errors). The channel name and detail are folded
        into ``function_or_command`` so downstream readers can grep them.
        """
        if drone_id is not None:
            agent_id = drone_id
            layer = "drone"
        else:
            agent_id = "egs"
            layer = "egs"
        try:
            self._validation_logger.log(
                agent_id=agent_id,
                layer=layer,
                function_or_command=f"{schema_name}@{channel}: {detail}",
                attempt=1,
                valid=False,
                rule_id=rule_id,
                outcome="failed_after_retries",
                raw_call=raw_call,
            )
        except Exception:  # pragma: no cover — never let logging crash dispatch
            _LOG.exception("RedisSubscriber: failed to write validation event")
