"""FastAPI WebSocket bridge — Phase 2 + 3.

Wires together:

  * ``BridgeConfig``       — env-driven tunables.
  * ``StateAggregator``    — three-bucket in-memory state (egs / drones / findings).
  * ``RedisSubscriber``    — psubscribes to egs.state, drones.*.state,
                              drones.*.findings; validates and dispatches into
                              the aggregator.
  * ``RedisPublisher``     — Phase 3 outbound: republishes validated operator
                              approvals to ``egs.operator_actions``.
  * ``_emit_loop``         — reads ``aggregator.snapshot()`` at ``BRIDGE_TICK_S``
                              and broadcasts to all WS clients.
  * ``_ConnectionRegistry``— per-client send with timeout, parallel via
                              ``asyncio.gather`` (eng-review fix 1A).

Inbound ``operator_command`` frames are validated and echoed back (full
multilingual translation path lands in Phase 4 with the EGS).
Inbound ``finding_approval`` frames (Phase 3) are validated, stamped with a
bridge-side timestamp, defensively re-validated against ``operator_actions``,
republished to Redis, and acked back to the operator.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from shared.contracts import VERSION, validate
from shared.contracts.logging import ValidationEventLogger, setup_logging

from frontend.ws_bridge.aggregator import StateAggregator
from frontend.ws_bridge.config import BridgeConfig
from frontend.ws_bridge.redis_publisher import RedisPublisher
from frontend.ws_bridge.redis_subscriber import RedisSubscriber

# ---- helpers ---------------------------------------------------------------

_FIXTURE_PATH = (
    Path(__file__).parent.parent.parent
    / "shared" / "schemas" / "fixtures" / "valid"
    / "websocket_messages" / "01_state_update.json"
)


def _load_seed_envelope() -> Dict[str, Any]:
    return json.loads(_FIXTURE_PATH.read_text())


def _now_iso_ms() -> str:
    """Return current UTC time formatted as iso_timestamp_utc_ms (per _common)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


async def _echo_error(
    websocket: WebSocket,
    *,
    error: str,
    detail: Optional[List[str]] = None,
    command_id: Optional[str] = None,
    finding_id: Optional[str] = None,
) -> None:
    """Send a uniformly-shaped error echo back to the WS client.

    All bridge-side rejections (schema invalid, internal validation failure,
    Redis publish failure) go through this helper so Flutter can branch on
    the ``error`` field without per-error-type parsing.
    """
    payload: Dict[str, Any] = {
        "type": "echo",
        "error": error,
        "contract_version": VERSION,
    }
    if detail is not None:
        payload["detail"] = detail
    if command_id is not None:
        payload["command_id"] = command_id
    if finding_id is not None:
        payload["finding_id"] = finding_id
    await websocket.send_text(json.dumps(payload))


# ---- connection registry ---------------------------------------------------


class _ConnectionRegistry:
    """Thread-safe (asyncio-safe) WS client registry with parallel broadcast.

    Each client receives the broadcast in its own ``asyncio`` task wrapped in
    ``asyncio.wait_for`` with ``broadcast_timeout_s``. A slow or dead client is
    dropped without blocking the other clients (eng-review finding 1A).
    """

    def __init__(self, *, broadcast_timeout_s: float) -> None:
        self._clients: Set[WebSocket] = set()
        self._lock: asyncio.Lock = asyncio.Lock()
        self._send_timeout_s: float = broadcast_timeout_s

    async def add(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.add(ws)

    async def remove(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, message: Dict[str, Any]) -> None:
        async with self._lock:
            targets: List[WebSocket] = list(self._clients)
        if not targets:
            return
        encoded = json.dumps(message)

        async def _send(ws: WebSocket) -> Optional[WebSocket]:
            try:
                await asyncio.wait_for(ws.send_text(encoded), timeout=self._send_timeout_s)
                return None
            except Exception:
                return ws

        results = await asyncio.gather(*[_send(ws) for ws in targets], return_exceptions=False)
        dead = [ws for ws in results if ws is not None]
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)


# ---- emit loop -------------------------------------------------------------


async def _emit_loop(
    *,
    registry: _ConnectionRegistry,
    aggregator: StateAggregator,
    tick_s: float,
) -> None:
    """Read aggregator snapshot at ``tick_s`` Hz and broadcast.

    Stamps ``contract_version`` from ``shared.contracts.VERSION`` on the way
    out (single source of truth at runtime). Validates the envelope against
    ``websocket_messages`` before broadcast; never publishes invalid output.
    A self-validation failure is a bridge bug, not upstream noise — log to
    stderr and skip the tick.
    """
    while True:
        try:
            env = aggregator.snapshot(timestamp_iso=_now_iso_ms())
            env["contract_version"] = VERSION
            outcome = validate("websocket_messages", env)
            if outcome.valid:
                await registry.broadcast(env)
            else:
                print(f"[ws_bridge] BUG: aggregator emitted invalid envelope: {outcome.errors}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Never let one bad tick kill the loop. Without this guard, a
            # single malformed aggregator state silently stops broadcasts
            # forever while WS clients keep connecting and seeing empty.
            print(f"[ws_bridge] _emit_loop tick error (continuing): {type(exc).__name__}: {exc}")
        await asyncio.sleep(tick_s)


# ---- app -------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    config: BridgeConfig = app.state.config
    registry: _ConnectionRegistry = app.state.registry
    aggregator: StateAggregator = app.state.aggregator
    subscriber: RedisSubscriber = app.state.subscriber

    emit_task = asyncio.create_task(
        _emit_loop(registry=registry, aggregator=aggregator, tick_s=config.tick_s)
    )
    subscribe_task = asyncio.create_task(subscriber.run())
    try:
        yield
    finally:
        # Cancel both tasks BEFORE awaiting either. If subscriber.stop()
        # raises, ``await subscribe_task`` would block forever otherwise,
        # hanging FastAPI shutdown until SIGKILL.
        emit_task.cancel()
        subscribe_task.cancel()
        try:
            await subscriber.stop()
        except Exception:
            pass
        for task in (emit_task, subscribe_task):
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        await app.state.publisher.close()


def create_app() -> FastAPI:
    setup_logging("ws_bridge")
    config = BridgeConfig.from_env()
    seed_envelope = _load_seed_envelope()
    aggregator = StateAggregator(
        max_findings=config.max_findings,
        seed_envelope=seed_envelope,
    )
    validation_logger = ValidationEventLogger()
    subscriber = RedisSubscriber(
        config=config,
        aggregator=aggregator,
        validation_logger=validation_logger,
    )
    publisher = RedisPublisher(redis_url=config.redis_url)
    registry = _ConnectionRegistry(broadcast_timeout_s=config.broadcast_timeout_s)

    app = FastAPI(title="FieldAgent WS Bridge (Phase 2)", lifespan=lifespan)
    app.state.config = config
    app.state.aggregator = aggregator
    app.state.subscriber = subscriber
    app.state.registry = registry
    app.state.publisher = publisher

    @app.get("/health")
    async def health() -> Dict[str, str]:
        return {"status": "ok", "contract_version": VERSION}

    @app.websocket("/")
    async def ws_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        await registry.add(websocket)
        try:
            # Send an immediate envelope on connect so the dashboard renders
            # without waiting up to one tick.
            initial = aggregator.snapshot(timestamp_iso=_now_iso_ms())
            initial["contract_version"] = VERSION
            await websocket.send_text(json.dumps(initial))
            while True:
                msg = await websocket.receive_text()
                # Validate inbound. Phase 3: ``finding_approval`` is republished
                # to Redis after validation. Phase 4 will republish
                # ``operator_command`` once the EGS translation path lands.
                # Unknown types fall through to a debug echo.
                try:
                    parsed = json.loads(msg)
                except json.JSONDecodeError:
                    await websocket.send_text(
                        json.dumps({
                            "type": "echo",
                            "error": "invalid_json",
                            "received": msg,
                            "contract_version": VERSION,
                        })
                    )
                    continue
                if isinstance(parsed, dict) and parsed.get("type") == "operator_command":
                    outcome = validate("websocket_messages", parsed)
                    if not outcome.valid:
                        await _echo_error(
                            websocket,
                            error="invalid_operator_command",
                            detail=[e.message for e in outcome.errors],
                            command_id=parsed.get("command_id"),
                        )
                        continue
                    # Phase 4: republish to ``egs.operator_commands`` so the
                    # EGS translator can pick it up and emit a structured
                    # ``command_translation``. The bridge stamps
                    # ``bridge_received_at_iso_ms`` so downstream consumers
                    # can measure end-to-end latency without trusting the
                    # client clock.
                    redis_payload: Dict[str, Any] = {
                        "kind": "operator_command",
                        "command_id": parsed["command_id"],
                        "language": parsed["language"],
                        "raw_text": parsed["raw_text"],
                        "bridge_received_at_iso_ms": _now_iso_ms(),
                        "contract_version": VERSION,
                    }
                    # Defensive: validate the payload we're about to publish.
                    bridge_outcome = validate(
                        "operator_commands_envelope", redis_payload,
                    )
                    if not bridge_outcome.valid:
                        await _echo_error(
                            websocket,
                            error="bridge_internal",
                            detail=[e.message for e in bridge_outcome.errors],
                            command_id=parsed.get("command_id"),
                        )
                        continue
                    try:
                        await app.state.publisher.publish(
                            "egs.operator_commands", redis_payload,
                        )
                    except Exception:
                        # See finding_approval branch — bare ``except
                        # Exception`` is safe here because
                        # ``asyncio.CancelledError`` is a ``BaseException``,
                        # not an ``Exception``.
                        await _echo_error(
                            websocket,
                            error="redis_publish_failed",
                            command_id=parsed.get("command_id"),
                        )
                        continue
                    await websocket.send_text(
                        json.dumps({
                            "type": "echo",
                            "ack": "operator_command_received",
                            "command_id": parsed["command_id"],
                            "contract_version": VERSION,
                        })
                    )
                elif isinstance(parsed, dict) and parsed.get("type") == "finding_approval":
                    outcome = validate("websocket_messages", parsed)
                    if not outcome.valid:
                        await _echo_error(
                            websocket,
                            error="invalid_finding_approval",
                            detail=[e.message for e in outcome.errors],
                            command_id=parsed.get("command_id"),
                            finding_id=parsed.get("finding_id"),
                        )
                        continue
                    # Phase 4: allowlist guard. The bridge's aggregator holds
                    # the canonical "known findings" set (the same set the
                    # dashboard renders). Reject approvals for unknown ids
                    # before publishing to keep the operator-decision audit
                    # trail clean — closes the Phase 3 adversarial finding.
                    if not app.state.aggregator.has_finding(parsed["finding_id"]):
                        await _echo_error(
                            websocket,
                            error="unknown_finding_id",
                            command_id=parsed.get("command_id"),
                            finding_id=parsed.get("finding_id"),
                        )
                        continue
                    redis_payload: Dict[str, Any] = {
                        "kind": "finding_approval",
                        "command_id": parsed["command_id"],
                        "finding_id": parsed["finding_id"],
                        "action": parsed["action"],
                        "bridge_received_at_iso_ms": _now_iso_ms(),
                        "contract_version": VERSION,
                    }
                    # Defensive: validate the payload we're about to publish.
                    bridge_outcome = validate("operator_actions", redis_payload)
                    if not bridge_outcome.valid:
                        await _echo_error(
                            websocket,
                            error="bridge_internal",
                            detail=[e.message for e in bridge_outcome.errors],
                            command_id=parsed.get("command_id"),
                            finding_id=parsed.get("finding_id"),
                        )
                        continue
                    try:
                        await app.state.publisher.publish(
                            "egs.operator_actions", redis_payload,
                        )
                    except Exception:
                        # Python 3.8+ guarantee: asyncio.CancelledError is a
                        # BaseException, NOT a subclass of Exception, so the
                        # bare ``except Exception`` here cannot swallow loop
                        # cancellation. Do not "tighten" this to
                        # ``except (RedisError, Exception)`` — that would
                        # introduce a real CancelledError suppression.
                        await _echo_error(
                            websocket,
                            error="redis_publish_failed",
                            command_id=parsed.get("command_id"),
                            finding_id=parsed.get("finding_id"),
                        )
                        continue
                    await websocket.send_text(
                        json.dumps({
                            "type": "echo",
                            "ack": "finding_approval",
                            "command_id": parsed["command_id"],
                            "finding_id": parsed["finding_id"],
                            "contract_version": VERSION,
                        })
                    )
                else:
                    await websocket.send_text(
                        json.dumps({
                            "type": "echo",
                            "received": parsed,
                            "contract_version": VERSION,
                        })
                    )
        except WebSocketDisconnect:
            pass
        finally:
            await registry.remove(websocket)

    return app


app = create_app()
