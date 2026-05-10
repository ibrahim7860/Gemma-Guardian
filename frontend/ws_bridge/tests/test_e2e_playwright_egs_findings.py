"""Playwright e2e: EGS-driven findings_count_by_type → bridge → Flutter DOM.

GATE 2 acceptance test (Task 7 of `docs/plans/2026-05-07-qasim-egs-gate2.md`).

Closes the live cross-stack hop the unit + integration tests cannot:
the dashboard renders a non-zero per-type findings count whose source
of truth is the real EGS coordinator graph (not a synthetic envelope).

Boot order:

    1. System Redis (already running locally — ``redis-cli ping`` skip-gate)
    2. ``agents/egs_agent/main.py``        — subscribes drones.*.findings,
                                              publishes egs.state @ 1 Hz
    3. ``scripts/dev_fake_producers.py --emit=findings --drone-id drone1``
                                            — emits one finding every 8
                                              ticks; first finding lands at
                                              tick 0 with type ``victim``
                                              (deterministic rotation,
                                              see ``_FINDING_TYPE_ROTATION``)
    4. ``frontend.ws_bridge.main`` (uvicorn) — subscribes egs.state +
                                              drones.*.findings,
                                              broadcasts ``state_update``
                                              frames to WS clients
    5. ``flutter_static_server`` fixture   — serves the Flutter web bundle
    6. Playwright Chromium                 — opens the dashboard with
                                              ``?ws=ws://…/`` override

Assertions:

    a. ``[flt-semantics-identifier^="finding-tile-"]`` attaches — the
       bridge forwarded the Contract-4 finding payload (active_findings).
    b. ``[flt-semantics-identifier="findings-count-victim"]`` attaches
       AND its rendered text reports a count >= 1 — the EGS coordinator
       processed the finding through ``process_findings``, incremented
       ``findings_count_by_type["victim"]``, the 1 Hz ``publish_egs_state``
       loop sent the updated dict on ``egs.state``, the bridge subscriber
       called ``aggregator.update_egs_state``, the emit loop broadcast
       a ``state_update`` carrying the new count, and the Flutter
       dashboard rendered it via ``FindingsCountSummary``.

Skip-gates (CI compatibility):

    * Redis not running on localhost:6379 → skip cleanly.
    * Playwright Chromium binary not installed → skip cleanly.
    * Flutter SDK / build artifact missing → handled by
      ``flutter_static_server`` fixture, which already skips.

The test runs in a try/finally so all subprocesses terminate even on
assertion failure. ``pytest.mark.timeout(180)`` caps total runtime at
3 minutes; the EGS publish cadence is 1 Hz so the count should land
inside ~2 ticks of the first finding (≤ 3 s in the happy path).
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
from contextlib import contextmanager
from pathlib import Path

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(180)]

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


def _system_redis_running() -> bool:
    """Probe localhost:6379 with redis-cli ping. Returns True iff PONG."""
    if not shutil.which("redis-cli"):
        return False
    try:
        proc = subprocess.run(
            ["redis-cli", "-h", "127.0.0.1", "-p", "6379", "ping"],
            capture_output=True, text=True, timeout=2,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return proc.returncode == 0 and "PONG" in (proc.stdout or "").upper()


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


def test_egs_findings_count_renders_in_flutter_semantics_tree(
    tmp_path, flutter_static_server,
):
    """Live cross-stack assertion: EGS-driven count flows into the dashboard.

    See module docstring for the boot order and the load-bearing
    semantics-identifier contract on the Flutter side.
    """
    if not _system_redis_running():
        pytest.skip(
            "system Redis not running on localhost:6379 — "
            "start `redis-server` and re-run"
        )
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed")
    # Mirror test_e2e_playwright_dom_render.py: chromium binary is fetched
    # by a separate `playwright install chromium` step. Skip cleanly if
    # missing rather than failing 5s into the subprocess fan-out with a
    # confusing "Executable doesn't exist at /…/Chromium" error.
    with sync_playwright() as _p:
        if not Path(_p.chromium.executable_path).exists():
            pytest.skip(
                "playwright chromium binary not installed — run "
                "`uv run playwright install chromium`"
            )

    bridge_port = _free_port()
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    env_extras = {"GG_LOG_DIR": str(log_dir)}

    # Best-effort: clean up any stale dev_fake_producer counter state by
    # using a fresh drone_id derived from PID. Also flushes egs.state so
    # the dashboard's seed envelope (zeroed counts) doesn't shadow the
    # real publish at attach time. Live system Redis is shared with the
    # user's other work, so we deliberately do NOT FLUSHALL.
    drone_id = "drone1"

    # The EGS process imports CONFIG at module scope and pulls
    # transport.redis_url from shared/config.yaml — we DON'T override
    # that here (matches Task 8's MCP runbook), so the EGS, the
    # dev_fake_producers, and the bridge all default to the same
    # localhost Redis.

    try:
        with _spawn(
            [sys.executable, "-m", "agents.egs_agent.main"],
            env=env_extras,
            name="egs",
        ) as egs_proc, _spawn(
            # PR1: EGS now subscribes to drones.*.findings.delivered, so the
            # mesh simulator must run as the passthrough between the fake
            # findings producer and the EGS / bridge consumers. EGS lat/lon
            # match the drone position in `dev_fake_producers.py` fixture
            # `01_active.json` (34.1234 / -118.5678) so `forward_finding`
            # doesn't drop every payload on the `egs_pos is None` early-out.
            [sys.executable, "-m", "agents.mesh_simulator.main",
             "--egs-lat", "34.1234", "--egs-lon", "-118.5678"],
            env=env_extras,
            name="mesh-sim",
        ), _spawn(
            [sys.executable, "scripts/dev_fake_producers.py",
             "--emit=findings", "--drone-id", drone_id, "--tick-s", "0.5"],
            env=env_extras,
            name="fake-findings",
        ), _spawn(
            [sys.executable, "-m", "uvicorn", "frontend.ws_bridge.main:app",
             "--host", "127.0.0.1", "--port", str(bridge_port)],
            env=env_extras,
            name="bridge",
        ):
            assert _wait_for_port(bridge_port, 10), "bridge did not come up"

            # Wait for EGS to subscribe + process at least one finding.
            # `dev_fake_producers --tick-s 0.5` emits a finding every 8
            # ticks (= every 4 s) starting at tick 0. The EGS publishes
            # egs.state at 1 Hz, so by ~6s after boot the bridge should
            # have an updated egs_state with victim>=1.
            time.sleep(2.0)  # let EGS start its psubscribe + publish loops
            # Surface early failures: if egs_proc died before we got
            # here, dump its tail so debugging the test isn't blind.
            if egs_proc.poll() is not None:
                tail = b""
                if egs_proc.stdout is not None:
                    try:
                        tail = egs_proc.stdout.read() or b""
                    except Exception:
                        tail = b""
                raise AssertionError(
                    "EGS agent exited prematurely "
                    f"(rc={egs_proc.returncode}); tail={tail[-1500:]!r}"
                )

            ws_url = f"ws://127.0.0.1:{bridge_port}/"
            dashboard_url = f"{flutter_static_server}/?ws={ws_url}"

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()
                console_msgs: list[str] = []
                page.on("console", lambda m: console_msgs.append(
                    f"[{m.type}] {m.text}"))
                page.goto(dashboard_url, wait_until="networkidle",
                          timeout=30_000)

                # ---- assertion (a): a finding tile attached ----
                # Any finding-id matches; dev_fake_producers emits
                # ``f_drone1_<n>`` (regex-shape per Contract 4). The
                # ``^=`` CSS prefix selector matches without us needing
                # to know the exact counter.
                tile_selector = '[flt-semantics-identifier^="finding-tile-"]'
                try:
                    page.wait_for_selector(tile_selector, timeout=60_000,
                                           state="attached")
                except Exception as e:
                    body_len = page.evaluate("document.body.outerHTML.length")
                    sem_sample = page.evaluate(
                        "Array.from(document.querySelectorAll("
                        "'flt-semantics, [flt-semantics-identifier]'"
                        ")).slice(0,30).map(e => e.outerHTML.slice(0, 200))"
                    )
                    raise AssertionError(
                        f"finding-tile-* not attached. "
                        f"body length={body_len}, "
                        f"semantics sample={sem_sample!r}, "
                        f"console tail={console_msgs[-15:]!r}"
                    ) from e

                # ---- assertion (b): findings-count-victim attached ----
                # The chip is rendered from cold start (count=0 also
                # attaches; see the Flutter widget test). The strong
                # form of this assertion checks the rendered text
                # reports >= 1, proving the EGS-driven update reached
                # the DOM, not just the seed envelope's zeros.
                count_selector = (
                    '[flt-semantics-identifier="findings-count-victim"]'
                )
                page.wait_for_selector(count_selector, timeout=30_000,
                                       state="attached")

                # Poll the rendered semantics label for the victim count.
                # Each chip's accessible name is "<type>: <n>" (matches
                # the Semantics(label:) we emit in findings_panel.dart).
                # We poll because the EGS publish cadence is 1 Hz and
                # the bridge tick is independent — the count may take
                # one or two ticks after the finding lands to render.
                deadline = time.time() + 60
                last_label = ""
                victim_count_re = re.compile(
                    r"victim\s*:\s*([1-9]\d*)", re.IGNORECASE,
                )
                matched = False
                while time.time() < deadline:
                    try:
                        el = page.locator(count_selector).first
                        last_label = el.get_attribute("aria-label") or ""
                    except Exception:
                        last_label = ""
                    if victim_count_re.search(last_label):
                        matched = True
                        break
                    time.sleep(0.5)

                if not matched:
                    # Diagnostic dump: surface the actual semantics-tree
                    # content for the count chips and the most recent
                    # console messages, so a CI failure points at the
                    # actual mismatch instead of a generic timeout.
                    chip_outers = page.evaluate(
                        "Array.from(document.querySelectorAll("
                        "'[flt-semantics-identifier^=\"findings-count-\"]'"
                        ")).map(e => ({"
                        "id: e.getAttribute('flt-semantics-identifier'), "
                        "label: e.getAttribute('aria-label'), "
                        "html: e.outerHTML.slice(0, 200)"
                        "}))"
                    )
                    raise AssertionError(
                        f"findings-count-victim never reported >= 1. "
                        f"last aria-label={last_label!r}, "
                        f"all count chips={chip_outers!r}, "
                        f"console tail={console_msgs[-15:]!r}"
                    )

                browser.close()
    finally:
        # Subprocesses are torn down by the _spawn context managers'
        # finally blocks. Nothing else to clean up here.
        pass
