"""FastAPI WebSocket bridge — Phase 1A skeleton (no Redis yet).

Pushes a state_update envelope to all connected clients every 1 second.
Every envelope is schema-valid against shared/schemas/websocket_messages.json
and stamped with the contract_version from shared/VERSION.

Wire into Redis in Phase 2; for now, this lets Person 4 build the Flutter
dashboard against a moving target without waiting for Person 3's EGS to ship.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from shared.contracts import VERSION, validate

# ---- envelope construction --------------------------------------------------

_FIXTURE_PATH = (
    Path(__file__).parent.parent.parent
    / "shared" / "schemas" / "fixtures" / "valid"
    / "websocket_messages" / "01_state_update.json"
)
_SEED: Dict[str, Any] = json.loads(_FIXTURE_PATH.read_text())
_EPOCH = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def _iso_ms(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def build_state_update_envelope(*, tick: int) -> Dict[str, Any]:
    """Return a schema-valid state_update envelope. Mutates timestamp per tick.

    Phase 1A keeps the embedded egs_state / active_findings / active_drones
    payloads stable from the seed fixture — those will be real once Phase 2
    wires Redis. The job here is to produce a moving-but-valid envelope so the
    dashboard sees per-second activity.
    """
    now = _EPOCH + timedelta(seconds=tick)
    iso = _iso_ms(now)
    env: Dict[str, Any] = json.loads(json.dumps(_SEED))  # deep copy
    env["timestamp"] = iso
    env["contract_version"] = VERSION
    if "egs_state" in env and "timestamp" in env["egs_state"]:
        env["egs_state"]["timestamp"] = iso
    return env


# ---- connection registry ----------------------------------------------------

class _ConnectionRegistry:
    def __init__(self) -> None:
        self._clients: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def add(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.add(ws)

    async def remove(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, message: Dict[str, Any]) -> None:
        # Snapshot under lock to avoid mutation during iteration.
        async with self._lock:
            targets = list(self._clients)
        encoded = json.dumps(message)
        dead: List[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_text(encoded)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)


# ---- broadcast loop ---------------------------------------------------------

async def _ticker(registry: _ConnectionRegistry, *, interval_s: float = 1.0) -> None:
    tick = 0
    while True:
        env = build_state_update_envelope(tick=tick)
        # Defensive: never publish an invalid envelope.
        outcome = validate("websocket_messages", env)
        if outcome.valid:
            await registry.broadcast(env)
        else:
            # Self-test failure: log and skip rather than push junk to clients.
            print(
                f"[ws_bridge] WARN: envelope failed validation at tick {tick}: {outcome.errors}"
            )
        tick += 1
        await asyncio.sleep(interval_s)


# ---- app --------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    registry: _ConnectionRegistry = app.state.registry  # type: ignore[attr-defined]
    task = asyncio.create_task(_ticker(registry))
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    app = FastAPI(title="FieldAgent WS Bridge (Phase 1A)", lifespan=lifespan)
    app.state.registry = _ConnectionRegistry()

    @app.get("/health")
    async def health() -> Dict[str, str]:
        return {"status": "ok", "contract_version": VERSION}

    @app.websocket("/")
    async def ws_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        registry: _ConnectionRegistry = app.state.registry
        await registry.add(websocket)
        try:
            # Send an immediate envelope on connect so the dashboard renders
            # without waiting up to 1 second.
            await websocket.send_text(json.dumps(build_state_update_envelope(tick=0)))
            while True:
                # We accept inbound messages (operator commands etc.) but Phase 1A
                # just echoes them back to confirm the round-trip is wired.
                msg = await websocket.receive_text()
                await websocket.send_text(
                    json.dumps({"type": "echo", "received": msg, "contract_version": VERSION})
                )
        except WebSocketDisconnect:
            pass
        finally:
            await registry.remove(websocket)

    return app


app = create_app()
