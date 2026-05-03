#!/usr/bin/env python3
"""Phase 3 dev helper: subscribe to egs.operator_actions and pretty-print.

Stand-in for the EGS-side subscriber that lands in Phase 4. Validates each
incoming payload against the operator_actions schema and prints a one-liner
per message so we can verify the bridge → Redis publish path locally without
a real EGS process.

Usage:
    PYTHONPATH=. python3 scripts/dev_actions_logger.py
    PYTHONPATH=. python3 scripts/dev_actions_logger.py --redis-url redis://localhost:6379
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone

import redis.asyncio as redis_async

from shared.contracts import validate
from shared.contracts.topics import EGS_OPERATOR_ACTIONS


def _short(s: str, n: int = 32) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


async def _run(redis_url: str) -> None:
    client = redis_async.Redis.from_url(redis_url)
    pubsub = client.pubsub()
    await pubsub.subscribe(EGS_OPERATOR_ACTIONS)
    print(
        f"[dev_actions_logger] subscribed to {EGS_OPERATOR_ACTIONS} on {redis_url}",
        file=sys.stderr,
    )
    try:
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
            if msg is None:
                continue
            data = msg.get("data")
            if isinstance(data, (bytes, bytearray)):
                raw = bytes(data).decode("utf-8", errors="replace")
            else:
                raw = str(data)
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                print(f"[INVALID json] {exc}: {_short(raw)}")
                continue
            outcome = validate("operator_actions", payload)
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + (
                f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"
            )
            if not outcome.valid:
                print(
                    f"{ts}  [INVALID schema]  errors={[e.message for e in outcome.errors][:2]}  payload={_short(raw, 80)}"
                )
                continue
            kind = payload.get("kind", "?")
            if kind == "finding_approval":
                print(
                    f"{ts}  finding_approval  action={payload['action']:8s}  "
                    f"finding_id={payload['finding_id']:20s}  command_id={payload['command_id']}"
                )
            else:
                print(f"{ts}  {kind}  payload={_short(raw, 80)}")
    finally:
        try:
            await pubsub.unsubscribe()
        finally:
            await pubsub.aclose()
            await client.aclose()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--redis-url", default="redis://localhost:6379")
    args = p.parse_args()
    try:
        asyncio.run(_run(args.redis_url))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
