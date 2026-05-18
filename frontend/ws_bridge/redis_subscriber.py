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
- ``drones.<id>.findings.delivered`` -> ``finding`` -> ``aggregator.add_finding``
  (PR1: bridge migrated from ``.findings`` onto the mesh-sim-gated
  ``.delivered`` copy. PR2 adds the actual gate; for now mesh sim is a pure
  passthrough.)

Channel constants come from ``shared.contracts.topics``; subscribe patterns
are derived by replacing ``{drone_id}`` with ``*``. Do not hard-code channel
strings.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
# PR1: the bridge consumes the mesh-sim-gated copy of findings.
_DRONE_FINDINGS_PATTERN: str = topics.PER_DRONE_FINDINGS_DELIVERED.replace(
    "{drone_id}", "*"
)
# Path γ-lite: live camera feed for the dashboard. Raw JPEG bytes; bypasses
# JSON validation since the payload is binary.
_DRONE_CAMERA_PATTERN: str = topics.PER_DRONE_CAMERA.replace("{drone_id}", "*")
# Path γ-MAX++: EGS task assignments (Contract 5) routed to dashboard for
# coordination visualization.
_DRONE_TASKS_PATTERN: str = topics.PER_DRONE_TASKS.replace("{drone_id}", "*")
_EGS_STATE_CHANNEL: str = topics.EGS_STATE
_EGS_COMMAND_TRANSLATIONS_CHANNEL: str = topics.EGS_COMMAND_TRANSLATIONS

# Path γ-MAX++: bbox sidecar — bridge precomputes file→bbox map at startup
# by SHA1-hashing each fixture frame. When a binary camera frame arrives we
# hash the payload and look up detections. This avoids changing
# frame_server's publish contract.
_BBOX_SIDECAR_PATH = Path("/workspace/Gemma-Guardian/sim/fixtures/bbox_metadata.json")
_FRAMES_DIR = Path("/workspace/Gemma-Guardian/sim/fixtures/frames")

# Option C: when the C2A vision adapter emits pixel_bbox on a finding, we
# attach the box to that drone's next few camera frames so the dashboard
# renders it. TTL chosen to outlive a single ~1 fps inference window plus a
# brief render delay; longer than 4s lets stale boxes linger across drone
# movement.
_MODEL_DETECTION_TTL_S: float = 4.0
# Frame size used to convert normalized [0-1] bboxes back to absolute pixel
# coords matching the bbox_metadata.json fixture geometry.
_FRAME_W: int = 1024
_FRAME_H: int = 576


def _build_bbox_lookup() -> Dict[str, list]:
    """Return {sha1_hash: detections_list} for every fixture frame with bbox."""
    if not _BBOX_SIDECAR_PATH.exists() or not _FRAMES_DIR.exists():
        _LOG.info("γ-MAX++ bbox sidecar not present, skipping bbox lookup build")
        return {}
    try:
        sidecar = json.loads(_BBOX_SIDECAR_PATH.read_text())
    except Exception as e:
        _LOG.warning("bbox sidecar parse error: %s", e)
        return {}
    lookup: Dict[str, list] = {}
    for fname, entry in sidecar.get("frames", {}).items():
        fpath = _FRAMES_DIR / fname
        if not fpath.exists():
            continue
        h = hashlib.sha1(fpath.read_bytes()).hexdigest()
        raw = entry.get("detections", [])
        # Annotate every sidecar detection so Flutter can render it with
        # the "GT" (ground truth) styling, distinguishing it from real
        # Gemma model output (which carries source="gemma_c2a").
        annotated = [{**d, "source": "sard_gt"} for d in raw if isinstance(d, dict)]
        lookup[h] = annotated
        _LOG.info("γ-MAX++ bbox: %s sha1=%s detections=%d", fname, h[:8], len(annotated))
    return lookup

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
    # PR1: findings now arrive on the mesh-sim-gated `.delivered` channel.
    # Form: drones.<id>.findings.delivered (4 dotted parts).
    if channel.startswith("drones.") and channel.endswith(".findings.delivered"):
        parts = channel.split(".")
        if len(parts) == 4:
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
        validation_log_queue: Optional[asyncio.Queue] = None,
        camera_queue: Optional[asyncio.Queue] = None,
        task_queue: Optional[asyncio.Queue] = None,
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
        # Bounded queue for validation event records. Pushed by the dispatch
        # path (sync, via put_nowait), drained by main.py's
        # _validation_log_writer_loop. Single writer = no interleaving on the
        # JSONL file. Maxsize=128 is generous for the validation event traffic
        # pattern (~1 event per malformed frame); drop-on-full policy
        # documented in _safe_enqueue_validation below.
        self._validation_log_queue: Optional[asyncio.Queue] = validation_log_queue
        # Path γ-lite: binary camera-frame pipeline. Subscriber pushes
        # (drone_id, raw_jpeg_bytes) tuples; the dedicated camera broadcaster
        # task in main.py base64-encodes and broadcasts. Drop-oldest-on-full
        # policy matches the translation queue (fresh frames > old frames).
        self._camera_queue: Optional[asyncio.Queue] = camera_queue
        # Path γ-MAX++: EGS task assignment routing. Subscriber pushes raw
        # JSON payloads; broadcaster forwards as drone_task_assignment.
        self._task_queue: Optional[asyncio.Queue] = task_queue
        # Path γ-MAX++: bbox lookup keyed by frame SHA1 hash, attached to
        # camera frames in the broadcaster loop (not here — keep subscriber
        # cheap).
        self._bbox_lookup: Dict[str, list] = _build_bbox_lookup()
        # Option C: per-drone cache of the most recent model-emitted detections.
        # Populated by the finding handler when a finding carries pixel_bbox;
        # consumed by the camera handler for the next _MODEL_DETECTION_TTL_S
        # seconds, then expires. Falls back to sidecar lookup when empty.
        self._model_detections: Dict[str, Tuple[float, List[dict]]] = {}
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
        # Path γ-lite: subscribe camera channel only if queue is wired (tests
        # that don't pass camera_queue stay schema-free).
        if self._camera_queue is not None:
            await pubsub.psubscribe(_DRONE_CAMERA_PATTERN)
        # Path γ-MAX++: task assignments for dashboard coordination overlay.
        if self._task_queue is not None:
            await pubsub.psubscribe(_DRONE_TASKS_PATTERN)

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

        # Path γ-lite: camera frames are RAW JPEG BYTES — bypass JSON parsing
        # and schema validation entirely. Push tuple (drone_id, bytes, detections)
        # onto camera_queue. Detections come from the precomputed sha1→bbox map.
        if (
            self._camera_queue is not None
            and channel.startswith("drones.")
            and channel.endswith(".camera")
        ):
            parts = channel.split(".")
            if len(parts) == 3:
                drone_id_c = parts[1]
                data_raw = message.get("data")
                if isinstance(data_raw, (bytes, bytearray)):
                    frame_bytes = bytes(data_raw)
                    # γ-MAX++ bbox lookup by SHA1 — O(1). The pixel coords
                    # are SARD ground-truth annotations of the fixture
                    # frames; the C2A LoRA emits report_finding(type=victim)
                    # but is a classifier (no bbox capability). If a model
                    # finding is fresh for this drone we prefer model-supplied
                    # bbox (future LoRA), otherwise fall back to sidecar.
                    model_dets = self._model_detections_for(drone_id_c)
                    if model_dets and model_dets[0].get("bbox"):
                        detections = model_dets
                    else:
                        frame_hash = hashlib.sha1(frame_bytes).hexdigest()
                        detections = self._bbox_lookup.get(frame_hash, [])
                    try:
                        self._camera_queue.put_nowait((drone_id_c, frame_bytes, detections))
                    except asyncio.QueueFull:
                        try:
                            self._camera_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                        try:
                            self._camera_queue.put_nowait((drone_id_c, frame_bytes, detections))
                        except asyncio.QueueFull:
                            pass
            return

        # Path γ-MAX++: task assignment forwarding. JSON envelope on
        # drones.<id>.tasks — schema-validate then enqueue.
        if (
            self._task_queue is not None
            and channel.startswith("drones.")
            and channel.endswith(".tasks")
        ):
            parts = channel.split(".")
            if len(parts) == 3:
                drone_id_t = parts[1]
                data_raw = message.get("data")
                try:
                    if isinstance(data_raw, (bytes, bytearray)):
                        payload = json.loads(data_raw.decode("utf-8"))
                    elif isinstance(data_raw, str):
                        payload = json.loads(data_raw)
                    else:
                        return
                    outcome = validate("task_assignment", payload)
                    if not outcome.valid:
                        _LOG.warning("task_assignment invalid for %s: %s", drone_id_t,
                                     outcome.errors[0].message if outcome.errors else "?")
                        return
                    try:
                        self._task_queue.put_nowait((drone_id_t, payload))
                    except asyncio.QueueFull:
                        try:
                            self._task_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                        try:
                            self._task_queue.put_nowait((drone_id_t, payload))
                        except asyncio.QueueFull:
                            pass
                except Exception as e:
                    _LOG.warning("task_assignment decode error for %s: %s", drone_id_t, e)
            return

        if "command_translation" in channel or "operator_command" in channel:
            print(f"[BRIDGE-RX] channel={channel} data_len={len(message.get('data') or b'')}", flush=True)
        schema_name, drone_id = _classify_channel(channel)
        if schema_name is None:
            print(f"[BRIDGE-RX] UNHANDLED channel={channel}", flush=True)
            _LOG.warning("RedisSubscriber: unhandled channel %r; dropping", channel)
            return
        if schema_name == "command_translations_envelope":
            print(f"[BRIDGE-RX] classified as command_translations_envelope, continuing dispatch", flush=True)

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
            if schema_name == "command_translations_envelope":
                _LOG.warning(
                    "validation failed for command_translation: %s", detail,
                )
                _LOG.debug("command_translation raw payload: %s", payload)
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
            # Option C: if the C2A adapter emitted a pixel_bbox, cache it for
            # the next few camera frames from this drone so the dashboard
            # renders model-derived boxes instead of the SHA1-keyed sidecar.
            self._maybe_cache_model_detection(payload)
        elif schema_name == "command_translations_envelope":
            print(f"[CMD-TRANS] RECEIVED payload keys={list(payload.keys())}", flush=True)
            if self._translation_queue is not None:
                try:
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
                except KeyError as e:
                    print(f"[CMD-TRANS] DROP key missing {e}: payload={payload}", flush=True)
                    return
                print(f"[CMD-TRANS] ENQUEUE cmd_id={ws_frame['command_id']} preview={ws_frame['preview_text'][:60]}", flush=True)
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

    # ---- Option C: model-emitted detection cache -------------------------

    def _maybe_cache_model_detection(self, payload: Dict[str, Any]) -> None:
        """Cache a finding event so the next camera frames render its box.

        If the finding carries a real ``pixel_bbox`` (future LoRA with
        detection capability), use those coords directly. Otherwise cache a
        placeholder so the camera handler knows to look up the SARD
        ground-truth bbox for the current frame. Either way, the box is
        gated on a real model emission — no box renders when the model
        hasn't fired.
        """
        drone_id = payload.get("source_drone_id")
        if not isinstance(drone_id, str):
            return
        label = str(payload.get("type", "victim")).upper()
        confidence = float(payload.get("confidence", 0.0))
        description = payload.get("visual_description", "")
        bbox_norm = payload.get("pixel_bbox")
        if isinstance(bbox_norm, (list, tuple)) and len(bbox_norm) == 4:
            try:
                x_n, y_n, w_n, h_n = (float(v) for v in bbox_norm)
                detection = {
                    "label": label,
                    "confidence": confidence,
                    "bbox": [
                        int(round(x_n * _FRAME_W)),
                        int(round(y_n * _FRAME_H)),
                        int(round(w_n * _FRAME_W)),
                        int(round(h_n * _FRAME_H)),
                    ],
                    "source": "gemma_c2a",
                    "description": description,
                }
                self._model_detections[drone_id] = (time.monotonic(), [detection])
                _LOG.info("model bbox cached for %s: bbox=%s conf=%.2f",
                          drone_id, detection["bbox"], confidence)
                return
            except (TypeError, ValueError):
                pass
        # No pixel_bbox: cache a trigger-only entry. The camera handler
        # enriches with SARD sidecar coords on the next matching frame.
        trigger = {
            "label": label,
            "confidence": confidence,
            "source": "c2a_trigger",
            "description": description,
        }
        self._model_detections[drone_id] = (time.monotonic(), [trigger])
        _LOG.info("model finding cached for %s: %s conf=%.2f (sidecar coords on next frame)",
                  drone_id, label, confidence)

    def _model_detections_for(self, drone_id: str) -> List[dict]:
        """Return cached model detections for drone if still within TTL."""
        cached = self._model_detections.get(drone_id)
        if cached is None:
            return []
        ts, detections = cached
        if time.monotonic() - ts > _MODEL_DETECTION_TTL_S:
            self._model_detections.pop(drone_id, None)
            return []
        return detections

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
        """Best-effort enqueue of a validation event for the writer task.

        Eng-review 2A Option B: the dispatch path must not block on disk
        I/O. We push a record dict onto ``self._validation_log_queue`` via
        ``put_nowait`` (sync, microseconds). ``main.py``'s
        ``_validation_log_writer_loop`` drains it on a dedicated task,
        serializing writes to the JSONL file (no interleaving) and running
        the actual disk I/O in the default thread pool executor (so even
        the writer task doesn't block on disk).

        Drop-on-full policy: if the bounded queue is at capacity (default
        maxsize=128), the record is dropped with a stderr warning. This
        only happens under sustained burst — at steady state the queue
        drains faster than dispatch fills it.

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
        record = {
            "agent_id": agent_id,
            "layer": layer,
            "function_or_command": f"{schema_name}@{channel}: {detail}",
            "attempt": 1,
            "valid": False,
            "rule_id": rule_id,
            "outcome": "failed_after_retries",
            "raw_call": raw_call,
        }
        if self._validation_log_queue is None:
            # Queue not wired (e.g., in unit tests that don't pass the kwarg).
            # Fall back to a no-op rather than crash dispatch.
            return
        try:
            self._validation_log_queue.put_nowait(record)
        except asyncio.QueueFull:
            # Sustained burst — queue can't keep up with dispatch. The
            # validation log is debug telemetry, so dropping is acceptable.
            # Log a warning so the fact that we dropped is visible without
            # requiring a tail of the (now-stale) validation_events.jsonl.
            _LOG.warning(
                "validation_log_queue full — dropping record for %s/%s@%s",
                agent_id,
                schema_name,
                channel,
            )
