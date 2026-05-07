"""Interactive drone-agent stand-in REPL.

Single-drone CLI that lets a human take the per-drone agent's seat while the
sim is publishing. Subscribes to ``drones.<id>.state`` and ``drones.<id>.camera``
on a real Redis (the contract path — fakeredis is for tests). Inputs map to
the same five drone function calls the real agent emits, plus utilities for
inspecting state, frames, and peer broadcasts.

Two-layer validation, matching the real drone agent's retry loop:

  1. Schema floor — payloads validate against ``shared/schemas/<name>.json``
     via :func:`shared.contracts.schemas.validate`. Mirrors the
     ``STRUCTURAL_VALIDATION_FAILED`` corrective text.
  2. Semantic rules — once the schema passes, the parsed function call is
     handed to :class:`agents.drone_agent.validation.ValidationNode` (the
     same instance the per-drone agent uses) for battery floor, GPS-in-zone,
     duplicate-finding, severity↔confidence, and coverage-monotonicity. The
     REPL prints the same corrective prompt the real agent would re-prompt
     Gemma with, so the human pilot sees the contract from the agent's
     point of view.

The semantic layer reuses ValidationNode rather than reimplementing the
rules — the contracts in ``agents/drone_agent/validation.py`` are the
single source of truth.

Why this exists: when Kaleel is iterating on the drone agent and Hazim
is iterating on scenarios, having a fast loop where a human can type one
finding into a live sim and watch it land on Redis (and on the EGS, once
that's wired) shortens every debug cycle. Also useful for Ibrahim verifying
the WebSocket bridge mirrors ``drones.<id>.findings`` correctly.

Usage:
    uv run python sim/manual_pilot.py --drone-id drone1
    # GPS-in-zone semantics require a scenario for zone_bounds:
    uv run python sim/manual_pilot.py --drone-id drone1 --scenario disaster_zone_v1
    # in another pane: scripts/launch_swarm.sh resilience_v1 --drones=drone2,drone3
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import shlex
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Project-root bootstrap so direct invocation works.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import redis
import redis.asyncio as redis_async

from agents.drone_agent.perception import DroneState, PerceptionBundle
from agents.drone_agent.validation import ValidationNode, ValidationResult
from agents.drone_agent.zone_bounds import derive_zone_bounds_from_scenario
from shared.contracts.config import CONFIG
from shared.contracts.schemas import StructuralError, validate
from shared.contracts.topics import (
    per_drone_camera_channel,
    per_drone_findings_channel,
    per_drone_state_channel,
    swarm_broadcast_channel,
    swarm_visible_to_channel,
)
from sim.scenario import Scenario, load_scenario


HELP_TEXT = """\
manual_pilot — interactive stand-in for the per-drone agent.

Commands:
  state                                          Print latest drone_state JSON.
  frame                                          Save latest JPEG to --frames-out-dir,
                                                 print path / byte count / frame#.
  peers                                          Print recent peer broadcasts received
                                                 on swarm.<id>.visible_to.<id>.
  finding <type> <sev> <lat> <lon> <conf> <desc...>
                                                 Build a finding, validate against
                                                 finding.json, publish on
                                                 drones.<id>.findings on success.
  explored <zone_id> <coverage_pct>              mark_explored, validate only.
  assist <urgency> <reason...>                   request_assist, validate only.
  rtb <reason>                                   return_to_base, validate only.
  continue                                       continue_mission, validate only.
  broadcast <message...>                         peer_broadcast (task_complete shape),
                                                 publish on swarm.broadcasts.<id>.
  help                                           This text.
  quit | Ctrl-D                                  Clean exit.

Validation runs in two layers: JSON-Schema floor first, then the same
semantic rules the per-drone agent uses (battery, GPS-in-zone, duplicate-
finding, severity↔confidence, coverage-monotonic) via ValidationNode.
"""


def _now_iso_ms() -> str:
    """ISO-8601 UTC with millisecond precision (matches _common.json)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Pure parsing + builder layer (no I/O — exhaustively unit-tested)
# ---------------------------------------------------------------------------


CommandResult = dict
"""Tagged-dict shape: ``{"kind": "<command>", "args"?: {...}, "message"?: str}``"""


def parse_command(line: str) -> CommandResult:
    """Parse a REPL line into a tagged-dict command.

    Returns one of: ``{kind: noop}``, ``{kind: help}``, ``{kind: quit}``,
    ``{kind: state | frame | peers}``, ``{kind: continue_mission}``,
    ``{kind: finding | explored | assist | rtb | broadcast, args: {...}}``,
    ``{kind: error, message: ...}``, ``{kind: unknown, args: {name: ...}}``.

    Pure function — no I/O, no global state — so every code path is
    cheaply unit-testable without a Redis client.
    """
    line = line.strip()
    if not line:
        return {"kind": "noop"}
    try:
        parts = shlex.split(line)
    except ValueError as e:
        return {"kind": "error", "message": f"could not tokenize input: {e}"}
    if not parts:
        return {"kind": "noop"}
    cmd = parts[0].lower()
    args = parts[1:]

    if cmd in ("help", "?"):
        return {"kind": "help"}
    if cmd in ("quit", "exit"):
        return {"kind": "quit"}
    if cmd == "state":
        return {"kind": "state"}
    if cmd == "frame":
        return {"kind": "frame"}
    if cmd == "peers":
        return {"kind": "peers"}
    if cmd in ("continue", "noop"):
        return {"kind": "continue_mission"}
    if cmd == "finding":
        if len(args) < 6:
            return {
                "kind": "error",
                "message": "usage: finding <type> <severity> <lat> <lon> <confidence> <description...>",
            }
        try:
            return {
                "kind": "finding",
                "args": {
                    "type": args[0],
                    "severity": int(args[1]),
                    "gps_lat": float(args[2]),
                    "gps_lon": float(args[3]),
                    "confidence": float(args[4]),
                    "visual_description": " ".join(args[5:]),
                },
            }
        except ValueError as e:
            return {"kind": "error", "message": f"could not parse numeric arg: {e}"}
    if cmd == "explored":
        if len(args) != 2:
            return {"kind": "error", "message": "usage: explored <zone_id> <coverage_pct>"}
        try:
            return {
                "kind": "explored",
                "args": {"zone_id": args[0], "coverage_pct": float(args[1])},
            }
        except ValueError as e:
            return {"kind": "error", "message": f"could not parse coverage_pct: {e}"}
    if cmd == "assist":
        if len(args) < 2:
            return {"kind": "error", "message": "usage: assist <urgency> <reason...>"}
        return {
            "kind": "assist",
            "args": {"urgency": args[0], "reason": " ".join(args[1:])},
        }
    if cmd == "rtb":
        if len(args) != 1:
            return {"kind": "error", "message": "usage: rtb <reason>"}
        return {"kind": "rtb", "args": {"reason": args[0]}}
    if cmd == "broadcast":
        if not args:
            return {"kind": "error", "message": "usage: broadcast <message...>"}
        return {"kind": "broadcast", "args": {"message": " ".join(args)}}
    return {"kind": "unknown", "args": {"name": cmd}}


def build_finding_payload(
    *,
    drone_id: str,
    counter: int,
    args: dict,
    altitude: float = 0.0,
    image_path: Optional[str] = None,
) -> dict:
    """Wrap a parsed `finding` command into a Contract 4 finding envelope."""
    return {
        "finding_id": f"f_{drone_id}_{counter:03d}",
        "source_drone_id": drone_id,
        "timestamp": _now_iso_ms(),
        "type": args["type"],
        "severity": args["severity"],
        "gps_lat": args["gps_lat"],
        "gps_lon": args["gps_lon"],
        "altitude": altitude,
        "confidence": args["confidence"],
        "visual_description": args["visual_description"],
        "image_path": image_path or f"/tmp/manual_pilot_{drone_id}.jpg",
        # validated=False because the floor is shape-only; the real
        # semantic validator hasn't run.
        "validated": False,
        "validation_retries": 0,
        "operator_status": "pending",
    }


def build_function_call(kind: str, args: dict) -> dict:
    """Build the ``{function, arguments}`` envelope per drone_function_calls.json."""
    if kind == "explored":
        return {
            "function": "mark_explored",
            "arguments": {
                "zone_id": args["zone_id"],
                "coverage_pct": args["coverage_pct"],
            },
        }
    if kind == "assist":
        return {
            "function": "request_assist",
            "arguments": {"reason": args["reason"], "urgency": args["urgency"]},
        }
    if kind == "rtb":
        return {
            "function": "return_to_base",
            "arguments": {"reason": args["reason"]},
        }
    if kind == "continue_mission":
        return {"function": "continue_mission", "arguments": {}}
    raise ValueError(f"unknown function-call kind: {kind!r}")


def build_broadcast_payload(
    *,
    drone_id: str,
    counter: int,
    last_position: Optional[tuple[float, float, float]],
    message: str,
) -> dict:
    """Wrap a free-form REPL message into a peer_broadcast envelope.

    Picks ``broadcast_type=task_complete`` because it's the lightest payload
    in peer_broadcast.json (only requires ``task_id`` and ``result``). The
    user message is sluggified into ``task_id``; ``result`` defaults to
    ``"success"``. If a richer broadcast type is needed later, add a new
    REPL command rather than overloading this one.
    """
    pos = last_position if last_position is not None else (0.0, 0.0, 0.0)
    slug = re.sub(r"[^A-Za-z0-9_-]", "_", message).strip("_")[:64]
    task_id = slug or f"manual_{counter:03d}"
    return {
        "broadcast_id": f"{drone_id}_b{counter:03d}",
        "sender_id": drone_id,
        "sender_position": {"lat": pos[0], "lon": pos[1], "alt": pos[2]},
        "timestamp": _now_iso_ms(),
        "broadcast_type": "task_complete",
        "payload": {"task_id": task_id, "result": "success"},
    }


# ---------------------------------------------------------------------------
# Validation + publish
# ---------------------------------------------------------------------------


class SchemaValidationError(Exception):
    """Raised when a payload fails its shared/schemas/<name>.json contract.

    Message formatting mirrors the STRUCTURAL_VALIDATION_FAILED corrective
    template from shared/contracts/rules.py so REPL users see the same
    "field X: message" feedback the real drone agent surfaces in its retry
    loop.
    """


class SemanticValidationError(Exception):
    """Raised when a parsed function call passes the schema floor but fails
    a semantic rule from :class:`agents.drone_agent.validation.ValidationNode`
    (battery, GPS-in-zone, duplicate-finding, severity↔confidence,
    coverage-monotonic). The message is the same corrective prompt the
    real drone agent re-feeds Gemma during its retry loop.
    """


def format_validation_errors(schema_name: str, errors: list[StructuralError]) -> str:
    lines = [f"{schema_name} validation failed ({len(errors)} error(s)):"]
    for e in errors:
        lines.append(f"  - field '{e.field_path}': {e.message}")
    lines.append("Re-emit the call with the correct shape; see shared/schemas/.")
    return "\n".join(lines)


def format_semantic_error(result: ValidationResult) -> str:
    rule_id = result.failure_reason.value if result.failure_reason else "UNKNOWN"
    prompt = result.corrective_prompt or "(no corrective prompt provided)"
    return f"semantic validation failed ({rule_id}):\n  {prompt}"


def validate_or_raise(schema_name: str, payload: dict) -> None:
    outcome = validate(schema_name, payload)
    if not outcome.valid:
        raise SchemaValidationError(format_validation_errors(schema_name, outcome.errors))


def publish_validated(
    *, redis_client: redis.Redis, channel: str, schema_name: str, payload: dict
) -> None:
    """Validate then publish JSON. Raises SchemaValidationError on failure
    (message already formatted with field-path detail)."""
    validate_or_raise(schema_name, payload)
    redis_client.publish(channel, json.dumps(payload))


# ---------------------------------------------------------------------------
# REPL state + dispatch
# ---------------------------------------------------------------------------


@dataclass
class _LiveState:
    """In-process buffers populated by the async listener task."""

    latest_state_json: Optional[dict] = None
    latest_frame_bytes: Optional[bytes] = None
    # Frame-counter from the listener. -1 = no frame yet; 0+ = nth frame.
    latest_frame_index: int = -1
    recent_peers: list[dict] = field(default_factory=list)
    finding_counter: int = 0
    broadcast_counter: int = 0


class ManualPilot:
    """Async REPL controller. Holds shared state between the listener and
    the dispatch loop. The dispatch ``_handle`` method is sync so it remains
    cheap to test against fakeredis without bringing asyncio into the test
    matrix."""

    def __init__(
        self,
        *,
        drone_id: str,
        redis_url: str,
        frames_out_dir: Path,
        scenario: Optional[Scenario] = None,
    ) -> None:
        self.drone_id = drone_id
        self.redis_url = redis_url
        self.frames_out_dir = Path(frames_out_dir)
        self.state = _LiveState()
        # Single ValidationNode instance per pilot — its recent_findings and
        # last_coverage_by_zone state must persist across REPL commands so
        # duplicate-finding and coverage-monotonic checks behave like the
        # real drone agent.
        self.validator = ValidationNode()
        # Without a scenario, zone_bounds is empty and the GPS_OUTSIDE_ZONE
        # check short-circuits to valid — the rest of the semantic layer
        # still runs.
        if scenario is not None:
            self.zone_bounds = derive_zone_bounds_from_scenario(scenario, drone_id)
        else:
            self.zone_bounds = {}

    # --- Subscription bookkeeping ---------------------------------------------

    async def _listen(self, redis_client: redis_async.Redis) -> None:
        pubsub = redis_client.pubsub()
        state_ch = per_drone_state_channel(self.drone_id)
        camera_ch = per_drone_camera_channel(self.drone_id)
        peer_ch = swarm_visible_to_channel(self.drone_id)
        await pubsub.subscribe(state_ch, camera_ch, peer_ch)
        try:
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                ch = msg["channel"]
                if isinstance(ch, bytes):
                    ch = ch.decode()
                data = msg["data"]
                if ch == state_ch:
                    self._ingest_state(data)
                elif ch == camera_ch:
                    self._ingest_frame(data)
                elif ch == peer_ch:
                    self._ingest_peer(data)
        finally:
            try:
                await pubsub.unsubscribe()
            finally:
                await pubsub.aclose()

    def _ingest_state(self, data: Any) -> None:
        try:
            self.state.latest_state_json = json.loads(data)
        except (TypeError, ValueError):
            pass

    def _ingest_frame(self, data: Any) -> None:
        if isinstance(data, (bytes, bytearray)):
            self.state.latest_frame_bytes = bytes(data)
        else:
            self.state.latest_frame_bytes = str(data).encode()
        self.state.latest_frame_index += 1

    def _ingest_peer(self, data: Any) -> None:
        try:
            self.state.recent_peers.append(json.loads(data))
            self.state.recent_peers = self.state.recent_peers[-10:]
        except (TypeError, ValueError):
            pass

    # --- Stdin --------------------------------------------------------------

    async def _read_line(self) -> Optional[str]:
        """asyncio-friendly stdin readline. Returns None on EOF (Ctrl-D)."""
        line = await asyncio.to_thread(sys.stdin.readline)
        if line == "":
            return None
        return line

    # --- Loop --------------------------------------------------------------

    async def run(self) -> int:
        client = redis_async.Redis.from_url(self.redis_url)
        listen_task = asyncio.create_task(self._listen(client))
        # Sync client for publishes from the REPL — keeps publish_validated
        # unit-testable on the same code path the live REPL exercises.
        sync_client = redis.Redis.from_url(self.redis_url)
        try:
            print(
                f"[manual_pilot] drone_id={self.drone_id} redis={self.redis_url}\n"
                f"Type 'help' for commands. Ctrl-D to quit.",
                flush=True,
            )
            while True:
                print(f"({self.drone_id}) > ", end="", flush=True)
                line = await self._read_line()
                if line is None:
                    print("", flush=True)
                    return 0
                cmd = parse_command(line)
                if self._handle(sync_client, cmd):
                    return 0
        finally:
            listen_task.cancel()
            try:
                await listen_task
            except asyncio.CancelledError:
                pass
            try:
                sync_client.close()
            except Exception:
                pass
            try:
                await client.aclose()
            except Exception:
                pass

    def _handle(self, sync_client: redis.Redis, cmd: CommandResult) -> bool:
        """Dispatch one parsed command. Returns True iff the loop should exit."""
        kind = cmd["kind"]
        if kind == "noop":
            return False
        if kind == "quit":
            return True
        if kind == "help":
            print(HELP_TEXT, flush=True)
            return False
        if kind == "error":
            print(f"[error] {cmd['message']}", flush=True)
            return False
        if kind == "unknown":
            print(f"[error] unknown command: {cmd['args']['name']!r}; try 'help'.", flush=True)
            return False
        if kind == "state":
            self._cmd_state()
            return False
        if kind == "frame":
            self._cmd_frame()
            return False
        if kind == "peers":
            self._cmd_peers()
            return False
        if kind == "continue_mission":
            self._cmd_validate_only("continue_mission", {})
            return False
        if kind in ("explored", "assist", "rtb"):
            self._cmd_validate_only(kind, cmd["args"])
            return False
        if kind == "finding":
            self._cmd_finding(sync_client, cmd["args"])
            return False
        if kind == "broadcast":
            self._cmd_broadcast(sync_client, cmd["args"])
            return False
        print(f"[error] unhandled command kind: {kind}", flush=True)
        return False

    # --- Per-command handlers ----------------------------------------------

    def _cmd_state(self) -> None:
        if self.state.latest_state_json is None:
            print("[state] no drone_state received yet.", flush=True)
        else:
            print(json.dumps(self.state.latest_state_json, indent=2), flush=True)

    def _cmd_frame(self) -> None:
        if self.state.latest_frame_bytes is None:
            print("[frame] no camera frame received yet.", flush=True)
            return
        self.frames_out_dir.mkdir(parents=True, exist_ok=True)
        path = self.frames_out_dir / f"manual_pilot_{self.drone_id}.jpg"
        path.write_bytes(self.state.latest_frame_bytes)
        print(
            f"[frame] saved to {path} "
            f"({len(self.state.latest_frame_bytes)} bytes; "
            f"frame #{self.state.latest_frame_index} since REPL start)",
            flush=True,
        )

    def _cmd_peers(self) -> None:
        if not self.state.recent_peers:
            print("[peers] no peer broadcasts received yet.", flush=True)
            return
        for peer in self.state.recent_peers:
            print(json.dumps(peer), flush=True)

    def _cmd_validate_only(self, kind: str, args: dict) -> None:
        try:
            payload = build_function_call(kind, args)
            validate_or_raise("drone_function_calls", payload)
            bundle = self._build_perception_bundle()
            result = self.validator.validate(payload, bundle)
            if not result.valid:
                raise SemanticValidationError(format_semantic_error(result))
            self.validator.record_success(payload, bundle)
        except (SchemaValidationError, SemanticValidationError) as e:
            print(f"[error] {e}", flush=True)
            return
        except (KeyError, ValueError) as e:
            print(f"[error] could not build call: {e}", flush=True)
            return
        print(
            f"[ok] {payload['function']} validated "
            f"(no canonical wire channel for raw calls; not republished).",
            flush=True,
        )

    def _cmd_finding(self, sync_client: redis.Redis, args: dict) -> None:
        self.state.finding_counter += 1
        altitude = self._latest_altitude() or 0.0
        payload = build_finding_payload(
            drone_id=self.drone_id,
            counter=self.state.finding_counter,
            args=args,
            altitude=altitude,
        )
        # Sibling function-call shape so ValidationNode's semantic rules
        # (severity↔confidence, GPS-in-zone, duplicate-finding) see the
        # same arguments the real agent would have emitted.
        function_call = {
            "function": "report_finding",
            "arguments": {
                "type": args["type"],
                "severity": args["severity"],
                "gps_lat": args["gps_lat"],
                "gps_lon": args["gps_lon"],
                "confidence": args["confidence"],
                "visual_description": args["visual_description"],
            },
        }
        bundle = self._build_perception_bundle()
        try:
            # Schema floor on the wire envelope.
            validate_or_raise("finding", payload)
            # Semantic floor on the function-call shape.
            result = self.validator.validate(function_call, bundle)
            if not result.valid:
                raise SemanticValidationError(format_semantic_error(result))
            sync_client.publish(
                per_drone_findings_channel(self.drone_id), json.dumps(payload)
            )
        except (SchemaValidationError, SemanticValidationError) as e:
            # Roll back so the next attempt isn't off by one.
            self.state.finding_counter -= 1
            print(f"[error] {e}", flush=True)
            return
        self.validator.record_success(function_call, bundle)
        print(
            f"[ok] published {payload['finding_id']} on "
            f"{per_drone_findings_channel(self.drone_id)}",
            flush=True,
        )

    def _cmd_broadcast(self, sync_client: redis.Redis, args: dict) -> None:
        self.state.broadcast_counter += 1
        payload = build_broadcast_payload(
            drone_id=self.drone_id,
            counter=self.state.broadcast_counter,
            last_position=self._latest_position(),
            message=args["message"],
        )
        try:
            publish_validated(
                redis_client=sync_client,
                channel=swarm_broadcast_channel(self.drone_id),
                schema_name="peer_broadcast",
                payload=payload,
            )
        except SchemaValidationError as e:
            self.state.broadcast_counter -= 1
            print(f"[error] {e}", flush=True)
            return
        print(
            f"[ok] published broadcast {payload['broadcast_id']} on "
            f"{swarm_broadcast_channel(self.drone_id)}",
            flush=True,
        )

    # --- Helpers ----------------------------------------------------------

    def _build_perception_bundle(self) -> PerceptionBundle:
        """Synthesize a PerceptionBundle from the latest drone_state JSON
        plus the (possibly empty) zone_bounds derived from the scenario.

        Defaults when fields are missing from the wire payload:
          - battery_pct=100.0 → RTB(low_battery) is correctly rejected
            until the sim publishes a real battery reading.
          - assigned_survey_points_remaining=1 → RTB(mission_complete) is
            correctly rejected until the sim signals zero remaining.
        These match the real drone agent's "no evidence yet" stance.
        """
        payload = self.state.latest_state_json or {}
        pos = payload.get("position") or {}
        drone_state = DroneState(
            drone_id=self.drone_id,
            lat=float(pos.get("lat", 0.0)),
            lon=float(pos.get("lon", 0.0)),
            alt=float(pos.get("alt", 0.0)),
            battery_pct=float(payload.get("battery_pct", 100.0)),
            heading_deg=float(payload.get("heading_deg", 0.0)),
            current_task=payload.get("current_task") or "survey",
            assigned_survey_points_remaining=int(
                payload.get("assigned_survey_points_remaining", 1)
            ),
            zone_bounds=self.zone_bounds,
        )
        return PerceptionBundle(frame_jpeg=b"", state=drone_state)

    def _latest_position(self) -> Optional[tuple[float, float, float]]:
        s = self.state.latest_state_json
        if not s:
            return None
        try:
            pos = s["position"]
            return (pos["lat"], pos["lon"], pos["alt"])
        except (KeyError, TypeError):
            return None

    def _latest_altitude(self) -> Optional[float]:
        pos = self._latest_position()
        return pos[2] if pos is not None else None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


_DRONE_ID_RE = re.compile(r"^drone\d+$")


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactive drone-agent stand-in REPL.")
    parser.add_argument(
        "--drone-id",
        required=True,
        help="Drone id matching ^drone\\d+$ (e.g. drone1).",
    )
    parser.add_argument("--redis-url", default=CONFIG.transport.redis_url)
    parser.add_argument(
        "--frames-out-dir",
        default="/tmp",
        help="Directory where 'frame' command writes the latest JPEG. Created on first save.",
    )
    parser.add_argument(
        "--scenario",
        default=None,
        help=(
            "Scenario YAML path or scenario_id under sim/scenarios/. "
            "Required for the GPS_OUTSIDE_ZONE semantic check; without it the "
            "GPS check short-circuits to valid (other semantic checks still run)."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _resolve_scenario_path(arg: str) -> Path:
    p = Path(arg)
    if p.exists():
        return p
    candidate = _PROJECT_ROOT / "sim" / "scenarios" / f"{arg}.yaml"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"scenario not found: {arg!r} (also looked at {candidate})")


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    if not _DRONE_ID_RE.match(args.drone_id):
        print(
            f"[error] --drone-id must match ^drone\\d+$; got {args.drone_id!r}",
            file=sys.stderr,
        )
        return 2
    scenario: Optional[Scenario] = None
    if args.scenario is not None:
        try:
            scenario = load_scenario(_resolve_scenario_path(args.scenario))
        except (FileNotFoundError, KeyError) as e:
            print(f"[error] could not load scenario: {e}", file=sys.stderr)
            return 2
    pilot = ManualPilot(
        drone_id=args.drone_id,
        redis_url=args.redis_url,
        frames_out_dir=Path(args.frames_out_dir),
        scenario=scenario,
    )
    try:
        return asyncio.run(pilot.run())
    except KeyboardInterrupt:
        print("[manual_pilot] stopped via SIGINT", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
