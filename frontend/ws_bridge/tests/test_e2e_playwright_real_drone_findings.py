"""Playwright e2e: real drone agent process → bridge → Flutter findings panel.

CI-friendly variant of test_e2e_playwright_multi_drone.py. The fake findings
producer is replaced with a real `python -m agents.drone_agent` process,
backed by scripts/ollama_mock_server.py. Asserts the real Contract-4 finding
lands on drones.drone1.findings.

This is the GATE 2 acceptance test: it proves Kaleel's wiring lands in the
operator UI without manual smoke. The Playwright UI assertion is intentionally
left as a `pytest.skip` — the implementer for the full UI version copies the
helper from test_e2e_playwright_multi_drone.py.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_for_port(port: int, deadline_s: float) -> bool:
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


@contextmanager
def _spawn(cmd: list[str], env: dict | None = None, name: str = "child"):
    proc = subprocess.Popen(
        cmd, cwd=str(REPO_ROOT),
        env={**os.environ, **(env or {})},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.mark.timeout(120)
def test_real_drone_finding_renders_in_dashboard(tmp_path):
    if not shutil.which("redis-server"):
        pytest.skip("redis-server not on PATH")

    redis_port = _free_port()
    ollama_port = _free_port()
    bridge_port = _free_port()

    # Per-test redis instance.
    redis_proc = subprocess.Popen(
        ["redis-server", "--port", str(redis_port), "--save", "", "--appendonly", "no"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    assert _wait_for_port(redis_port, 5), "redis did not come up"
    redis_url = f"redis://127.0.0.1:{redis_port}/0"
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    try:
        with _spawn(
            [sys.executable, "scripts/ollama_mock_server.py", "--port", str(ollama_port)],
            name="ollama-mock",
        ):
            assert _wait_for_port(ollama_port, 5), "ollama mock did not come up"

            # NOTE: We use disaster_zone_v1 (3 drones) because waypoint_runner
            # enforces a strict match against shared/config.yaml's
            # mission.drone_count=3. single_drone_smoke trips that guard.
            # The drone agent subscribes only to drone1, so the other two
            # drones' state/camera channels are simply unused traffic.
            scenario = "disaster_zone_v1"
            with _spawn(
                [sys.executable, "-m", "sim.waypoint_runner",
                 "--scenario", scenario, "--redis-url", redis_url],
                name="waypoint",
            ), _spawn(
                [sys.executable, "-m", "sim.frame_server",
                 "--scenario", scenario, "--redis-url", redis_url],
                name="frame",
            ), _spawn(
                [sys.executable, "-m", "agents.drone_agent",
                 "--drone-id", "drone1", "--scenario", scenario,
                 "--redis-url", redis_url,
                 "--ollama-endpoint", f"http://127.0.0.1:{ollama_port}"],
                env={"GG_LOG_DIR": str(log_dir)},
                name="drone-agent",
            ), _spawn(
                [sys.executable, "-m", "uvicorn", "frontend.ws_bridge.main:app",
                 "--host", "127.0.0.1", "--port", str(bridge_port)],
                env={"REDIS_URL": redis_url},
                name="bridge",
            ):
                assert _wait_for_port(bridge_port, 10), "bridge did not come up"

                import redis as _redis
                client = _redis.Redis.from_url(redis_url)
                pubsub = client.pubsub()
                pubsub.subscribe("drones.drone1.findings")
                pubsub.get_message(timeout=1)
                deadline = time.time() + 60
                got = None
                while time.time() < deadline:
                    msg = pubsub.get_message(timeout=1)
                    if msg and msg["type"] == "message":
                        import json
                        got = json.loads(msg["data"])
                        break
                assert got is not None, "no real finding observed within 60s"
                assert got["source_drone_id"] == "drone1"
                assert got["type"] == "victim"
                victim_finding_id = got["finding_id"]

                # Bridge → WebSocket assertion: prove the bridge's drones.<id>.findings
                # subscriber forwards the agent's real finding into the dashboard's
                # state_update envelopes. Mirrors test_e2e_playwright_multi_drone.py
                # but against the real drone agent (not the fake findings producer).
                import asyncio as _asyncio
                import httpx as _httpx
                from httpx_ws import aconnect_ws as _aconnect_ws

                async def _wait_for_finding_in_envelope(ws_url: str, fid: str,
                                                        timeout_s: float = 30.0) -> dict:
                    deadline = _asyncio.get_event_loop().time() + timeout_s
                    async with _httpx.AsyncClient() as c:
                        async with _aconnect_ws(ws_url, c) as ws:
                            while _asyncio.get_event_loop().time() < deadline:
                                remaining = max(0.0, deadline - _asyncio.get_event_loop().time())
                                try:
                                    raw = await _asyncio.wait_for(ws.receive_text(), timeout=remaining)
                                except _asyncio.TimeoutError:
                                    break
                                try:
                                    env = json.loads(raw)
                                except json.JSONDecodeError:
                                    continue
                                if env.get("type") != "state_update":
                                    continue
                                for f in env.get("active_findings") or []:
                                    if f.get("finding_id") == fid:
                                        return f
                    raise AssertionError(
                        f"finding {fid!r} did not appear in any state_update envelope "
                        f"within {timeout_s}s — bridge.findings subscriber may be broken"
                    )

                ws_url = f"ws://127.0.0.1:{bridge_port}/"
                rendered = _asyncio.run(_wait_for_finding_in_envelope(ws_url, victim_finding_id))
                assert rendered["source_drone_id"] == "drone1"
                assert rendered["type"] == "victim"
                assert rendered["severity"] == 4

    finally:
        redis_proc.terminate()
        try:
            redis_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            redis_proc.kill()
