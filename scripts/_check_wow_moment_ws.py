"""WebSocket sub-check for scripts/check_wow_moment.sh.

Connects to the bridge, snapshots state_update envelopes for a configurable
window (default 5s), and exits 0 iff at least one envelope carries a non-
empty `replan_in_flight_attempt_log`. Exits 1 otherwise.

Kept as its own module (rather than inlined into the shell script) so it
can be unit-tested via subprocess without standing up a live bridge.

CLI:
    uv run python scripts/_check_wow_moment_ws.py \\
        --bridge-url ws://127.0.0.1:9090 \\
        --window-s 5.0

Exit codes:
    0  — at least one envelope had a non-empty replan_in_flight_attempt_log.
    1  — none seen within the window.
    2  — bridge connection / protocol error.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from typing import List, Optional


async def _amain(args: argparse.Namespace) -> int:
    import httpx
    from httpx_ws import aconnect_ws

    deadline = time.monotonic() + args.window_s
    saw_populated: bool = False
    saw_envelopes: int = 0
    try:
        async with httpx.AsyncClient() as http:
            async with aconnect_ws(args.bridge_url, http) as ws:
                while time.monotonic() < deadline:
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
                    saw_envelopes += 1
                    log = (env.get("egs_state") or {}).get(
                        "replan_in_flight_attempt_log", [],
                    )
                    if isinstance(log, list) and len(log) > 0:
                        saw_populated = True
                        break
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(
            f"[check_wow_moment_ws] bridge connection error: "
            f"{type(exc).__name__}: {exc}\n"
        )
        return 2

    if saw_populated:
        sys.stdout.write(
            "[check_wow_moment_ws] PASS — at least one envelope carried a "
            "non-empty replan_in_flight_attempt_log "
            f"(observed {saw_envelopes} state_update envelopes total)\n"
        )
        return 0
    sys.stderr.write(
        "[check_wow_moment_ws] FAIL — no envelope carried a non-empty "
        "replan_in_flight_attempt_log within the "
        f"{args.window_s:.1f}s window "
        f"(observed {saw_envelopes} state_update envelopes total)\n"
    )
    return 1


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--bridge-url",
        default="ws://127.0.0.1:9090",
        help="WebSocket URL of the running bridge (default: ws://127.0.0.1:9090)",
    )
    p.add_argument(
        "--window-s",
        type=float,
        default=5.0,
        help="How long to listen for envelopes (seconds; default 5.0)",
    )
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    try:
        return asyncio.run(_amain(args))
    except KeyboardInterrupt:
        sys.stderr.write("[check_wow_moment_ws] interrupted\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
