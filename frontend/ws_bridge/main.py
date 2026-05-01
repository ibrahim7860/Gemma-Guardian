"""FastAPI WebSocket bridge — Phase 2.

Wires together:

  * ``BridgeConfig``       — env-driven tunables.
  * ``StateAggregator``    — three-bucket in-memory state (egs / drones / findings).
  * ``RedisSubscriber``    — psubscribes to egs.state, drones.*.state,
                              drones.*.findings; validates and dispatches into
                              the aggregator.
  * ``_emit_loop``         — reads ``aggregator.snapshot()`` at ``BRIDGE_TICK_S``
                              and broadcasts to all WS clients.
  * ``_ConnectionRegistry``— per-client send with timeout, parallel via
                              ``asyncio.gather`` (eng-review fix 1A).

Inbound operator commands are validated against the
``websocket_messages.operator_command`` branch and echoed back. Real Redis
republish is Phase 3.
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
        env = aggregator.snapshot(timestamp_iso=_now_iso_ms())
        env["contract_version"] = VERSION
        outcome = validate("websocket_messages", env)
        if outcome.valid:
            await registry.broadcast(env)
        else:
            print(f"[ws_bridge] BUG: aggregator emitted invalid envelope: {outcome.errors}")
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
        emit_task.cancel()
        await subscriber.stop()
        for task in (emit_task, subscribe_task):
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


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
    registry = _ConnectionRegistry(broadcast_timeout_s=config.broadcast_timeout_s)

    app = FastAPI(title="FieldAgent WS Bridge (Phase 2)", lifespan=lifespan)
    app.state.config = config
    app.state.aggregator = aggregator
    app.state.subscriber = subscriber
    app.state.registry = registry

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
                # Validate inbound; only operator_command frames are accepted
                # for now (Phase 3 will republish to Redis). Other types echo
                # back with a hint.
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
                    if outcome.valid:
                        # Phase 3 will republish onto Redis. For now, just
                        # acknowledge.
                        await websocket.send_text(
                            json.dumps({
                                "type": "echo",
                                "ack": "operator_command_received",
                                "command_id": parsed.get("command_id"),
                                "contract_version": VERSION,
                            })
                        )
                    else:
                        await websocket.send_text(
                            json.dumps({
                                "type": "echo",
                                "error": "invalid_operator_command",
                                "detail": [e.message for e in outcome.errors],
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
