"""End-to-end Playwright coverage for multi-drone scenarios.

Mirrors the harness shape of ``test_e2e_playwright.py`` but spawns one
``dev_fake_producers.py`` instance per drone (``--emit=state,findings``)
plus a single global ``--emit=egs`` instance. The single-drone file's
``pipeline`` fixture is intentionally NOT reused — different roster, and
keeping the fixtures independent prevents subtle module-scope coupling
between the two suites.

drone roster: drone1, drone2, drone3 — matches Hazim's
``sim/scenarios/disaster_zone_v1.yaml`` so failures here translate
directly to demo-time risk.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import httpx
import pytest
from httpx_ws import aconnect_ws
import asyncio


# Mirror the single-drone e2e file: opt into the ``e2e`` marker so this
# suite is excluded from the default ``pytest -m "not e2e"`` quick runs,
# and bump the per-test timeout above pytest.ini's 30s default — the
# multi-drone fixture cold-starts redis + uvicorn + 4 producers + a
# static server, which can comfortably exceed 30s on a slow CI runner.
pytestmark = [pytest.mark.e2e, pytest.mark.timeout(90)]


_REPO_ROOT: Path = Path(__file__).resolve().parents[3]
_DEV_PRODUCER: Path = _REPO_ROOT / "scripts" / "dev_fake_producers.py"
_FLUTTER_WEB_DIR: Path = (
    _REPO_ROOT / "frontend" / "flutter_dashboard" / "build" / "web"
)
_DRONE_ROSTER: List[str] = ["drone1", "drone2", "drone3"]


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _resolve_redis_server() -> str:
    for candidate in ("/opt/homebrew/bin/redis-server", "/usr/local/bin/redis-server", "redis-server"):
        if os.path.isabs(candidate):
            if os.path.exists(candidate):
                return candidate
        else:
            from shutil import which
            resolved = which(candidate)
            if resolved:
                return resolved
    pytest.skip("redis-server not on PATH; install via brew/apt to run e2e")


def _resolve_redis_cli() -> str:
    for candidate in ("/opt/homebrew/bin/redis-cli", "/usr/local/bin/redis-cli", "redis-cli"):
        if os.path.isabs(candidate):
            if os.path.exists(candidate):
                return candidate
        else:
            from shutil import which
            resolved = which(candidate)
            if resolved:
                return resolved
    pytest.skip("redis-cli not on PATH; install via brew/apt to run e2e")


def _wait_redis_ready(redis_cli: str, port: int, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = subprocess.run(
            [redis_cli, "-p", str(port), "ping"],
            capture_output=True, text=True, timeout=2.0,
        )
        if r.returncode == 0 and r.stdout.strip().upper() == "PONG":
            return
        time.sleep(0.1)
    raise RuntimeError(f"redis on port {port} did not become ready in {timeout_s}s")


def _wait_http_ready(url: str, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            r = httpx.get(url, timeout=1.0)
            if r.status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise RuntimeError(f"{url} did not become ready in {timeout_s}s")


def _terminate_proc(proc: Optional[subprocess.Popen], label: str) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            print(f"[multi_drone_pipeline] WARNING: {label} did not exit", file=sys.stderr)


@pytest.fixture(scope="module")
def multi_drone_pipeline() -> Iterator[Dict[str, Any]]:
    """Spin up redis + bridge + 1 egs producer + 3 drone producers + http.server.

    Yields ports/urls and the resolved drone roster. Tears everything down in
    a ``try/finally`` so a test failure never leaks subprocesses.

    FIFO eviction note (module-scope gotcha):
        The bridge keeps at most ``BRIDGE_MAX_FINDINGS`` findings (default
        50, see ``frontend/ws_bridge/config.py``). Three drone producers at
        ``--tick-s 0.2`` ship ~one finding/second aggregate, so the cap
        fills in ~50s of fixture wall-clock. Tests that share this fixture
        (module scope) will see oldest findings evicted across the suite.
        Assertions should hold across eviction — e.g., "at least one
        finding from each drone is present at some point in the capture
        window" rather than "the first finding ever produced is still
        present in test N".
    """
    if not _FLUTTER_WEB_DIR.is_dir() or not (_FLUTTER_WEB_DIR / "index.html").exists():
        pytest.skip(
            f"Flutter web build missing at {_FLUTTER_WEB_DIR}. Run "
            "`flutter build web` in frontend/flutter_dashboard first."
        )

    redis_server = _resolve_redis_server()
    redis_cli = _resolve_redis_cli()

    redis_port = _pick_free_port()
    bridge_port = _pick_free_port()
    flutter_port = _pick_free_port()

    redis_proc: Optional[subprocess.Popen] = None
    bridge_proc: Optional[subprocess.Popen] = None
    egs_producer: Optional[subprocess.Popen] = None
    drone_producers: List[subprocess.Popen] = []
    http_proc: Optional[subprocess.Popen] = None

    try:
        # 1. Redis on isolated port, no persistence.
        redis_proc = subprocess.Popen(
            [
                redis_server,
                "--port", str(redis_port),
                "--daemonize", "no",
                "--save", "",
                "--appendonly", "no",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_redis_ready(redis_cli, redis_port, timeout_s=5.0)

        # 2. Bridge via uvicorn, pointed at the isolated Redis.
        bridge_env = os.environ.copy()
        bridge_env["REDIS_URL"] = f"redis://127.0.0.1:{redis_port}"
        bridge_env["BRIDGE_TICK_S"] = "0.25"
        bridge_env["BRIDGE_RECONNECT_MAX_S"] = "2"
        existing_pp = bridge_env.get("PYTHONPATH", "")
        bridge_env["PYTHONPATH"] = (
            f"{_REPO_ROOT}{os.pathsep}{existing_pp}" if existing_pp else str(_REPO_ROOT)
        )
        bridge_proc = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn",
                "frontend.ws_bridge.main:app",
                "--host", "127.0.0.1",
                "--port", str(bridge_port),
                "--log-level", "warning",
            ],
            env=bridge_env,
            cwd=str(_REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_http_ready(f"http://127.0.0.1:{bridge_port}/health", timeout_s=15.0)

        # 3. Single egs producer (1 instance — egs.state is global).
        egs_producer = subprocess.Popen(
            [
                sys.executable, str(_DEV_PRODUCER),
                "--emit", "egs",
                "--redis-url", f"redis://127.0.0.1:{redis_port}",
                "--tick-s", "0.2",
            ],
            cwd=str(_REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # 4. Per-drone producers (state + findings each).
        for drone_id in _DRONE_ROSTER:
            proc = subprocess.Popen(
                [
                    sys.executable, str(_DEV_PRODUCER),
                    "--emit", "state,findings",
                    "--drone-id", drone_id,
                    "--redis-url", f"redis://127.0.0.1:{redis_port}",
                    "--tick-s", "0.2",
                ],
                cwd=str(_REPO_ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            drone_producers.append(proc)

        # 5. Static server for Flutter web build.
        http_proc = subprocess.Popen(
            [
                sys.executable, "-m", "http.server", str(flutter_port),
                "--directory", str(_FLUTTER_WEB_DIR),
                "--bind", "127.0.0.1",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_http_ready(f"http://127.0.0.1:{flutter_port}/", timeout_s=10.0)

        yield {
            "redis_port": redis_port,
            "bridge_port": bridge_port,
            "flutter_port": flutter_port,
            "redis_url": f"redis://127.0.0.1:{redis_port}",
            "bridge_ws_url": f"ws://127.0.0.1:{bridge_port}/",
            "bridge_health_url": f"http://127.0.0.1:{bridge_port}/health",
            "flutter_url": f"http://127.0.0.1:{flutter_port}/",
            "drone_roster": list(_DRONE_ROSTER),
        }
    finally:
        _terminate_proc(egs_producer, "egs_producer")
        for i, p in enumerate(drone_producers):
            _terminate_proc(p, f"drone_producer[{i}]")
        _terminate_proc(http_proc, "http.server")
        _terminate_proc(bridge_proc, "uvicorn_bridge")
        _terminate_proc(redis_proc, "redis-server")


async def _capture_envelopes(
    bridge_ws_url: str, *, min_envelopes: int, timeout_s: float,
) -> List[Dict[str, Any]]:
    """Connect to the bridge WS and accumulate up to ``min_envelopes`` parsed
    state_update envelopes (or until ``timeout_s`` elapses). Returns parsed
    dicts only — invalid JSON or non-state_update messages are skipped."""
    deadline = time.monotonic() + timeout_s
    envelopes: List[Dict[str, Any]] = []
    async with httpx.AsyncClient() as c:
        async with aconnect_ws(bridge_ws_url, c) as ws:
            while time.monotonic() < deadline and len(envelopes) < min_envelopes:
                # Clamp to non-negative: on a slow runner, the gap between
                # the loop guard and this line can flip ``remaining`` negative,
                # which would make ``asyncio.wait_for`` raise immediately.
                # Clamping makes the deadline-elapsed exit path explicit
                # rather than relying on accidentally-correct exception flow.
                remaining = max(0.0, deadline - time.monotonic())
                try:
                    raw = await asyncio.wait_for(ws.receive_text(), timeout=remaining)
                except asyncio.TimeoutError:
                    break
                try:
                    env = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(env, dict) and env.get("type") == "state_update":
                    envelopes.append(env)
    return envelopes


def test_smoke_bridge_emits_envelopes(multi_drone_pipeline: Dict[str, Any]) -> None:
    """Sanity check that the multi-drone pipeline produces ANY envelope.
    Real multi-drone assertions live in subsequent tests; this one fails
    fast if the harness itself is broken."""
    envelopes = asyncio.run(
        _capture_envelopes(
            multi_drone_pipeline["bridge_ws_url"],
            min_envelopes=3,
            timeout_s=15.0,
        )
    )
    assert len(envelopes) >= 3, (
        f"Expected >=3 state_update envelopes; got {len(envelopes)}. "
        f"Pipeline may be misconfigured."
    )
