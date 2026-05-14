"""E2E: clicking APPROVE/DISMISS drives a finding through bridge → real EGS
coordinator → state_update with ``operator_status`` set, within 3 seconds.

This is the live cross-stack acceptance test for the Day-11
finding-approval round trip (Task 6 of
``docs/superpowers/plans/2026-05-11-finding-approval-egs-consumer.md``).
The unit and integration tests cover the bridge stamp (Task 4) and the
Flutter dismiss promotion (Task 5) in isolation; this test closes the
final hop that none of those can: a real Chromium click on a real
``APPROVE`` / ``DISMISS`` button propagates through the bridge to the
real ``agents.egs_agent`` coordinator and the resulting upstream
``operator_status`` change re-renders in the dashboard within the
3-second budget the demo storyboard depends on.

Pipeline under test::

    Flutter web (Playwright chromium)
        ↑ WebSocket
    frontend.ws_bridge.main:app (uvicorn, test port)
        ↑ Redis
    agents.egs_agent.main (real coordinator)
        ↑ Redis
    scripts/dev_fake_producers.py --emit=state,findings,mesh-heartbeat

The ``mesh-heartbeat`` --emit mode (added in the same commit as this
test) lets the EGS coordinator's ``_await_mesh_sim`` healthcheck pass
without paying the cost of spawning the full
``agents.mesh_simulator`` subprocess — see the script's module
docstring for the rationale. We deliberately omit ``egs`` from
``--emit`` so the real EGS coordinator is the sole publisher on
``egs.state`` (no fake-vs-real collision).

Skip-gates mirror the sibling EGS-findings e2e: missing Redis,
missing Playwright Chromium, or a missing Flutter web build all skip
cleanly rather than failing 5s into the subprocess fan-out.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List

import pytest

# Same e2e marker + generous timeout cap as the sibling EGS-driven e2e.
# Cold-start spends a few seconds spinning up redis + EGS + mesh
# heartbeat + bridge + http.server + chromium before the first
# assertion. 180s is the safety net; happy path is under 30s.
pytestmark = [pytest.mark.e2e, pytest.mark.timeout(180)]

_REPO_ROOT: Path = Path(__file__).resolve().parents[3]
_FLUTTER_WEB_DIR: Path = _REPO_ROOT / "frontend" / "flutter_dashboard" / "build" / "web"


def _install_ws_url_rewriter(page: Any, bridge_port: int) -> None:
    """Rewrite the Flutter app's hardcoded ws://localhost:9090 to our port.

    Same trick as the other Phase 4 click tests in ``test_e2e_playwright.py``:
    the Flutter dashboard reads its WS endpoint from
    ``shared/contracts/topics.yaml`` codegen (port 9090), but our fixture
    allocates a free port at runtime. We patch ``window.WebSocket`` so
    every ws://localhost:<X>/ becomes ws://localhost:<bridge_port>/.
    MUST be called BEFORE ``page.goto`` so the init script runs before
    Flutter bootstraps and opens its socket.
    """
    page.add_init_script(
        f"""
        (() => {{
            const TARGET_PORT = {bridge_port};
            const Original = window.WebSocket;
            function Patched(url, protocols) {{
                try {{
                    const u = new URL(url, window.location.href);
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


def _free_port() -> int:
    """Bind to port 0, read back the OS-assigned port, release it."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _resolve_redis_server() -> str:
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
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            out = subprocess.run(
                [redis_cli, "-p", str(port), "ping"],
                capture_output=True, text=True, timeout=1.0,
            )
            if out.returncode == 0 and "PONG" in out.stdout.upper():
                return
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        time.sleep(0.1)
    raise RuntimeError(
        f"redis-server on port {port} did not become ready in {timeout_s}s."
    )


def _wait_for_port(port: int, deadline_s: float) -> bool:
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


@contextmanager
def _spawn(
    cmd: List[str],
    env: Dict[str, str] | None = None,
    name: str = "child",
    log_path: Path | None = None,
) -> Iterator[subprocess.Popen]:
    """Spawn a subprocess and aggressively tear it down on context exit.

    When ``log_path`` is provided, stdout+stderr are redirected to that
    file so the test body can read it back on failure (subprocess.PIPE
    is unreliable for child processes that buffer through stdio).
    """
    if log_path is not None:
        log_fh = log_path.open("wb")
        stdout_target: Any = log_fh
        stderr_target: Any = subprocess.STDOUT
    else:
        log_fh = None
        stdout_target = subprocess.PIPE
        stderr_target = subprocess.STDOUT
    proc = subprocess.Popen(
        cmd, cwd=str(_REPO_ROOT),
        env={**os.environ, **(env or {})},
        stdout=stdout_target, stderr=stderr_target,
    )
    try:
        yield proc
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
        if log_fh is not None:
            try:
                log_fh.close()
            except Exception:
                pass


@pytest.fixture
def green_check_pipeline(tmp_path) -> Iterator[Dict[str, Any]]:
    """Spin up redis + mesh-heartbeat + EGS + bridge + http.server.

    Function-scoped (not module-scoped) so the parametrized approve and
    dismiss cases each get a clean Redis and a fresh stream of findings
    — the bridge's snapshot stamp persists across reconnects within a
    single process lifetime, and we want the two parametrized cases to
    be independent.
    """
    if not _FLUTTER_WEB_DIR.is_dir() or not (_FLUTTER_WEB_DIR / "index.html").exists():
        pytest.skip(
            f"Flutter web build missing at {_FLUTTER_WEB_DIR}. Run "
            "`flutter build web` in frontend/flutter_dashboard first."
        )
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        pytest.skip("playwright not installed")
    with sync_playwright() as _p:
        if not Path(_p.chromium.executable_path).exists():
            pytest.skip(
                "playwright chromium binary not installed — run "
                "`uv run playwright install chromium`"
            )

    redis_server = _resolve_redis_server()
    redis_cli = _resolve_redis_cli()

    redis_port = _free_port()
    bridge_port = _free_port()
    flutter_port = _free_port()
    redis_url = f"redis://127.0.0.1:{redis_port}"

    redis_proc: subprocess.Popen | None = None
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    # Shared env for the python children. PYTHONPATH ensures
    # ``frontend.ws_bridge.main`` and ``agents.egs_agent.main`` resolve
    # regardless of cwd. REDIS_URL is what shared.contracts.CONFIG and
    # the bridge config both read.
    base_env = {
        "REDIS_URL": redis_url,
        "BRIDGE_TICK_S": "0.25",
        "BRIDGE_RECONNECT_MAX_S": "2",
        "GG_SCENARIO_ID": "disaster_zone_v1",
        "GG_LOG_DIR": str(log_dir),
        "PYTHONPATH": (
            f"{_REPO_ROOT}{os.pathsep}{os.environ.get('PYTHONPATH', '')}"
            if os.environ.get("PYTHONPATH")
            else str(_REPO_ROOT)
        ),
    }

    try:
        # 1. Redis on an isolated port with no persistence.
        redis_proc = subprocess.Popen(
            [redis_server, "--port", str(redis_port),
             "--daemonize", "no", "--save", "", "--appendonly", "no"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        _wait_redis_ready(redis_cli, redis_port, timeout_s=5.0)

        # 2-5. The remaining children stack as nested context managers so
        # teardown is automatic even on assertion failure inside the test
        # body. Order matters: mesh-heartbeat must be publishing BEFORE
        # the EGS coordinator runs _await_mesh_sim, otherwise EGS bails
        # with a RuntimeError before consuming any findings.
        producer_cmd = [
            sys.executable, "scripts/dev_fake_producers.py",
            "--redis-url", redis_url,
            "--drone-id", "drone1",
            "--tick-s", "0.5",
            # NOTE: deliberately exclude `egs` from --emit so the real
            # EGS coordinator owns egs.state without a fake-vs-real
            # collision. state + findings + mesh-heartbeat is enough
            # to feed the dashboard and unblock _await_mesh_sim.
            "--emit=state,findings,mesh-heartbeat",
        ]
        egs_cmd = [sys.executable, "-m", "agents.egs_agent.main"]
        bridge_cmd = [
            sys.executable, "-m", "uvicorn",
            "frontend.ws_bridge.main:app",
            "--host", "127.0.0.1", "--port", str(bridge_port),
            "--log-level", "warning",
        ]
        http_cmd = [
            sys.executable, "-m", "http.server", str(flutter_port),
            "--directory", str(_FLUTTER_WEB_DIR),
            "--bind", "127.0.0.1",
        ]

        egs_log = log_dir / "egs.log"
        bridge_log = log_dir / "bridge.log"
        producer_log = log_dir / "producer.log"
        with _spawn(producer_cmd, env=base_env, name="fake-producer",
                    log_path=producer_log), \
             _spawn(egs_cmd, env=base_env, name="egs-coordinator",
                    log_path=egs_log) as egs_proc, \
             _spawn(bridge_cmd, env=base_env, name="ws-bridge",
                    log_path=bridge_log), \
             _spawn(http_cmd, env=base_env, name="flutter-static"):

            assert _wait_for_port(bridge_port, 15), "bridge did not come up"
            assert _wait_for_port(flutter_port, 10), "flutter static did not come up"

            # Note: a previous draft slept 2s here to surface a crashed
            # EGS early. Dropped — the subsequent
            # ``btn.wait_for(timeout=30_000)`` already catches stalls
            # with a clear error, and the fixed sleep was fragile under
            # load (slow CI runners would still race the readiness).

            yield {
                "bridge_ws_url": f"ws://127.0.0.1:{bridge_port}/",
                "flutter_url": f"http://127.0.0.1:{flutter_port}/",
                "bridge_port": bridge_port,
                "redis_url": redis_url,
                "egs_log": egs_log,
                "bridge_log": bridge_log,
            }
    finally:
        if redis_proc is not None and redis_proc.poll() is None:
            redis_proc.terminate()
            try:
                redis_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                redis_proc.kill()


@pytest.mark.parametrize(
    "action,button_label,expected_status",
    [
        ("approve", "APPROVE", "approved"),
        ("dismiss", "DISMISS", "dismissed"),
    ],
)
def test_finding_action_round_trip_within_3s(
    green_check_pipeline: Dict[str, Any],
    action: str,
    button_label: str,
    expected_status: str,
) -> None:
    """Clicking APPROVE or DISMISS yields a state_update with the
    matching upstream ``operator_status`` within 3 seconds of the click.

    The 3-second budget is the demo storyboard's "judges click and the
    tile turns green within a heartbeat" gate. The pipeline runs at
    BRIDGE_TICK_S=0.25 and the EGS publish loop at 1 Hz, so a healthy
    system clears it with plenty of headroom; a sustained miss usually
    indicates the bridge → Redis → EGS → Redis → bridge → WS chain
    has a stall somewhere.
    """
    from playwright.sync_api import sync_playwright

    # Frames collected from the dashboard's WebSocket. We only retain
    # state_update envelopes whose active_findings include the
    # operator_status we expect — every other type (echo,
    # finding_approval_ack, etc.) is irrelevant to this assertion.
    matched_frames: List[Dict[str, Any]] = []
    # Diagnostic buffer: every state_update we observed, so a failure
    # surfaces the actual operator_status values that DID arrive
    # instead of a bare empty list.
    all_state_updates: List[Dict[str, Any]] = []
    # Diagnostic: every frame the Flutter app SENT to the bridge.
    # If the click fires correctly we expect a finding_approval frame
    # to appear here within a few hundred ms of the click.
    sent_frames: List[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            # MUST install the WS URL rewriter before page.goto so the
            # Flutter app's auto-opened socket targets our test bridge
            # port (the bundle's hardcoded 9090 isn't listening).
            _install_ws_url_rewriter(page, green_check_pipeline["bridge_port"])

            def on_websocket(ws: Any) -> None:
                # Filter on bridge port so we ignore any other socket the
                # browser may open during init.
                if str(green_check_pipeline["bridge_port"]) not in ws.url:
                    return

                def on_frame_received(payload: Any) -> None:
                    raw = (
                        payload if isinstance(payload, str)
                        else payload.decode("utf-8", "replace")
                    )
                    try:
                        env = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        return
                    if not isinstance(env, dict) or env.get("type") != "state_update":
                        return
                    all_state_updates.append({
                        "n_findings": len(env.get("active_findings") or []),
                        "operator_statuses": [
                            (f.get("finding_id"), f.get("operator_status"), f.get("approved"))
                            for f in (env.get("active_findings") or [])
                            if isinstance(f, dict)
                        ],
                        "approved_findings": (env.get("egs_state") or {}).get("approved_findings"),
                    })
                    for f in env.get("active_findings", []) or []:
                        if isinstance(f, dict) and f.get("operator_status") == expected_status:
                            matched_frames.append(f)

                ws.on("framereceived", on_frame_received)
                ws.on(
                    "framesent",
                    lambda payload: sent_frames.append(
                        payload if isinstance(payload, str)
                        else payload.decode("utf-8", "replace")
                    ),
                )

            page.on("websocket", on_websocket)
            page.goto(
                green_check_pipeline["flutter_url"],
                wait_until="domcontentloaded",
                timeout=15_000,
            )

            # Wait for the producer's first finding to land in the
            # panel — the button only exists once a finding tile has
            # rendered. Producer ticks at 0.5s and publishes a finding
            # every 8 ticks; combined with EGS process_findings →
            # publish_egs_state at 1 Hz → bridge tick at 0.25s, the
            # button typically appears within ~6-10s of cold start
            # locally. GitHub Actions runners take 2-3x longer for
            # Flutter web cold-load + EGS subprocess startup + WS
            # handshake; the dismiss param flaked on `8e791bc` at the
            # 30s ceiling (PR run for same SHA was clean — pure CI
            # cold-start variance, not a regression). Bumped to 60s
            # for CI headroom; the actual 3s round-trip SLA below is
            # unchanged.
            btn = page.locator(
                f'flt-semantics[role="button"]:has-text("{button_label}")'
            ).first
            btn.wait_for(state="visible", timeout=60_000)

            # ---- the load-bearing click ----
            click_t0 = time.monotonic()
            btn.click()

            # 3-second budget for the round trip. Poll until we see a
            # state_update with the expected operator_status, or the
            # deadline elapses.
            deadline = click_t0 + 3.0
            while time.monotonic() < deadline and not matched_frames:
                page.wait_for_timeout(100)

            elapsed_ms = (time.monotonic() - click_t0) * 1000
            if not matched_frames:
                # Dump tail of EGS + bridge logs so a stall is debuggable.
                try:
                    egs_tail = green_check_pipeline["egs_log"].read_text()[-3000:]
                except Exception:
                    egs_tail = "<unreadable>"
                try:
                    bridge_tail = green_check_pipeline["bridge_log"].read_text()[-2000:]
                except Exception:
                    bridge_tail = "<unreadable>"
                # Validation events from the bridge subscriber's drop log
                # (Contract 11 JSONL). If a schema validation failed
                # silently here, that's the smoking gun.
                try:
                    val_log = green_check_pipeline["egs_log"].parent / "validation_events.jsonl"
                    val_tail = val_log.read_text()[-2000:] if val_log.exists() else "<no validation_events.jsonl>"
                except Exception:
                    val_tail = "<unreadable>"
                pytest.fail(
                    f"no state_update with operator_status={expected_status!r} "
                    f"within 3s after clicking {button_label} (waited "
                    f"{elapsed_ms:.0f}ms). Indicates a stall on the "
                    f"bridge → Redis → EGS → Redis → bridge → WS chain.\n"
                    f"recent_state_updates={all_state_updates[-5:]!r}\n"
                    f"sent_frame_count={len(sent_frames)} "
                    f"sent_frames_tail={sent_frames[-5:]!r}\n"
                    f"--- EGS log tail ---\n{egs_tail}\n"
                    f"--- Bridge log tail ---\n{bridge_tail}\n"
                    f"--- validation_events.jsonl tail ---\n{val_tail}"
                )

            # Sanity-check the stamped finding belongs to a real id —
            # the aggregator's snapshot loop already enforced the verb
            # match (the operator_status filter above), so a wrong-verb
            # propagation would have failed earlier. The boolean
            # ``approved`` mirror was removed in commit f0bf8a8 because
            # Contract 4's ``additionalProperties: false`` forbade it;
            # the operator_status enum carries the signal.
            first = matched_frames[0]
            assert first.get("finding_id"), (
                f"action={action!r} expected a non-empty finding_id on the "
                f"stamped finding; got {first!r}"
            )
        finally:
            browser.close()
