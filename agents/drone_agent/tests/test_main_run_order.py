"""Lock the call-order invariant of agents.drone_agent.__main__._run.

The healthcheck must be awaited BEFORE Redis clients or DroneRuntime are
constructed, so the operator sees a readable WARNING line on boot instead
of a Redis stack trace when Ollama is the actual problem.

This is a regression guard, not a behavioural test — see test_main_ollama_healthcheck.py
for the three branches of the healthcheck itself.
"""
from __future__ import annotations

import argparse

import pytest

import agents.drone_agent.__main__ as drone_main


@pytest.mark.asyncio
async def test_run_calls_healthcheck_before_redis(monkeypatch, tmp_path):
    calls: list[str] = []

    async def fake_healthcheck(endpoint: str, model: str) -> None:
        calls.append("healthcheck")

    def fake_redis_from_url(*_args, **_kwargs):
        calls.append("redis_sync")
        raise RuntimeError("stop here — we only care about ordering")

    monkeypatch.setattr(drone_main, "_ollama_healthcheck", fake_healthcheck)
    monkeypatch.setattr(drone_main._redis_sync.Redis, "from_url", classmethod(
        lambda cls, *a, **kw: fake_redis_from_url(*a, **kw)
    ))

    args = argparse.Namespace(
        drone_id="drone1",
        scenario="disaster_zone_v1",
        redis_url="redis://localhost:6379/0",
        model="gemma4:e2b",
        ollama_endpoint="http://localhost:11434",
        max_retries=3,
        zone_buffer_m=50.0,
        text_only=True,
        cpu_only=False,
        standalone=False,
    )

    with pytest.raises(RuntimeError, match="stop here"):
        await drone_main._run(args)

    assert calls == ["healthcheck", "redis_sync"], (
        f"healthcheck must run before redis construction; got {calls}"
    )
