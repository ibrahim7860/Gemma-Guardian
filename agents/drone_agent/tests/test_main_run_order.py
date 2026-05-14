"""Lock the call-order invariant of agents.drone_agent.__main__._run.

The healthcheck must be awaited BEFORE Redis clients are constructed, so the
operator sees a readable WARNING line on boot instead of a Redis stack trace
when Ollama is the actual problem.

This is a regression guard, not a behavioural test — see test_main_ollama_healthcheck.py
for the three branches of the healthcheck itself.
"""
from __future__ import annotations

import pytest

import agents.drone_agent.__main__ as drone_main


@pytest.mark.asyncio
async def test_run_calls_healthcheck_before_redis(monkeypatch):
    calls: list[str] = []

    async def fake_healthcheck(endpoint: str, model: str) -> None:
        calls.append("healthcheck")

    def fake_redis_sync_from_url(*_args, **_kwargs):
        calls.append("redis_sync")
        raise RuntimeError("stop here — we only care about ordering")

    def fake_redis_async_from_url(*_args, **_kwargs):
        calls.append("redis_async")
        raise RuntimeError("stop here — we only care about ordering")

    monkeypatch.setattr(drone_main, "_ollama_healthcheck", fake_healthcheck)
    monkeypatch.setattr(drone_main._redis_sync.Redis, "from_url", staticmethod(fake_redis_sync_from_url))
    monkeypatch.setattr(drone_main._redis_async, "from_url", fake_redis_async_from_url)

    args = drone_main.build_parser().parse_args([
        "--drone-id", "drone1",
        "--scenario", "disaster_zone_v1",
        "--text-only",
    ])

    with pytest.raises(RuntimeError, match="stop here"):
        await drone_main._run(args)

    assert calls, "no calls recorded — neither healthcheck nor redis ran"
    assert calls[0] == "healthcheck", (
        f"healthcheck must run before ANY redis construction (sync or async); got {calls}"
    )
