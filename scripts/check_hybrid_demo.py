"""Smoke verifier for the bridge cutover hybrid demo.

Connects to ws://localhost:9090/ (the bridge) and asserts that within the
deadline, a state_update envelope arrives whose active_drones[] covers every
drone_id from the named scenario AND whose active_findings[] is non-empty.

Envelope shape (per StateAggregator.snapshot in frontend/ws_bridge/aggregator.py):
    {type, timestamp, contract_version, egs_state, active_drones[], active_findings[]}

Usage:
    python scripts/check_hybrid_demo.py disaster_zone_v1
    python scripts/check_hybrid_demo.py disaster_zone_v1 --deadline-s 30

Exit codes:
    0  — envelope satisfied both invariants within the deadline
    1  — deadline elapsed without satisfying both invariants
    2  — connection / protocol error (bridge not running, etc.)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import List, Set

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sim.list_drones import list_drone_ids  # noqa: E402

import httpx  # noqa: E402
from httpx_ws import aconnect_ws  # noqa: E402


async def _verify(scenario: str, ws_url: str, deadline_s: float) -> int:
    expected: Set[str] = set(list_drone_ids(scenario))
    if not expected:
        print(f"[check] scenario {scenario!r} has no drones declared", file=sys.stderr)
        return 2
    print(f"[check] expecting drones={sorted(expected)} from scenario={scenario}")
    print(f"[check] connecting to {ws_url} (deadline {deadline_s:.0f}s)")

    deadline = time.monotonic() + deadline_s
    try:
        async with httpx.AsyncClient() as http_client:
            async with aconnect_ws(ws_url, http_client) as ws:
                while time.monotonic() < deadline:
                    remaining = deadline - time.monotonic()
                    try:
                        raw = await asyncio.wait_for(
                            ws.receive_text(), timeout=remaining,
                        )
                    except asyncio.TimeoutError:
                        break
                    try:
                        env = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(env, dict):
                        continue
                    if env.get("type") != "state_update":
                        continue
                    drones: List[dict] = env.get("active_drones", []) or []
                    findings: List[dict] = env.get("active_findings", []) or []
                    seen = {d.get("drone_id") for d in drones if d.get("drone_id")}
                    missing = expected - seen
                    if missing:
                        continue
                    if not findings:
                        continue
                    print(
                        f"[check] PASS — drones={sorted(seen)} "
                        f"findings_count={len(findings)}"
                    )
                    return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[check] connection error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(f"[check] FAIL — deadline {deadline_s:.0f}s elapsed without "
          f"satisfying invariants (expected drones={sorted(expected)} + "
          f"findings_count > 0)", file=sys.stderr)
    return 1


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", help="Scenario id or path (same forms as launch_swarm.sh)")
    parser.add_argument("--ws-url", default="ws://localhost:9090/")
    parser.add_argument("--deadline-s", type=float, default=20.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    return asyncio.run(_verify(args.scenario, args.ws_url, args.deadline_s))


if __name__ == "__main__":
    raise SystemExit(main())
