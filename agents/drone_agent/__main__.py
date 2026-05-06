"""Long-running drone agent entrypoint.

Usage:
    python -m agents.drone_agent --drone-id drone1 --scenario disaster_zone_v1

Subscribes to drones.<id>.camera + drones.<id>.state, runs the agent step
loop, publishes findings + broadcasts. Uses the redis-url from
shared/config.yaml unless overridden.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Iterable, Optional

import redis as _redis_sync
import redis.asyncio as _redis_async

from agents.drone_agent.runtime import DroneRuntime
from agents.drone_agent.zone_bounds import derive_zone_bounds_from_scenario
from shared.contracts.config import CONFIG
from shared.contracts.logging import setup_logging
from sim.scenario import load_scenario


_REPO_ROOT = Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drone-id", required=True, help="e.g. drone1")
    parser.add_argument("--scenario", default="disaster_zone_v1",
                        help="scenario YAML name under sim/scenarios/ or full path")
    parser.add_argument("--redis-url", default=CONFIG.transport.redis_url)
    parser.add_argument("--model", default=CONFIG.inference.drone_model)
    parser.add_argument("--ollama-endpoint", default=CONFIG.inference.ollama_drone_endpoint)
    parser.add_argument("--max-retries", type=int, default=CONFIG.validation.max_retries)
    parser.add_argument("--zone-buffer-m", type=float, default=50.0,
                        help="metres of slack on the per-drone zone bbox")
    parser.add_argument("--text-only", action="store_true",
                        help="skip image (for text-only Gemma stand-ins during integration)")
    parser.add_argument("--cpu-only", action="store_true",
                        help="force CPU inference via num_gpu=0 in Ollama")
    return parser


def _resolve_scenario_path(arg: str) -> Path:
    p = Path(arg)
    if p.exists():
        return p
    candidate = _REPO_ROOT / "sim" / "scenarios" / f"{arg}.yaml"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"scenario not found: {arg!r} (also looked at {candidate})")


async def _ollama_healthcheck(endpoint: str, model: str) -> None:
    """Best-effort check that the Ollama daemon is reachable and the model is pulled.

    Logs a clear warning and continues if anything is wrong. The agent will still
    try to call Ollama on each step — this is purely about giving the operator
    a single readable line at boot instead of a stack trace 30 seconds later.
    """
    import httpx
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{endpoint.rstrip('/')}/api/tags")
            r.raise_for_status()
            body = r.json()
            tags = body.get("models", []) or body.get("tags", [])
            names = [t.get("name") or t.get("model") for t in tags if isinstance(t, dict)]
            if model not in names:
                print(f"[drone_agent] WARNING: model {model!r} not in pulled list "
                      f"({names}). Run: ollama pull {model}", flush=True)
            else:
                print(f"[drone_agent] ollama OK at {endpoint}, model {model} present",
                      flush=True)
    except Exception as e:
        print(f"[drone_agent] WARNING: ollama healthcheck failed at {endpoint}: {e}",
              flush=True)


async def _run(args: argparse.Namespace) -> int:
    setup_logging(component_name=f"drone_agent_{args.drone_id}")
    scenario = load_scenario(_resolve_scenario_path(args.scenario))
    zone_bounds = derive_zone_bounds_from_scenario(
        scenario, args.drone_id, buffer_m=args.zone_buffer_m,
    )

    await _ollama_healthcheck(args.ollama_endpoint, args.model)

    sync_client = _redis_sync.Redis.from_url(args.redis_url)
    async_client = _redis_async.from_url(args.redis_url)

    runtime = DroneRuntime(
        drone_id=args.drone_id,
        scenario=scenario,
        zone_bounds=zone_bounds,
        sync_client=sync_client,
        async_client=async_client,
        ollama_endpoint=args.ollama_endpoint,
        model=args.model,
        max_retries=args.max_retries,
        send_image=not args.text_only,
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(runtime.stop()))

    print(
        f"[drone_agent] drone_id={args.drone_id} scenario={scenario.scenario_id} "
        f"redis={args.redis_url} model={args.model}",
        flush=True,
    )
    try:
        await runtime.run()
    finally:
        await async_client.aclose()
        sync_client.close()
    return 0


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
