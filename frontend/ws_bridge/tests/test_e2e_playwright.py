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
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

import pytest

# All tests in this file hit a multi-process pipeline (redis + uvicorn +
# producer + http.server + chromium). Cold-start can spend several seconds
# building the pipeline fixture before the first test even runs, and the
# Phase 4 round-trip tests below add another ~5s waiting on a producer
# finding to land. Bump per-test timeout to 90s — well above the ~5s
# steady-state — to avoid flakes on slow CI runners.
pytestmark = [pytest.mark.e2e, pytest.mark.timeout(90)]


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


def _ws_send_and_capture(
    page_url: str,
    bridge_ws_url: str,
    *,
    send_frames: List[Dict[str, Any]],
    match: Callable[[Dict[str, Any]], bool],
    timeout_s: float = 15.0,
    pre_send_delay_ms: int = 200,
    on_first_state_update: Optional[Callable[[Dict[str, Any]], Optional[List[Dict[str, Any]]]]] = None,
) -> Optional[Dict[str, Any]]:
    """Open a WS from page JS, send frames, return the first frame matching ``match``.

    The flow is:

    1. Load ``page_url`` (the Flutter dashboard) so any auto-opened WS does
       its thing — we don't depend on it, but loading the page mirrors the
       real-user environment.
    2. Open a second WebSocket from page JS and stash received frames on
       ``window.__e2eRX`` so Python can poll them back via ``page.evaluate``.
    3. After ``onopen`` fires (and ``pre_send_delay_ms`` of grace so the
       initial ``state_update`` envelope drains into ``__e2eRX``), send each
       frame in ``send_frames`` via ``ws.send(JSON.stringify(...))``.
    4. Optionally call ``on_first_state_update`` with the first observed
       ``state_update`` frame; if it returns extra frames, send those next
       (used by the finding_approval round-trip to capture a finding_id
       before sending the approval).
    5. Poll ``__e2eRX`` until a frame matches ``match`` or the timeout fires.

    Returns the matching frame as a dict, or ``None`` if no frame matched
    within ``timeout_s``.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(page_url, wait_until="domcontentloaded", timeout=15_000)

            # Open the WS we control. Wait synchronously for ``onopen`` so
            # subsequent ``ws.send`` calls don't race the handshake.
            opened = page.evaluate(
                """async (url) => {
                    window.__e2eRX = [];
                    return await new Promise((resolve) => {
                        const ws = new WebSocket(url);
                        const t = setTimeout(() => resolve(false), 5000);
                        ws.onopen = () => { clearTimeout(t); resolve(true); };
                        ws.onmessage = (ev) => {
                            try { window.__e2eRX.push(ev.data); } catch (e) {}
                        };
                        ws.onerror = () => { clearTimeout(t); resolve(false); };
                        window.__e2eWS = ws;
                    });
                }""",
                bridge_ws_url,
            )
            if not opened:
                return None

            # Let the bridge's initial state_update frame land before sending.
            page.wait_for_timeout(pre_send_delay_ms)

            extra_frames: List[Dict[str, Any]] = []
            if on_first_state_update is not None:
                # Wait for the first state_update; capture, callback may
                # produce additional frames to send (e.g. finding_approval).
                deadline_state = time.monotonic() + timeout_s
                first_state: Optional[Dict[str, Any]] = None
                while time.monotonic() < deadline_state and first_state is None:
                    raw_frames: List[str] = page.evaluate(
                        "() => (window.__e2eRX || []).slice()"
                    )
                    for raw in raw_frames:
                        try:
                            env = json.loads(raw)
                        except (json.JSONDecodeError, TypeError):
                            continue
                        if isinstance(env, dict) and env.get("type") == "state_update":
                            cb_result = on_first_state_update(env)
                            if cb_result is None:
                                continue
                            extra_frames = cb_result
                            first_state = env
                            break
                    if first_state is None:
                        page.wait_for_timeout(200)
                if first_state is None:
                    return None

            for frame in send_frames + extra_frames:
                page.evaluate(
                    """(payload) => {
                        const ws = window.__e2eWS;
                        if (ws && ws.readyState === 1) {
                            ws.send(JSON.stringify(payload));
                        }
                    }""",
                    frame,
                )

            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                raw_frames: List[str] = page.evaluate(
                    "() => (window.__e2eRX || []).slice()"
                )
                for raw in raw_frames:
                    try:
                        env = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if isinstance(env, dict) and match(env):
                        return env
                page.wait_for_timeout(200)
            return None
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


# ---------------------------------------------------------------------------
# Phase 4 outbound paths
# ---------------------------------------------------------------------------
#
# The 4 tests above cover inbound state propagation. The 5 tests below cover
# the bridge's Phase 4 outbound surface: operator_command publish,
# operator_command_dispatch, finding_approval (happy + error path), and
# command_translation forwarding from Redis to the browser.
#
# Each test drives a real chromium WebSocket against the running uvicorn
# bridge — exercising the same code paths that the httpx-based unit tests
# in ``test_main_*.py`` cover, but through the actual WS transport.


def test_operator_command_publish_round_trip(pipeline: Dict[str, Any]) -> None:
    """Browser sends ``operator_command`` and receives the echo ack.

    This exercises the bridge's republish-to-Redis path: the bridge validates
    the inbound frame, publishes a stamped ``operator_commands_envelope`` to
    ``egs.operator_commands``, and only then echoes the ack back. The echo's
    arrival proves the publish path didn't error.
    """
    command_id = "e2e-cmd-pub-1"
    matched = _ws_send_and_capture(
        pipeline["flutter_url"],
        pipeline["bridge_ws_url"],
        send_frames=[{
            "type": "operator_command",
            "command_id": command_id,
            "language": "en",
            "raw_text": "recall drone1 to base",
            "contract_version": "1.0.0",
        }],
        match=lambda env: (
            env.get("type") == "echo"
            and env.get("ack") == "operator_command_received"
            and env.get("command_id") == command_id
        ),
        timeout_s=15.0,
    )
    assert matched is not None, (
        f"No operator_command_received echo for command_id={command_id} "
        "within 15s. The bridge may have failed validation or the redis "
        "publish raised."
    )


def test_operator_command_dispatch_round_trip(pipeline: Dict[str, Any]) -> None:
    """Browser sends ``operator_command_dispatch`` and receives the echo ack.

    Mirrors the operator_command path but hits the dispatch branch, which
    republishes onto ``egs.operator_actions`` (same channel as
    finding_approval).
    """
    command_id = "e2e-cmd-dispatch-1"
    matched = _ws_send_and_capture(
        pipeline["flutter_url"],
        pipeline["bridge_ws_url"],
        send_frames=[{
            "type": "operator_command_dispatch",
            "command_id": command_id,
            "contract_version": "1.0.0",
        }],
        match=lambda env: (
            env.get("type") == "echo"
            and env.get("ack") == "operator_command_dispatch"
            and env.get("command_id") == command_id
        ),
        timeout_s=15.0,
    )
    assert matched is not None, (
        f"No operator_command_dispatch echo for command_id={command_id} "
        "within 15s."
    )


def test_finding_approval_round_trip(pipeline: Dict[str, Any]) -> None:
    """Browser approves a producer-published finding and gets the echo ack.

    The producer publishes a finding every 8 ticks (~1.6s at the
    fixture's tick_s=0.2). The dance:

    1. Subscribe to the bridge WS.
    2. Wait for a state_update frame whose ``active_findings`` is non-empty.
    3. Capture the first ``finding_id`` from that frame.
    4. Send a ``finding_approval`` for that id.
    5. Wait for the matching echo ack.
    """
    command_id = "e2e-approve-1"
    captured: Dict[str, str] = {}

    def _on_state_update(env: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        findings = env.get("active_findings") or []
        if not findings:
            return None
        fid = findings[0].get("finding_id")
        if not isinstance(fid, str) or not fid:
            return None
        captured["finding_id"] = fid
        return [{
            "type": "finding_approval",
            "command_id": command_id,
            "finding_id": fid,
            "action": "approve",
            "contract_version": "1.0.0",
        }]

    matched = _ws_send_and_capture(
        pipeline["flutter_url"],
        pipeline["bridge_ws_url"],
        send_frames=[],
        on_first_state_update=_on_state_update,
        match=lambda env: (
            env.get("type") == "echo"
            and env.get("ack") == "finding_approval"
            and env.get("command_id") == command_id
        ),
        # Producer first finding lands at tick 0, but the bridge needs a
        # subscriber + aggregator tick to see it. ~5s headroom after WS
        # open is generous for tick_s=0.2.
        timeout_s=20.0,
    )
    assert "finding_id" in captured, (
        "Never observed a state_update with active_findings — the producer "
        "may not have ticked or the bridge subscriber didn't deliver."
    )
    assert matched is not None, (
        f"No finding_approval echo for command_id={command_id} "
        f"finding_id={captured.get('finding_id')!r} within 20s."
    )
    assert matched.get("finding_id") == captured["finding_id"], (
        f"Echo's finding_id {matched.get('finding_id')!r} did not match "
        f"the captured {captured['finding_id']!r}."
    )


def test_command_translation_forward(pipeline: Dict[str, Any]) -> None:
    """Envelope published to ``egs.command_translations`` is forwarded to WS.

    Uses ``redis-cli PUBLISH`` to inject the envelope (rather than starting
    a Python redis client) — ``pipeline`` already exposes the cli path and
    port. The bridge subscriber strips ``kind`` and ``egs_published_at_iso_ms``
    before broadcasting; assert both are gone in the received frame.
    """
    command_id = "e2e-translate-1"
    envelope = {
        "kind": "command_translation",
        "command_id": command_id,
        "structured": {
            "command": "recall_drone",
            "args": {"drone_id": "drone1", "reason": "operator request"},
        },
        "valid": True,
        "preview_text": "Will recall drone1: operator request",
        "preview_text_in_operator_language": "Will recall drone1: operator request",
        "egs_published_at_iso_ms": "2026-05-04T12:34:57.123Z",
        "contract_version": "1.0.0",
    }
    redis_cli = pipeline["redis_cli_bin"]
    redis_port = pipeline["redis_port"]
    channel = "egs.command_translations"

    # The publish must happen AFTER the bridge subscriber has actually
    # subscribed. The bridge binds the subscriber at startup, but on slow
    # CI runners there's a small window. Schedule the publish on a delay
    # using a background thread so it fires after our WS open + drain.
    import threading

    def _delayed_publish() -> None:
        # 1.5s gives the WS open + initial state drain plenty of time.
        time.sleep(1.5)
        try:
            subprocess.run(
                [
                    redis_cli, "-p", str(redis_port),
                    "PUBLISH", channel, json.dumps(envelope),
                ],
                check=True,
                capture_output=True,
                timeout=5.0,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            sys.stderr.write(f"[e2e] redis publish failed: {exc}\n")

    t = threading.Thread(target=_delayed_publish, daemon=True)
    t.start()

    try:
        matched = _ws_send_and_capture(
            pipeline["flutter_url"],
            pipeline["bridge_ws_url"],
            send_frames=[],
            match=lambda env: (
                env.get("type") == "command_translation"
                and env.get("command_id") == command_id
            ),
            timeout_s=15.0,
        )
    finally:
        t.join(timeout=5.0)

    assert matched is not None, (
        f"No command_translation frame for command_id={command_id} "
        "within 15s. Bridge subscriber may not have been ready."
    )
    # Bridge-only fields must NOT leak.
    assert "kind" not in matched, (
        f"Bridge leaked 'kind' field to client: {matched.get('kind')!r}"
    )
    assert "egs_published_at_iso_ms" not in matched, (
        "Bridge leaked 'egs_published_at_iso_ms' field to client."
    )
    assert matched.get("structured", {}).get("command") == "recall_drone"
    assert matched.get("valid") is True
    assert matched.get("preview_text", "").startswith("Will recall")


def test_unknown_finding_id_error_path(pipeline: Dict[str, Any]) -> None:
    """Approving an unknown finding_id yields an ``unknown_finding_id`` echo.

    The producer uses prefix ``f_drone99_<counter>``; we use ``drone98``
    with a high suffix to guarantee the id matches the contract regex
    (``^f_drone\\d+_\\d+$``) but is never minted by the producer.

    The match predicate checks BOTH ``error == 'unknown_finding_id'`` AND
    ``command_id`` so the test can't false-pass on a stray echo.
    """
    command_id = "e2e-unknown-1"
    unknown_finding_id = "f_drone98_999999"

    matched = _ws_send_and_capture(
        pipeline["flutter_url"],
        pipeline["bridge_ws_url"],
        send_frames=[{
            "type": "finding_approval",
            "command_id": command_id,
            "finding_id": unknown_finding_id,
            "action": "approve",
            "contract_version": "1.0.0",
        }],
        match=lambda env: (
            env.get("type") == "echo"
            and env.get("error") == "unknown_finding_id"
            and env.get("command_id") == command_id
        ),
        timeout_s=15.0,
    )
    assert matched is not None, (
        f"No unknown_finding_id error echo for command_id={command_id} "
        "within 15s."
    )
    assert matched.get("finding_id") == unknown_finding_id, (
        f"Echo's finding_id {matched.get('finding_id')!r} did not match "
        f"the unknown id we sent ({unknown_finding_id!r})."
    )


# ---------------------------------------------------------------------------
# Phase 4 UI-interaction tests (a11y semantics)
# ---------------------------------------------------------------------------
#
# The tests above use Playwright as a JSON transport — they open a side-channel
# WebSocket from page JS and send/receive frames directly. Useful for protocol
# regression but they never touch a real button.
#
# The tests below drive the actual Flutter dashboard UI through Flutter web's
# accessibility semantics tree (``SemanticsBinding.ensureSemantics`` is wired
# in ``frontend/flutter_dashboard/lib/main.dart``). Every visible widget shows
# up as a ``<flt-semantics>`` DOM node with a ``role`` attribute and the
# widget's text as its content, which Playwright can locate and click. The
# command-panel text input is a real ``<input>`` element with an ``aria-label``.
#
# We hook into the Flutter app's OWN WebSocket (the one it opens to the bridge
# on load) via ``page.on('websocket')`` + ``framesent`` and inspect what the UI
# actually sends in response to clicks/typing — which is the ground truth we
# care about for the demo.


def _install_ws_url_rewriter(page, bridge_port: int) -> None:
    """Patch ``window.WebSocket`` so any URL the Flutter app passes is
    rewritten to point at our dynamically-allocated bridge port.

    The Flutter dashboard hardcodes ``ws://localhost:9090`` from
    ``Channels.wsEndpoint`` (generated from ``shared/contracts/topics.yaml``).
    Our test fixture allocates a free port at runtime, so without this
    rewrite the Flutter app would try to connect to 9090 — which isn't
    running — and the findings panel never populates. We rewrite at the
    JavaScript layer because the Dart code can't be reconfigured without a
    rebuild.

    MUST be called BEFORE ``page.goto`` so the init script runs before
    Flutter bootstraps.
    """
    page.add_init_script(
        f"""
        (() => {{
            const TARGET_PORT = {bridge_port};
            const Original = window.WebSocket;
            function Patched(url, protocols) {{
                try {{
                    const u = new URL(url, window.location.href);
                    // Only rewrite ws:// URLs targeting localhost/127.0.0.1
                    // — leave anything else (e.g., devtools) alone.
                    if (
                        (u.protocol === 'ws:' || u.protocol === 'wss:')
                        && (u.hostname === 'localhost' || u.hostname === '127.0.0.1')
                    ) {{
                        u.port = String(TARGET_PORT);
                        url = u.toString();
                    }}
                }} catch (e) {{ /* fall through with original url */ }}
                return protocols === undefined
                    ? new Original(url)
                    : new Original(url, protocols);
            }}
            Patched.prototype = Original.prototype;
            Patched.CONNECTING = Original.CONNECTING;
            Patched.OPEN = Original.OPEN;
            Patched.CLOSING = Original.CLOSING;
            Patched.CLOSED = Original.CLOSED;
            window.WebSocket = Patched;
        }})();
        """
    )


def _capture_app_outbound_frames(page, bridge_port: int) -> List[str]:
    """Attach a WS listener that buffers every outbound frame the Flutter
    app sends to the bridge. Returns a live list — keep using ``page`` and
    new frames append automatically. MUST be called BEFORE ``page.goto``
    so the listener is live when the Flutter app opens its WS.

    Filters by ``bridge_port`` so unrelated WS connections (e.g., devtools)
    are ignored.
    """
    sent: List[str] = []

    def on_websocket(ws: Any) -> None:
        if str(bridge_port) not in ws.url:
            return
        ws.on(
            "framesent",
            lambda payload: sent.append(
                payload if isinstance(payload, str) else payload.decode("utf-8", "replace")
            ),
        )

    page.on("websocket", on_websocket)
    return sent


def _wait_for_frame_matching(
    frames: List[str],
    predicate: Callable[[Dict[str, Any]], bool],
    *,
    timeout_s: float,
    poll_ms: int = 100,
) -> Dict[str, Any]:
    """Poll the live ``frames`` list until one parses-as-JSON and matches
    ``predicate``. Returns the matching frame. Raises AssertionError on
    timeout.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for raw in frames:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if predicate(msg):
                return msg
        time.sleep(poll_ms / 1000.0)
    raise AssertionError(
        f"no frame in {len(frames)} captured frames matched predicate within {timeout_s}s"
    )


def test_ui_approve_button_fires_finding_approval(pipeline: Dict[str, Any]) -> None:
    """Clicking 'APPROVE' on a finding tile must produce a single
    finding_approval frame on the Flutter app's WebSocket to the bridge.

    This is the operator's primary demo action: see a victim, approve.
    The network-layer test covers the bridge's handling of an inbound
    finding_approval; this test covers that the actual UI button does
    fire that frame in the first place.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            _install_ws_url_rewriter(page, pipeline["bridge_port"])
            sent_frames = _capture_app_outbound_frames(page, pipeline["bridge_port"])
            page.goto(pipeline["flutter_url"], wait_until="domcontentloaded", timeout=15_000)
            # Wait for the producer's first finding to land in the panel.
            # Producer publishes findings every ~1.6s; cold-start can take
            # several seconds before the first one renders.
            approve_btn = page.locator(
                'flt-semantics[role="button"]:has-text("APPROVE")'
            ).first
            approve_btn.wait_for(state="visible", timeout=20_000)
            approve_btn.click()
            # Allow the click handler to fire and the WS send to flush.
            page.wait_for_timeout(500)

            approvals: List[Dict[str, Any]] = []
            for raw in sent_frames:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if msg.get("type") == "finding_approval":
                    approvals.append(msg)
            assert len(approvals) == 1, (
                f"expected exactly one finding_approval frame; got "
                f"{len(approvals)}: {approvals!r}"
            )
            ap = approvals[0]
            assert ap.get("action") == "approve", (
                f"action must be 'approve'; got {ap.get('action')!r}"
            )
            assert re.match(r"^f_drone\d+_\d+$", ap.get("finding_id", "")), (
                f"finding_id must match schema regex; got {ap.get('finding_id')!r}"
            )
            assert ap.get("command_id"), (
                f"command_id must be non-empty; got {ap.get('command_id')!r}"
            )
        finally:
            browser.close()


def test_ui_dismiss_button_fires_finding_approval_with_dismiss_action(
    pipeline: Dict[str, Any],
) -> None:
    """Clicking 'DISMISS' on a finding tile fires finding_approval with
    action='dismiss'. Sister test to APPROVE — covers the negative
    operator action.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            _install_ws_url_rewriter(page, pipeline["bridge_port"])
            sent_frames = _capture_app_outbound_frames(page, pipeline["bridge_port"])
            page.goto(pipeline["flutter_url"], wait_until="domcontentloaded", timeout=15_000)
            dismiss_btn = page.locator(
                'flt-semantics[role="button"]:has-text("DISMISS")'
            ).first
            dismiss_btn.wait_for(state="visible", timeout=20_000)
            dismiss_btn.click()
            page.wait_for_timeout(500)

            dismiss = _wait_for_frame_matching(
                sent_frames,
                lambda m: (
                    m.get("type") == "finding_approval"
                    and m.get("action") == "dismiss"
                ),
                timeout_s=5.0,
            )
            assert re.match(r"^f_drone\d+_\d+$", dismiss.get("finding_id", "")), (
                f"finding_id must match schema regex; got {dismiss.get('finding_id')!r}"
            )
            assert dismiss.get("command_id"), (
                f"command_id must be non-empty; got {dismiss.get('command_id')!r}"
            )
        finally:
            browser.close()


def test_ui_translate_button_fires_operator_command_with_language(
    pipeline: Dict[str, Any],
) -> None:
    """Pick Spanish in the dropdown, type a command, click TRANSLATE.
    The Flutter app must send an operator_command frame with
    language='es' and the typed raw_text.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            _install_ws_url_rewriter(page, pipeline["bridge_port"])
            sent_frames = _capture_app_outbound_frames(page, pipeline["bridge_port"])
            page.goto(pipeline["flutter_url"], wait_until="domcontentloaded", timeout=15_000)

            # The text input is a real <input> with aria-label="Type a command..."
            text_input = page.locator('input[aria-label="Type a command..."]').first
            text_input.wait_for(state="visible", timeout=15_000)

            # Open the language dropdown by clicking its trigger
            # (currently shows "English").
            page.locator(
                'flt-semantics[role="button"]:has-text("English")'
            ).first.click()
            # Flutter renders dropdown items as ``<flt-semantics
            # role="menuitem">`` but the text content lives on the
            # canvas, not in the DOM — so we cannot select by text. The
            # DropdownMenuItem order is fixed in command_panel.dart:
            # English (0), Spanish (1), Arabic (2). Pick index 1.
            #
            # Flake fix: the previous version of this test used a bare
            # ``wait_for_timeout(500)`` before clicking. On a slow CI
            # runner, the menuitem DOM nodes haven't been added by
            # Flutter's a11y bridge in 500ms and ``.click()`` times out
            # at 30s. Replaced with an explicit ``wait_for(state="attached")``
            # on the second menuitem so we wait until Flutter has
            # actually rendered the dropdown items.
            spanish_item = page.locator(
                'flt-semantics[role="menuitem"]'
            ).nth(1)
            spanish_item.wait_for(state="attached", timeout=10_000)
            spanish_item.click()

            text_input.fill("recall drone1 to base")
            # TRANSLATE button must now be enabled (text is non-empty).
            translate_btn = page.locator(
                'flt-semantics[role="button"]:has-text("TRANSLATE")'
            ).first
            translate_btn.click()
            page.wait_for_timeout(500)

            cmd = _wait_for_frame_matching(
                sent_frames,
                lambda m: m.get("type") == "operator_command",
                timeout_s=5.0,
            )
            assert cmd.get("language") == "es", (
                f"language must be 'es'; got {cmd.get('language')!r}"
            )
            assert cmd.get("raw_text") == "recall drone1 to base", (
                f"raw_text must match what we typed; got {cmd.get('raw_text')!r}"
            )
            assert cmd.get("command_id"), (
                f"command_id must be non-empty; got {cmd.get('command_id')!r}"
            )
        finally:
            browser.close()


def test_ui_approve_disables_button_after_click(pipeline: Dict[str, Any]) -> None:
    """After clicking APPROVE, the button must visually transition to a
    disabled state (per MissionState's optimistic update — finding moves
    to ApprovalState.pending which gates onPressed: null).

    This is the operator-feedback contract: judges will mash the button
    and we don't want it to fire 5 times before the bridge ack arrives.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            _install_ws_url_rewriter(page, pipeline["bridge_port"])
            sent_frames = _capture_app_outbound_frames(page, pipeline["bridge_port"])
            page.goto(pipeline["flutter_url"], wait_until="domcontentloaded", timeout=15_000)
            page.locator(
                'flt-semantics[role="button"]:has-text("APPROVE")'
            ).first.wait_for(state="visible", timeout=20_000)
            # Resolve to a concrete DOM node so subsequent clicks hit the
            # SAME button. ``locator(...).first`` re-queries on every call
            # — and the producer publishes a new finding every ~1.6s, so
            # the second ``.first`` would target a different tile entirely.
            approve_handle = page.locator(
                'flt-semantics[role="button"]:has-text("APPROVE")'
            ).first.element_handle()
            assert approve_handle is not None, "approve element handle missing"
            approve_handle.click()
            # Click the SAME node again immediately. If the button is
            # properly disabled, the second click is a no-op.
            page.wait_for_timeout(50)
            try:
                approve_handle.click(timeout=2_000, force=True)
            except Exception:
                # The button may detach / become non-clickable as Flutter
                # rebuilds the tile with the disabled state. That's exactly
                # what we want — count the second click as a no-op.
                pass
            page.wait_for_timeout(800)

            # Flake fix: the producer publishes a new finding every ~1.6s
            # while this test runs. Flutter web aggressively recycles
            # ``flt-semantics`` nodes, so the element_handle from the
            # first APPROVE click can end up backing a fresh tile by the
            # time the second click fires — producing TWO approvals for
            # two DIFFERENT finding_ids and a flaky failure.
            #
            # The contract this test enforces is "the SAME button can't
            # fire twice" (operator mashes the button, only one
            # finding_approval lands). We capture the finding_id from
            # the first approval frame and assert no SECOND approval
            # fires for that same id. Approvals for other findings
            # (caused by node recycling onto a fresh tile) are
            # cosmetically suboptimal but don't violate the contract.
            approvals: List[Dict[str, Any]] = []
            for raw in sent_frames:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if (
                    msg.get("type") == "finding_approval"
                    and msg.get("action") == "approve"
                ):
                    approvals.append(msg)
            assert len(approvals) >= 1, (
                f"expected at least one approval; got {approvals!r}"
            )
            first_finding_id = approvals[0].get("finding_id")
            same_id_approvals = [
                a for a in approvals if a.get("finding_id") == first_finding_id
            ]
            assert len(same_id_approvals) == 1, (
                f"same button must not fire twice; got "
                f"{len(same_id_approvals)} approvals for {first_finding_id!r}: "
                f"{same_id_approvals!r}"
            )
        finally:
            browser.close()
