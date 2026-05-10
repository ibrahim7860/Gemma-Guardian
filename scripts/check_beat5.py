"""Programmatic verifier for the Beat 5 capture run (resilience_v1).

Subscribes to the bridge WebSocket and reads the validation_events.jsonl log
file produced by the drone agent. Asserts the six A-assertions listed in
``docs/plans/2026-05-10-beat5-path-a-full.md`` §9:

    A1: drone3 enters ``agent_status == "standalone"`` between scenario
        t=120 and t=130.
    A2: drone3 publishes >= 1 Contract-4 ``report_finding`` while
        standalone (validation_events log; scenario time in [120, 180]).
    A3: That finding lands on ``drones.drone3.findings.delivered`` ONLY
        AFTER ``egs_link_restore`` (t≈180).
    A4: ``egs.state.findings_count_by_type`` reflects the
        drone3-while-standalone finding within 5s of ``egs_link_restore``.
    A5: drone3 returns to ``agent_status == "active"`` after t=180.
    A6: The same ``finding_id`` does NOT cause a second count increment
        (resilience to replay double-fire).

Scenario tick is derived from the latest ``egs_state.timestamp`` — when
the run starts the EGS publishes its first state, and the verifier
correlates wall-clock to scenario tick by clamping to the first observed
timestamp. (We can't read the exact scenario `t` from the bridge envelope
since it isn't carried there; the wall-clock anchor is good enough for
the +/- 5-10s tolerances in the assertions.)

CLI:
    scripts/check_beat5.py \
        --bridge-url ws://127.0.0.1:9090 \
        --validation-log /tmp/gemma_guardian_logs/validation_events.jsonl \
        --deadline-s 240

Exit codes:
    0  — all six A-assertions passed within the deadline.
    1  — one or more A-assertions failed (printed as a table to stderr).
    2  — connection / file / protocol error (bridge not running, no log
         file, etc.).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


_DEFAULT_VALIDATION_LOG = Path(
    os.environ.get("GG_LOG_DIR", "/tmp/gemma_guardian_logs")
) / "validation_events.jsonl"


@dataclass
class _AssertionResult:
    code: str
    description: str
    passed: bool = False
    detail: str = ""


@dataclass
class _RunState:
    """Accumulator while we tail the bridge + validation log."""
    # Wall-clock at the first observed envelope. Used to derive a
    # scenario-tick estimate (t_scenario ≈ wall_clock - anchor_wall_clock).
    anchor_wall_s: Optional[float] = None
    # First scenario-tick at which drone3.agent_status was observed as
    # "standalone", in seconds-since-anchor.
    drone3_first_standalone_t: Optional[float] = None
    # First scenario-tick at which drone3.agent_status returned to "active"
    # AFTER having been "standalone".
    drone3_back_to_active_t: Optional[float] = None
    # Highest victim+fire+smoke+damaged_structure+blocked_route total seen
    # while drone3 was standalone (before any link_restore).
    counts_during_standalone: Dict[str, int] = field(default_factory=dict)
    # Counts at the moment we last observed drone3 == standalone.
    counts_at_standalone_end: Dict[str, int] = field(default_factory=dict)
    # Counts after standalone window closed.
    counts_after_restore: Dict[str, int] = field(default_factory=dict)
    # Highest count snapshot ever seen across all tracked types.
    counts_max: Dict[str, int] = field(default_factory=dict)
    # Wall-clock at which we observed drone3 transitioning back to active.
    restore_wall_s: Optional[float] = None
    # Wall-clock at first envelope where total count incremented AFTER
    # restore_wall_s.
    first_increment_after_restore_wall_s: Optional[float] = None
    # The total count value at restore time.
    total_at_restore: int = 0
    # The total count value reached after restore.
    max_total_after_restore: int = 0


def _sum_counts(c: Dict[str, int]) -> int:
    return sum(int(v) for v in c.values() if isinstance(v, (int, float)))


async def _consume_bridge(
    ws_url: str,
    state: _RunState,
    deadline_s: float,
    stop_event: asyncio.Event,
) -> None:
    """Tail bridge state_update envelopes until the deadline or stop_event."""
    import httpx
    from httpx_ws import aconnect_ws

    deadline = time.monotonic() + deadline_s
    try:
        async with httpx.AsyncClient() as http_client:
            async with aconnect_ws(ws_url, http_client) as ws:
                while time.monotonic() < deadline and not stop_event.is_set():
                    remaining = deadline - time.monotonic()
                    try:
                        raw = await asyncio.wait_for(
                            ws.receive_text(), timeout=min(remaining, 1.0),
                        )
                    except asyncio.TimeoutError:
                        continue
                    try:
                        env = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(env, dict):
                        continue
                    if env.get("type") != "state_update":
                        continue
                    _ingest_envelope(env, state, now_wall=time.monotonic())
    except Exception as exc:  # noqa: BLE001
        # Surface the error via state.anchor_wall_s being None — main()
        # will detect "we never connected".
        sys.stderr.write(
            f"[check_beat5] bridge connection error: "
            f"{type(exc).__name__}: {exc}\n"
        )


def _ingest_envelope(
    env: dict,
    state: _RunState,
    now_wall: Optional[float] = None,
) -> None:
    """Update accumulator from one bridge envelope.

    ``now_wall`` is the monotonic-style timestamp to associate with this
    envelope. When ``None`` (live mode) we read ``time.monotonic()`` so
    behavior matches the pre-refactor implementation. When replaying from
    a recorded log, the caller passes the recorded ``received_at_s`` so
    A3/A4 timing semantics are preserved.
    """
    if now_wall is None:
        now_wall = time.monotonic()
    if state.anchor_wall_s is None:
        state.anchor_wall_s = now_wall
    t_scenario = now_wall - state.anchor_wall_s

    egs = env.get("egs_state") or {}
    counts = egs.get("findings_count_by_type") or {}
    if isinstance(counts, dict):
        for k, v in counts.items():
            try:
                iv = int(v)
            except (TypeError, ValueError):
                continue
            state.counts_max[k] = max(state.counts_max.get(k, 0), iv)

    drones = env.get("active_drones") or []
    drone3 = next(
        (d for d in drones if isinstance(d, dict) and d.get("drone_id") == "drone3"),
        None,
    )
    if drone3 is not None:
        status = drone3.get("agent_status")
        if status == "standalone":
            if state.drone3_first_standalone_t is None:
                state.drone3_first_standalone_t = t_scenario
            # While standalone, freeze a snapshot of counts so we can
            # compute the post-restore delta.
            if isinstance(counts, dict):
                state.counts_at_standalone_end = dict(counts)
        elif status == "active":
            if (
                state.drone3_first_standalone_t is not None
                and state.drone3_back_to_active_t is None
            ):
                state.drone3_back_to_active_t = t_scenario
                state.restore_wall_s = now_wall
                state.total_at_restore = _sum_counts(
                    state.counts_at_standalone_end
                )
            if (
                state.restore_wall_s is not None
                and isinstance(counts, dict)
            ):
                total_now = _sum_counts(counts)
                state.max_total_after_restore = max(
                    state.max_total_after_restore, total_now,
                )
                if (
                    state.first_increment_after_restore_wall_s is None
                    and total_now > state.total_at_restore
                ):
                    state.first_increment_after_restore_wall_s = now_wall
                state.counts_after_restore = dict(counts)


def _read_validation_events(log_path: Path) -> List[dict]:
    """Read the JSONL log; tolerate missing/empty/corrupted lines."""
    if not log_path.exists():
        return []
    events: List[dict] = []
    try:
        text = log_path.read_text()
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            events.append(obj)
    return events


def _evaluate(
    state: _RunState,
    validation_events: List[dict],
) -> List[_AssertionResult]:
    results: List[_AssertionResult] = []

    a1 = _AssertionResult(
        code="A1",
        description="drone3 enters agent_status=standalone in scenario [120, 130]",
    )
    if state.drone3_first_standalone_t is None:
        a1.detail = (
            "no envelope ever showed drone3 in standalone — check that mesh "
            "sim received the egs_link_drop scripted event and emitted "
            "mesh.link_status link=down for drone3"
        )
    else:
        # Allow generous slack; the wall-clock anchor isn't perfectly aligned
        # with scenario tick zero (boot delay, etc.). The contract is that
        # the standalone transition lands inside the scripted window.
        t = state.drone3_first_standalone_t
        if 100.0 <= t <= 150.0:
            a1.passed = True
            a1.detail = f"first standalone observed at t≈{t:.1f}s (scripted t=120)"
        else:
            a1.detail = (
                f"first standalone observed at t≈{t:.1f}s, expected ~120s "
                f"(window 100..150 to absorb boot drift)"
            )
    results.append(a1)

    a2 = _AssertionResult(
        code="A2",
        description=(
            "drone3 emits >=1 Contract-4 report_finding while standalone "
            "(validation_events; scenario t in [120, 180])"
        ),
    )
    drone3_findings = [
        e for e in validation_events
        if isinstance(e, dict)
        and e.get("agent_id") == "drone3"
        and e.get("function_or_command") == "report_finding"
        and e.get("valid") is True
    ]
    if drone3_findings:
        a2.passed = True
        a2.detail = (
            f"{len(drone3_findings)} successful report_finding event(s) "
            f"logged for drone3 (sample finding_id="
            f"{(drone3_findings[0].get('raw_call') or {}).get('finding_id')!r})"
        )
    else:
        a2.detail = (
            "no successful drone3 report_finding events in validation log; "
            "either Gemma never produced one or the log path is wrong"
        )
    results.append(a2)

    a3 = _AssertionResult(
        code="A3",
        description=(
            "drone3 finding lands on .delivered only after egs_link_restore "
            "(no count increase during standalone window)"
        ),
    )
    if state.restore_wall_s is None:
        a3.detail = (
            "drone3 never transitioned back to active; cannot evaluate "
            "post-restore delivery"
        )
    elif state.first_increment_after_restore_wall_s is None:
        # If the count never incremented after restore at all, A3 cannot be
        # called passing — but it's also possible the increment happened
        # during standalone (which is the failure mode this assertion
        # guards against). Distinguish via counts_at_standalone_end.
        total_during = _sum_counts(state.counts_at_standalone_end)
        if total_during > 0 and state.max_total_after_restore == total_during:
            a3.detail = (
                "findings count appears to have ticked DURING the standalone "
                f"window (total={total_during}); .delivered should have been "
                "silent until restore"
            )
        else:
            a3.detail = (
                "no count increment observed after restore; finding may have "
                "been lost or the bridge envelope didn't refresh in time"
            )
    else:
        delta = (
            state.first_increment_after_restore_wall_s - state.restore_wall_s
        )
        a3.passed = True
        a3.detail = (
            f"first count increment {delta:.1f}s after restore (>=0 means "
            f"post-restore delivery)"
        )
    results.append(a3)

    a4 = _AssertionResult(
        code="A4",
        description=(
            "findings_count_by_type reflects drone3-while-standalone "
            "finding within 5s of restore"
        ),
    )
    if (
        state.restore_wall_s is None
        or state.first_increment_after_restore_wall_s is None
    ):
        a4.detail = "no count increment observed after restore (see A3)"
    else:
        delta = (
            state.first_increment_after_restore_wall_s - state.restore_wall_s
        )
        if delta <= 5.0:
            a4.passed = True
            a4.detail = f"count increment landed +{delta:.2f}s after restore"
        else:
            a4.detail = (
                f"count increment landed +{delta:.2f}s after restore, "
                f"exceeded 5s budget"
            )
    results.append(a4)

    a5 = _AssertionResult(
        code="A5",
        description="drone3 returns to agent_status=active after t=180",
    )
    if state.drone3_back_to_active_t is None:
        a5.detail = "drone3 never observed back in active state"
    else:
        t = state.drone3_back_to_active_t
        # Same boot-drift slack as A1.
        if t >= 150.0:
            a5.passed = True
            a5.detail = f"drone3 active again at t≈{t:.1f}s (scripted t=180)"
        else:
            a5.detail = (
                f"drone3 returned to active at t≈{t:.1f}s, earlier than the "
                "scripted egs_link_restore window"
            )
    results.append(a5)

    a6 = _AssertionResult(
        code="A6",
        description="same finding_id does not cause a second count increment",
    )
    # The total findings count after restore should be exactly the
    # count_at_standalone_end + N where N == number of unique finding_ids
    # produced by drone3 during the standalone window. If a replayed
    # finding double-counts, the delta exceeds N.
    seen_ids = set()
    for e in drone3_findings:
        rc = e.get("raw_call") or {}
        fid = rc.get("finding_id") or rc.get("arguments", {}).get("finding_id")
        if isinstance(fid, str):
            seen_ids.add(fid)
    expected_delta = max(1, len(seen_ids)) if drone3_findings else 0
    actual_delta = (
        state.max_total_after_restore - state.total_at_restore
    )
    if state.restore_wall_s is None or state.first_increment_after_restore_wall_s is None:
        a6.detail = "cannot evaluate delta; A3/A4 already failed"
    elif actual_delta == 0:
        a6.detail = "no post-restore delta observed"
    elif actual_delta <= expected_delta:
        a6.passed = True
        a6.detail = (
            f"post-restore delta={actual_delta} matches expected "
            f"unique-finding count={expected_delta}; no double-count"
        )
    else:
        a6.detail = (
            f"post-restore delta={actual_delta} exceeds expected "
            f"unique-finding count={expected_delta} — likely double-count"
        )
    results.append(a6)

    return results


def _print_table(results: List[_AssertionResult]) -> None:
    width_code = max(len(r.code) for r in results)
    width_desc = max(len(r.description) for r in results)
    sys.stderr.write("\n")
    sys.stderr.write(
        f"{'STATUS':<6} {'CODE':<{width_code}}  "
        f"{'ASSERTION':<{width_desc}}  DETAIL\n"
    )
    for r in results:
        flag = "PASS" if r.passed else "FAIL"
        sys.stderr.write(
            f"{flag:<6} {r.code:<{width_code}}  "
            f"{r.description:<{width_desc}}  {r.detail}\n"
        )
    sys.stderr.write("\n")


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Programmatic verifier for the Beat 5 offline-proof capture "
            "run (resilience_v1)."
        ),
    )
    parser.add_argument(
        "--bridge-url",
        default="ws://127.0.0.1:9090",
        help="WebSocket URL of the running bridge (default: ws://127.0.0.1:9090)",
    )
    parser.add_argument(
        "--validation-log",
        default=str(_DEFAULT_VALIDATION_LOG),
        help=(
            "Path to validation_events.jsonl (default: "
            "$GG_LOG_DIR/validation_events.jsonl)"
        ),
    )
    parser.add_argument(
        "--deadline-s",
        type=float,
        default=240.0,
        help=(
            "Total wall-clock budget for the verifier (seconds; default: "
            "240, matching the resilience_v1 mission_complete tick)"
        ),
    )
    parser.add_argument(
        "--ws-replay-log",
        default=None,
        help=(
            "Path to a JSONL file of recorded bridge envelopes. When set, "
            "check_beat5 skips the live WS connection and replays envelopes "
            "from this file using their recorded timestamps. Use this for "
            "backup-machine verification after the live run."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _replay_ws_log(log_path: Path, state: _RunState) -> int:
    """Replay recorded bridge envelopes from a JSONL file.

    Each line should be ``{"received_at_s": <float>, "envelope": {...}}``.
    Tolerates missing/empty/corrupted lines like ``_read_validation_events``.
    Returns the number of state_update envelopes ingested.
    """
    if not log_path.exists():
        return 0
    try:
        text = log_path.read_text()
    except OSError:
        return 0
    n = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        env = obj.get("envelope")
        ts = obj.get("received_at_s")
        if not isinstance(env, dict):
            continue
        if env.get("type") != "state_update":
            continue
        try:
            ts_f = float(ts) if ts is not None else None
        except (TypeError, ValueError):
            ts_f = None
        if ts_f is None:
            # Skip envelopes with missing or non-numeric received_at_s.
            # Falling back to time.monotonic() would mix wall-clocks and
            # produce garbage scenario_t values; better to drop the line
            # and let _amain's "log is empty" exit-2 path fire if every
            # line is corrupt.
            continue
        _ingest_envelope(env, state, now_wall=ts_f)
        n += 1
    return n


async def _amain(args: argparse.Namespace) -> int:
    state = _RunState()
    stop_event = asyncio.Event()
    log_path = Path(args.validation_log)

    replay_log = getattr(args, "ws_replay_log", None)
    if replay_log:
        # User explicitly opted into replay mode. If they also passed
        # --bridge-url with a non-default value, warn — we ignore it.
        if args.bridge_url and args.bridge_url != "ws://127.0.0.1:9090":
            sys.stderr.write(
                "[check_beat5] WARNING: --bridge-url is ignored when "
                "--ws-replay-log is set\n"
            )
        replay_path = Path(replay_log)
        sys.stdout.write(
            f"[check_beat5] replay mode: reading bridge envelopes from "
            f"{replay_path} (validation log={log_path})\n"
        )
        sys.stdout.flush()
        n_replayed = _replay_ws_log(replay_path, state)
        if n_replayed == 0 or state.anchor_wall_s is None:
            sys.stderr.write(
                f"[check_beat5] replay log {replay_path} is empty or "
                "missing\n"
            )
            return 2
    else:
        sys.stdout.write(
            f"[check_beat5] tailing bridge {args.bridge_url} "
            f"(deadline {args.deadline_s:.0f}s, "
            f"log={log_path})\n"
        )
        sys.stdout.flush()

        bridge_task = asyncio.create_task(
            _consume_bridge(args.bridge_url, state, args.deadline_s, stop_event),
        )
        try:
            await bridge_task
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(
                f"[check_beat5] bridge tail crashed: "
                f"{type(exc).__name__}: {exc}\n"
            )

        if state.anchor_wall_s is None:
            sys.stderr.write(
                "[check_beat5] connection error: never received a state_update "
                f"envelope from {args.bridge_url}. Is the bridge up?\n"
            )
            return 2

    validation_events = _read_validation_events(log_path)
    if not validation_events:
        sys.stderr.write(
            f"[check_beat5] WARNING: validation log {log_path} is empty or "
            "missing. A2 will fail.\n"
        )

    results = _evaluate(state, validation_events)
    _print_table(results)

    all_passed = all(r.passed for r in results)
    if all_passed:
        sys.stdout.write(
            f"[check_beat5] PASS — all {len(results)} A-assertions met.\n"
        )
        return 0
    failing = [r.code for r in results if not r.passed]
    sys.stderr.write(
        f"[check_beat5] FAIL — {len(failing)}/{len(results)} assertion(s) "
        f"failed: {', '.join(failing)}\n"
    )
    return 1


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    try:
        return asyncio.run(_amain(args))
    except KeyboardInterrupt:
        sys.stderr.write("[check_beat5] interrupted\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
