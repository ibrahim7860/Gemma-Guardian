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
import logging
import os
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

logger = logging.getLogger(__name__)

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
            logger.debug(
                "broadcast: no WS clients registered, dropping frame type=%s",
                message.get("type"),
            )
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
                logger.error("BUG: aggregator emitted invalid envelope: %s", outcome.errors)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Never let one bad tick kill the loop. Without this guard, a
            # single malformed aggregator state silently stops broadcasts
            # forever while WS clients keep connecting and seeing empty.
            logger.warning("_emit_loop tick error (continuing): %s: %s", type(exc).__name__, exc)
        await asyncio.sleep(tick_s)


# ---- app -------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    config: BridgeConfig = app.state.config
    registry: _ConnectionRegistry = app.state.registry
    aggregator: StateAggregator = app.state.aggregator
    subscriber: RedisSubscriber = app.state.subscriber
    translation_broadcaster = app.state.translation_broadcaster
    validation_log_writer = app.state.validation_log_writer
    camera_broadcaster = app.state.camera_broadcaster
    task_broadcaster = app.state.task_broadcaster
    validation_tick_broadcaster = app.state.validation_tick_broadcaster

    emit_task = asyncio.create_task(
        _emit_loop(registry=registry, aggregator=aggregator, tick_s=config.tick_s)
    )
    subscribe_task = asyncio.create_task(subscriber.run())
    # Adversarial finding #1: command_translations are enqueued by the
    # subscriber and broadcast by this dedicated task. Decoupling means a
    # slow WS client cannot stall the Redis subscribe loop.
    translation_task = asyncio.create_task(translation_broadcaster())
    # Eng-review 2A: validation log events are enqueued by the dispatch path
    # (put_nowait) and written to disk by this dedicated task. Decoupling
    # means slow disk I/O cannot back-pressure the Redis subscribe loop.
    validation_log_task = asyncio.create_task(validation_log_writer())
    # Path γ-lite: camera broadcaster — drains binary frames from camera_queue
    # and broadcasts base64-encoded WS frames at ≤ 1 fps per drone.
    camera_task = asyncio.create_task(camera_broadcaster())
    # Path γ-MAX++: task assignment broadcaster + validation event tailer.
    task_task = asyncio.create_task(task_broadcaster())
    validation_tick_task = asyncio.create_task(validation_tick_broadcaster())
    try:
        yield
    finally:
        # Phase 5+ teardown ordering. The old sequence
        # (cancel → subscriber.stop → await tasks) closed the
        # subscriber's pubsub while the subscribe task was still mid-
        # ``pubsub.get_message()``, producing
        # ``RuntimeError: Event loop is closed`` on every shutdown.
        #
        # New order (eng-review 1B + 2A):
        #   1. Flip the subscriber's stop flag (NO pubsub close yet)
        #   2. Cancel ALL FOUR tasks. signal_stop gives the subscribe
        #      loop a clean exit on its next read-timeout; cancel()
        #      handles the case where get_message() is parked.
        #   3. Await ALL FOUR tasks so the subscribe task has fully
        #      exited its read loop before we touch its pubsub
        #   4. ONLY THEN close the subscriber (pubsub.aclose())
        #   5. Close the publisher
        subscriber.signal_stop()
        emit_task.cancel()
        subscribe_task.cancel()
        translation_task.cancel()
        validation_log_task.cancel()
        camera_task.cancel()
        task_task.cancel()
        validation_tick_task.cancel()
        for task in (
            emit_task, subscribe_task, translation_task, validation_log_task, camera_task, task_task, validation_tick_task,
        ):
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        # Tear down pubsub AFTER the subscribe task has exited so we never
        # call aclose() while the task is mid-get_message (which produced
        # "RuntimeError: Event loop is closed" on stderr in previous builds).
        try:
            await subscriber.close()
        except Exception:
            pass
        # Wrap publisher.close() defensively — any exception here would
        # leak to FastAPI shutdown after we've already torn down the
        # background tasks that depend on it.
        try:
            await app.state.publisher.close()
        except Exception:
            pass


def create_app() -> FastAPI:
    setup_logging("ws_bridge")
    config = BridgeConfig.from_env()
    seed_envelope = _load_seed_envelope()
    aggregator = StateAggregator(
        max_findings=config.max_findings,
        seed_envelope=seed_envelope,
        demo_autoapprove_victims=True,
    )
    validation_logger = ValidationEventLogger()

    # Registry must be constructed BEFORE the broadcaster closure that
    # captures it, and BEFORE the subscriber that shares the translation
    # queue with the broadcaster.
    registry = _ConnectionRegistry(broadcast_timeout_s=config.broadcast_timeout_s)

    # Adversarial finding #1 / spec §5.1: bounded queue between subscriber
    # and broadcaster. ``maxsize=64`` is generous for the bursty
    # operator-translation traffic pattern; the subscriber's
    # drop-oldest-on-full policy provides hard back-pressure relief.
    translation_queue: asyncio.Queue = asyncio.Queue(maxsize=64)

    # Path γ-lite: camera frame pipeline. maxsize=16 because we throttle to
    # 1 fps/drone in the broadcaster anyway.
    camera_queue: asyncio.Queue = asyncio.Queue(maxsize=16)

    # Path γ-MAX++: EGS task assignments + validation event ticker queues.
    task_queue: asyncio.Queue = asyncio.Queue(maxsize=32)
    validation_tick_queue: asyncio.Queue = asyncio.Queue(maxsize=64)

    async def _translation_broadcaster_loop() -> None:
        """Drain ``translation_queue`` and broadcast via ``registry``.

        Owns slowness: if a WS client is slow, this task waits — but the
        subscriber and ``_emit_loop`` keep running. Same defensive
        try/except shape as ``_emit_loop`` so a single bad frame never
        kills the broadcaster.
        """
        while True:
            try:
                frame = await translation_queue.get()
            except asyncio.CancelledError:
                raise
            try:
                # Defense in depth: re-validate the post-strip frame
                # against the WS contract before broadcasting. If the
                # subscriber's strip logic ever produces an invalid frame
                # (a bridge bug), drop it with a log line rather than
                # corrupt the WS clients.
                outcome = validate("websocket_messages", frame)
                if not outcome.valid:
                    print(f"[CMD-TRANS] DROP post-validate: {outcome.errors[0].message if outcome.errors else '?'} frame={frame}", flush=True)
                    continue
                print(f"[CMD-TRANS] BROADCAST cmd_id={frame.get('command_id')}", flush=True)
                await registry.broadcast(frame)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # A single bad frame must not kill the broadcaster.
                logger.warning(
                    "translation_broadcaster tick error (continuing): %s: %s",
                    type(exc).__name__,
                    exc,
                )

    # Eng-review 2A: bounded queue between dispatch and disk-write.
    # ``maxsize=128`` is generous for the validation-event traffic
    # pattern; drop-on-full policy lives on the producer side
    # (``_safe_enqueue_validation`` in redis_subscriber.py — Task 4).
    # Single writer task = no JSONL interleaving on the log file.
    validation_log_queue: asyncio.Queue = asyncio.Queue(maxsize=128)

    async def _validation_log_writer_loop() -> None:
        """Drain ``validation_log_queue`` and write to disk via the
        synchronous ``ValidationEventLogger``. Single writer = ordered
        JSONL output, no atomicity concerns from concurrent appends.

        Owns slowness: if disk I/O is slow, this task waits — but the
        subscriber's read loop keeps draining Redis (it only does
        ``put_nowait`` on the queue, never awaits a write).

        Mirrors the defensive shape of ``_translation_broadcaster_loop``:
        a single bad record never kills the writer.
        """
        while True:
            try:
                record = await validation_log_queue.get()
            except asyncio.CancelledError:
                raise
            try:
                # Run the synchronous file write off the event loop so
                # the next ``queue.get()`` doesn't park behind disk I/O.
                # Even though this writer is single-tenant (no
                # interleaving), a slow write would block subsequent
                # ``put_nowait`` calls if the queue fills.
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None, lambda r=record: validation_logger.log(**r)
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # A single bad record must not kill the writer.
                logger.warning(
                    "validation_log_writer tick error (continuing): %s: %s",
                    type(exc).__name__,
                    exc,
                )

    async def _camera_broadcaster_loop() -> None:
        """Drain ``camera_queue``, base64-encode JPEGs, broadcast to WS clients.

        γ-MAX++: also forwards ``detections`` from bbox sidecar so the dashboard
        can render bounding boxes on victim-bearing frames.
        Rate-limited to 1 frame per second per drone.
        """
        import base64
        import time as _time
        last_emit: Dict[str, float] = {}
        min_interval_s = 1.0
        while True:
            try:
                drone_id, frame_bytes, detections = await camera_queue.get()
            except asyncio.CancelledError:
                raise
            try:
                now = _time.monotonic()
                last = last_emit.get(drone_id, 0.0)
                if now - last < min_interval_s:
                    continue  # throttle
                last_emit[drone_id] = now
                frame_b64 = base64.b64encode(frame_bytes).decode("ascii")
                frame: Dict[str, Any] = {
                    "type": "drone_camera",
                    "drone_id": drone_id,
                    "frame_b64": frame_b64,
                    "ts": now,
                }
                if detections:
                    frame["detections"] = detections
                outcome = validate("websocket_messages", frame)
                if not outcome.valid:
                    logger.error("BUG: dropped camera frame post-build: %s", outcome.errors)
                    continue
                await registry.broadcast(frame)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "camera_broadcaster tick error (continuing): %s: %s",
                    type(exc).__name__, exc,
                )

    async def _task_broadcaster_loop() -> None:
        """γ-MAX++: forward EGS task assignments as drone_task_assignment frames."""
        while True:
            try:
                drone_id, payload = await task_queue.get()
            except asyncio.CancelledError:
                raise
            try:
                frame: Dict[str, Any] = {
                    "type": "drone_task_assignment",
                    "drone_id": drone_id,
                    "task_id": payload.get("task_id", ""),
                    "task_type": payload.get("task_type", ""),
                    "assigned_survey_points": payload.get("assigned_survey_points", []),
                }
                outcome = validate("websocket_messages", frame)
                if not outcome.valid:
                    logger.error("BUG: dropped task_assignment post-build: %s", outcome.errors)
                    continue
                await registry.broadcast(frame)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("task_broadcaster tick error: %s: %s", type(exc).__name__, exc)

    async def _validation_tick_broadcaster_loop() -> None:
        """γ-MAX++: tail validation_events.jsonl and broadcast new lines."""
        import time as _time
        from pathlib import Path as _Path
        log_path = _Path(os.environ.get("GG_LOG_DIR", "/tmp/gemma_guardian_logs")) / "validation_events.jsonl"
        last_size = 0
        # Start from end so we don't dump history on bridge restart.
        if log_path.exists():
            last_size = log_path.stat().st_size
        print(f"[validation_tick_tailer] STARTED path={log_path} last_size={last_size}", flush=True)
        while True:
            try:
                await asyncio.sleep(0.5)
                if not log_path.exists():
                    continue
                cur_size = log_path.stat().st_size
                if cur_size <= last_size:
                    continue
                with open(log_path, "r") as f:
                    f.seek(last_size)
                    new_content = f.read()
                last_size = cur_size
                for line in new_content.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    frame: Dict[str, Any] = {
                        "type": "validation_event_tick",
                        "agent_id": str(rec.get("agent_id", "?")),
                        "layer": str(rec.get("layer", "?")),
                        "rule_id": str(rec.get("rule_id", "?")),
                        "outcome": str(rec.get("outcome", "?")),
                        "function_or_command": str(rec.get("function_or_command", "?"))[:200],
                        "valid": bool(rec.get("valid", False)),
                        "ts": _time.monotonic(),
                    }
                    outcome = validate("websocket_messages", frame)
                    if not outcome.valid:
                        print(f"[validation_tick] REJECT: {outcome.errors[0].message if outcome.errors else '?'} | frame={frame}", flush=True)
                        continue
                    print(f"[validation_tick] BROADCAST: {frame['agent_id']} {frame['outcome']}", flush=True)
                    await registry.broadcast(frame)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("validation_tick tailer error: %s: %s", type(exc).__name__, exc)

    subscriber = RedisSubscriber(
        config=config,
        aggregator=aggregator,
        validation_logger=validation_logger,
        translation_queue=translation_queue,
        validation_log_queue=validation_log_queue,
        camera_queue=camera_queue,
        task_queue=task_queue,
    )
    publisher = RedisPublisher(redis_url=config.redis_url)

    app = FastAPI(title="FieldAgent WS Bridge (Phase 2)", lifespan=lifespan)
    app.state.config = config
    app.state.aggregator = aggregator
    app.state.subscriber = subscriber
    app.state.registry = registry
    app.state.publisher = publisher
    app.state.translation_queue = translation_queue
    app.state.translation_broadcaster = _translation_broadcaster_loop
    # Path γ-lite: camera pipeline registration.
    app.state.camera_queue = camera_queue
    app.state.camera_broadcaster = _camera_broadcaster_loop
    # Path γ-MAX++: task + validation tick pipelines.
    app.state.task_queue = task_queue
    app.state.task_broadcaster = _task_broadcaster_loop
    app.state.validation_tick_queue = validation_tick_queue
    app.state.validation_tick_broadcaster = _validation_tick_broadcaster_loop
    # Eng-review 2A: validation log queue + single-writer task.
    app.state.validation_log_queue = validation_log_queue
    app.state.validation_log_writer = _validation_log_writer_loop

    @app.get("/health")
    async def health() -> Dict[str, str]:
        return {"status": "ok", "contract_version": VERSION}

    # Path Δ: serve the Flutter dashboard from /dashboard so the runpod
    # proxy can reach it without exposing a separate port. Requires the
    # Flutter build to use --base-href "/dashboard/".
    from pathlib import Path as _Path
    from fastapi.staticfiles import StaticFiles
    _DASHBOARD = _Path("/workspace/Gemma-Guardian/frontend/flutter_dashboard/build/web")
    if _DASHBOARD.exists():
        app.mount("/dashboard", StaticFiles(directory=str(_DASHBOARD), html=True), name="dashboard")

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
                elif isinstance(parsed, dict) and parsed.get("type") == "operator_command_dispatch":
                    # Phase 4: the operator clicked DISPATCH on a translated
                    # command. Mirror the ``finding_approval`` path — validate,
                    # stamp ``bridge_received_at_iso_ms``, defensively
                    # re-validate against ``operator_actions`` (whose ``oneOf``
                    # covers both ``finding_approval`` and
                    # ``operator_command_dispatch`` kinds), then republish
                    # onto the same ``egs.operator_actions`` channel.
                    outcome = validate("websocket_messages", parsed)
                    if not outcome.valid:
                        await _echo_error(
                            websocket,
                            error="invalid_operator_command_dispatch",
                            detail=[e.message for e in outcome.errors],
                            command_id=parsed.get("command_id"),
                        )
                        continue
                    redis_payload: Dict[str, Any] = {
                        "kind": "operator_command_dispatch",
                        "command_id": parsed["command_id"],
                        "bridge_received_at_iso_ms": _now_iso_ms(),
                        "contract_version": VERSION,
                    }
                    bridge_outcome = validate("operator_actions", redis_payload)
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
                            "egs.operator_actions", redis_payload,
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
                            "ack": "operator_command_dispatch",
                            "command_id": parsed["command_id"],
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
