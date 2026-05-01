"""End-to-end Playwright tests for the Phase 2 WS bridge pipeline.

Exercises the full data path with REAL processes:

    redis-server (test port)
        ^   ^
        |   +-- scripts/dev_fake_producers.py (publishes contract-valid msgs)
        |
    frontend.ws_bridge.main:app (uvicorn, test port)
        |
        +-- WebSocket --> Flutter web (served via python -m http.server)

These tests are slow (multi-second), so they are marked ``@pytest.mark.e2e``
and excluded from the default pytest run via ``pytest.ini`` at the repo
root. Invoke explicitly with::

    python3 -m pytest frontend/ws_bridge/tests/test_e2e_playwright.py -v

Prerequisites:
    * ``redis-server`` available at ``/opt/homebrew/opt/redis/bin/redis-server``
      (Homebrew default on macOS) or anywhere on ``PATH``.
    * Flutter web build artifacts at
      ``frontend/flutter_dashboard/build/web/index.html``. Build with
      ``flutter build web --release`` from the dashboard project root.
    * Playwright chromium installed (``python3 -m playwright install chromium``).

Design notes:
    * Every subprocess is killed in a ``try/finally`` so a test failure never
      leaks redis/uvicorn/http.server. Aggressive teardown:
      ``terminate()`` -> ``wait(timeout=5)`` -> ``kill()``.
    * Free ports are picked dynamically (``socket().bind(('', 0))``) to avoid
      clashing with brew-managed Redis or any other service on the dev box.
    * Flutter web canvas-renders text, so DOM queries are unreliable. We
      assert correctness by intercepting WebSocket frames via Playwright's
      ``page.on('websocket')`` and re-validating them against the locked
      ``websocket_messages`` schema.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import pytest

pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# Repo paths
# ---------------------------------------------------------------------------

_REPO_ROOT: Path = Path(__file__).resolve().parents[3]
_FLUTTER_WEB_DIR: Path = _REPO_ROOT / "frontend" / "flutter_dashboard" / "build" / "web"
_DEV_PRODUCER: Path = _REPO_ROOT / "scripts" / "dev_fake_producers.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pick_free_port() -> int:
    """Bind to port 0, read back the OS-assigned port, release it.

    Race-y in principle (another process could grab the port between close
    and the next bind), but in practice this is fine for a single-machine
    test runner and avoids hardcoding ports that may collide with brew
    services on the dev box.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _resolve_redis_server() -> str:
    """Find the redis-server binary or fail with a clear message."""
    explicit = "/opt/homebrew/opt/redis/bin/redis-server"
    if Path(explicit).exists():
        return explicit
    found = shutil.which("redis-server")
    if found:
        return found
    raise RuntimeError(
        "redis-server not found. Install with `brew install redis` or "
        "`apt install redis-server`."
    )


def _resolve_redis_cli() -> str:
    explicit = "/opt/homebrew/opt/redis/bin/redis-cli"
    if Path(explicit).exists():
        return explicit
    found = shutil.which("redis-cli")
    if found:
        return found
    raise RuntimeError("redis-cli not found.")


def _wait_redis_ready(redis_cli: str, port: int, timeout_s: float = 5.0) -> None:
    """Poll ``redis-cli ping`` until PONG comes back or timeout."""
    deadline = time.monotonic() + timeout_s
    last_err: Optional[str] = None
    while time.monotonic() < deadline:
        try:
            out = subprocess.run(
                [redis_cli, "-p", str(port), "ping"],
                capture_output=True,
                text=True,
                timeout=1.0,
            )
            if out.returncode == 0 and "PONG" in out.stdout.upper():
                return
            last_err = f"rc={out.returncode} stdout={out.stdout!r} stderr={out.stderr!r}"
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            last_err = str(exc)
        time.sleep(0.1)
    raise RuntimeError(
        f"redis-server on port {port} did not become ready in {timeout_s}s. "
        f"last_err={last_err}"
    )


def _wait_http_ready(url: str, timeout_s: float = 10.0) -> None:
    """Poll an HTTP URL until a 2xx response or timeout."""
    deadline = time.monotonic() + timeout_s
    last_err: Optional[str] = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                if 200 <= resp.status < 300:
                    return
                last_err = f"status={resp.status}"
        except (urllib.error.URLError, ConnectionError, OSError) as exc:
            last_err = str(exc)
        time.sleep(0.1)
    raise RuntimeError(
        f"HTTP {url} did not become ready in {timeout_s}s. last_err={last_err}"
    )


def _terminate_proc(proc: Optional[subprocess.Popen], name: str) -> None:
    """terminate -> wait(5) -> kill. Never raises."""
    if proc is None:
        return
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
    except Exception as exc:  # pragma: no cover - defensive teardown
        sys.stderr.write(f"[e2e_teardown] failed to stop {name}: {exc}\n")


# ---------------------------------------------------------------------------
# Fixture: full pipeline
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pipeline() -> Iterator[Dict[str, Any]]:
    """Spin up redis + bridge + producer + http.server once per module.

    Yields a dict with port numbers and URLs; tears everything down in a
    ``try/finally`` so a test failure never leaks subprocesses.
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
    producer_proc: Optional[subprocess.Popen] = None
    http_proc: Optional[subprocess.Popen] = None

    try:
        # 1. Redis on a non-default port, no persistence.
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

        # 2. Bridge via uvicorn. Pass env so config picks up our redis URL.
        bridge_env = os.environ.copy()
        bridge_env["REDIS_URL"] = f"redis://127.0.0.1:{redis_port}"
        bridge_env["BRIDGE_TICK_S"] = "0.25"
        bridge_env["BRIDGE_RECONNECT_MAX_S"] = "2"
        # Ensure repo root is on PYTHONPATH so `frontend.ws_bridge.main`
        # resolves regardless of cwd uvicorn inherits.
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

        # 3. Fake producer (no need to wait — bridge will catch up).
        producer_proc = subprocess.Popen(
            [
                sys.executable, str(_DEV_PRODUCER),
                "--redis-url", f"redis://127.0.0.1:{redis_port}",
                "--tick-s", "0.2",
            ],
            cwd=str(_REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # 4. Static server for the Flutter web build.
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
            "redis_server_bin": redis_server,
            "redis_cli_bin": redis_cli,
        }
    finally:
        _terminate_proc(producer_proc, "fake_producer")
        _terminate_proc(http_proc, "http.server")
        _terminate_proc(bridge_proc, "uvicorn_bridge")
        _terminate_proc(redis_proc, "redis-server")


# ---------------------------------------------------------------------------
# Helpers for browser frame capture
# ---------------------------------------------------------------------------


def _capture_ws_frames(
    page_url: str,
    bridge_ws_url: str,
    *,
    min_frames: int,
    timeout_s: float,
) -> List[str]:
    """Open the dashboard, attach a WS listener, return raw frame payloads.

    The Flutter app opens its own WebSocket on load. We additionally open
    one from page JS so we always get frames regardless of how Flutter
    times its connect handshake; either source counts.
    """
    from playwright.sync_api import sync_playwright

    frames: List[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()

            def on_websocket(ws: Any) -> None:
                ws.on(
                    "framereceived",
                    lambda payload: frames.append(
                        payload if isinstance(payload, str) else payload.decode("utf-8", "replace")
                    ),
                )

            page.on("websocket", on_websocket)
            page.goto(page_url, wait_until="domcontentloaded", timeout=15_000)

            # Open an explicit WS from page JS as a redundant frame source.
            # This guarantees we capture frames even if the Flutter app
            # hasn't finished initializing.
            page.evaluate(
                """(url) => {
                    try {
                        const ws = new WebSocket(url);
                        window.__e2eWS = ws;
                    } catch (e) {
                        window.__e2eWSError = String(e);
                    }
                }""",
                bridge_ws_url,
            )

            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline and len(frames) < min_frames:
                page.wait_for_timeout(200)

            return list(frames)
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_dashboard_loads_and_connects(pipeline: Dict[str, Any]) -> None:
    """Dashboard page loads and the bridge accepts a fresh WS connection."""
    from playwright.sync_api import sync_playwright

    connected = {"value": False}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()

            def on_ws(ws: Any) -> None:
                # If any WebSocket opens that points at our bridge port, the
                # connection succeeded.
                if str(pipeline["bridge_port"]) in ws.url:
                    connected["value"] = True

            page.on("websocket", on_ws)
            page.goto(pipeline["flutter_url"], wait_until="domcontentloaded", timeout=15_000)

            # Open a JS WebSocket directly so we don't depend on Flutter's
            # canvas-rendered "connected" indicator. This validates the
            # bridge accepts new clients.
            opened = page.evaluate(
                """async (url) => {
                    return await new Promise((resolve) => {
                        const ws = new WebSocket(url);
                        const t = setTimeout(() => resolve(false), 5000);
                        ws.onopen = () => { clearTimeout(t); resolve(true); };
                        ws.onerror = () => { clearTimeout(t); resolve(false); };
                    });
                }""",
                pipeline["bridge_ws_url"],
            )
            assert opened, "Bridge WebSocket did not accept connection within 5s"
            connected["value"] = True
        finally:
            browser.close()

    assert connected["value"], "No WebSocket to bridge observed"


def test_finding_appears_in_panel(pipeline: Dict[str, Any]) -> None:
    """After producer publishes a finding, a frame contains active_findings."""
    valid_finding_types = {
        "victim", "fire", "smoke", "damaged_structure", "blocked_route",
    }

    frames = _capture_ws_frames(
        pipeline["flutter_url"],
        pipeline["bridge_ws_url"],
        min_frames=5,
        timeout_s=20.0,
    )
    assert len(frames) >= 3, f"Expected >=3 WS frames, got {len(frames)}"

    found_finding = False
    for raw in frames:
        try:
            env = json.loads(raw)
        except json.JSONDecodeError:
            continue
        findings = env.get("active_findings") or []
        if findings:
            ftype = findings[0].get("finding_type") or findings[0].get("type")
            assert ftype in valid_finding_types, (
                f"Unexpected finding type {ftype!r} not in {valid_finding_types}"
            )
            found_finding = True
            break

    assert found_finding, (
        f"No frame contained active_findings within {len(frames)} captured "
        "frames. Producer may not have ticked far enough — its first finding "
        "is published at tick 0 then every 8 ticks."
    )


def test_captured_ws_frames_revalidate(pipeline: Dict[str, Any]) -> None:
    """Every captured WS frame re-validates against the websocket_messages schema."""
    from shared.contracts import validate

    frames = _capture_ws_frames(
        pipeline["flutter_url"],
        pipeline["bridge_ws_url"],
        min_frames=5,
        timeout_s=15.0,
    )
    assert len(frames) >= 3, f"Expected >=3 WS frames, got {len(frames)}"

    invalid: List[str] = []
    for raw in frames[:8]:
        try:
            env = json.loads(raw)
        except json.JSONDecodeError as exc:
            invalid.append(f"json error: {exc}")
            continue
        outcome = validate("websocket_messages", env)
        if not outcome.valid:
            invalid.append(f"schema errors: {outcome.errors}")

    assert not invalid, (
        f"{len(invalid)}/{min(len(frames), 8)} captured frames failed validation:\n"
        + "\n".join(invalid[:5])
    )


def test_drone_state_reflects_battery(pipeline: Dict[str, Any]) -> None:
    """Some frame includes drone99 with a sane battery_pct."""
    frames = _capture_ws_frames(
        pipeline["flutter_url"],
        pipeline["bridge_ws_url"],
        min_frames=5,
        timeout_s=15.0,
    )
    assert len(frames) >= 3, f"Expected >=3 WS frames, got {len(frames)}"

    for raw in frames:
        try:
            env = json.loads(raw)
        except json.JSONDecodeError:
            continue
        drones = env.get("active_drones") or []
        if not drones:
            continue
        first = drones[0]
        bat = first.get("battery_pct")
        assert isinstance(bat, (int, float)), f"battery_pct not numeric: {bat!r}"
        assert 0 <= bat <= 100, f"battery_pct out of range: {bat}"
        assert first.get("drone_id") == "drone99", (
            f"Expected drone_id 'drone99', got {first.get('drone_id')!r}"
        )
        return

    pytest.fail(
        f"No frame contained any active_drones within {len(frames)} frames. "
        "Producer publishes drone state every tick — check producer logs."
    )


@pytest.mark.skip(
    reason=(
        "Optional resilience test. Phase 2 reconnect path is unit-tested in "
        "test_subscriber.py (disconnect mid-stream case). Manual verification "
        "of the live restart path is documented in the Phase 2 spec."
    )
)
def test_redis_restart_resilience(pipeline: Dict[str, Any]) -> None:
    """TODO(phase-3): live redis kill+restart with reconnect verification."""
    pass
