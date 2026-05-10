"""Tiny WS client that records bridge state_update envelopes as JSONL.

Subscribes to the ws_bridge WebSocket and appends each received
``state_update`` envelope to an output file as one JSON line of the form::

    {"received_at_s": <time.monotonic() float>, "envelope": {...}}

This file is consumed by ``scripts/check_beat5.py --ws-replay-log <path>``
so a backup machine (or post-run rerun) can re-verify A1-A6 from
artifacts alone, without a live bridge.

Run alongside the live capture stack; expected lifetime is a single
scenario window (default 300s — slightly longer than the 240s
resilience_v1 mission_complete tick). Exits cleanly on SIGTERM or
Ctrl-C, flushing the output file.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional


_DEFAULT_OUT = Path(
    os.environ.get("GG_LOG_DIR", "/tmp/gemma_guardian_logs")
) / "ws_frames.jsonl"


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record ws_bridge state_update envelopes as JSONL.",
    )
    parser.add_argument(
        "--bridge-url",
        default="ws://127.0.0.1:9090",
        help="WebSocket URL of the bridge (default: ws://127.0.0.1:9090)",
    )
    parser.add_argument(
        "--out",
        default=str(_DEFAULT_OUT),
        help="Output JSONL path (default: $GG_LOG_DIR/ws_frames.jsonl)",
    )
    parser.add_argument(
        "--deadline-s",
        type=float,
        default=300.0,
        help="Max wall-clock recording window in seconds (default: 300)",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


async def _record(
    bridge_url: str,
    out_path: Path,
    deadline_s: float,
    stop_event: asyncio.Event,
) -> int:
    import httpx
    from httpx_ws import aconnect_ws

    out_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + deadline_s
    n = 0
    with open(out_path, "a", buffering=1, encoding="utf-8") as fh:
        async with httpx.AsyncClient() as http_client:
            async with aconnect_ws(bridge_url, http_client) as ws:
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
                    fh.write(json.dumps({
                        "received_at_s": time.monotonic(),
                        "envelope": env,
                    }) + "\n")
                    n += 1
    return n


async def _amain(args: argparse.Namespace) -> int:
    out_path = Path(args.out)
    sys.stderr.write(
        f"[ws_recorder] recording bridge={args.bridge_url} "
        f"to={out_path} deadline={args.deadline_s:.0f}s\n"
    )
    sys.stderr.flush()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            # Windows / some sandboxes: fall through, KeyboardInterrupt
            # will still bubble.
            pass

    n = 0
    try:
        n = await _record(args.bridge_url, out_path, args.deadline_s, stop_event)
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(
            f"[ws_recorder] connection error: {type(exc).__name__}: {exc}\n"
        )
        return 1
    sys.stderr.write(f"[ws_recorder] wrote {n} envelopes, exiting\n")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    try:
        return asyncio.run(_amain(args))
    except KeyboardInterrupt:
        sys.stderr.write("[ws_recorder] interrupted\n")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
