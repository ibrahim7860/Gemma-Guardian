"""Playwright e2e for the Beat 4 dashboard pre-flight signals:

  1. The "EGS LINK SEVERED" banner — `[flt-semantics-identifier="egs-link-severed-banner"]`
  2. The "STANDALONE MODE ACTIVE" badge — `[flt-semantics-identifier="standalone-badge-<drone_id>"]`

Both ride on the same accessibility-tree machinery as
`test_e2e_playwright_dom_render.py`'s finding tile (Flutter 3.41 CanvasKit
+ flt-semantics shadow tree, auto-enabled by `main.dart`'s
`SemanticsBinding.instance.ensureSemantics()`).

Why a synthetic WebSocket server instead of the integrated stack?

The banner is driven by `egs.state` heartbeat staleness inside
`MissionState`. To trigger it we need to send ONE envelope with
`egs_state` populated, then stop sending — for a few seconds — while
the WS itself stays connected. The full integrated stack
(redis + sim + drone agent + bridge) actively republishes `egs.state`
every 1 s and we'd need to MITM or kill its publisher mid-run to
exercise the staleness path. A 30-line `websockets` server is a
deterministic, fast equivalent for what we're proving here:
"the Semantics identifiers we ship are reachable from a browser
when the dashboard enters the severed/standalone state."

The full integrated path is already covered by
`test_e2e_playwright_dom_render.py` — this test is the targeted
companion for Beat 4's specific UI states.
"""
from __future__ import annotations

import asyncio
import json
import socket
import threading
from pathlib import Path

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(120)]


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# Canonical state_update shape: shared/schemas/fixtures/valid/websocket_messages/01_state_update.json
# We populate active_drones with one drone in agent_status="standalone" so the
# badge renders immediately, and ship a fresh egs_state once so the banner only
# appears after the heartbeat staleness window (5 s, MissionState.egsHeartbeatStaleAfter).
SEED_ENVELOPE = {
    "type": "state_update",
    "timestamp": "2026-05-07T10:00:00.000Z",
    "contract_version": "1.0.0",
    "egs_state": {
        "mission_id": "beat4_demo",
        "mission_status": "active",
        "timestamp": "2026-05-07T10:00:00.000Z",
        "zone_polygon": [
            [34.1230, -118.5680], [34.1240, -118.5680],
            [34.1240, -118.5670], [34.1230, -118.5670],
        ],
        "survey_points": [],
        "drones_summary": {},
        "findings_count_by_type": {
            "victim": 0, "fire": 0, "smoke": 0,
            "damaged_structure": 0, "blocked_route": 0,
        },
        "recent_validation_events": [],
        "active_zone_ids": [],
    },
    "active_findings": [],
    "active_drones": [
        {
            "drone_id": "drone3",
            "agent_status": "standalone",
            "battery_pct": 62,
            "current_task": "survey",
            "findings_count": 1,
            "validation_failures_total": 0,
        },
    ],
}


def _start_synthetic_ws_server(port: int) -> threading.Thread:
    """Background thread running an asyncio loop with a `websockets` server.

    On each accept: send the seed envelope once, then hold open
    indefinitely. Exits cleanly when the test process tears down — daemon
    thread + connection handler returning when the client disconnects.
    """
    import websockets

    async def handler(ws):
        await ws.send(json.dumps(SEED_ENVELOPE))
        # Keep the connection open without sending more egs.state. Any
        # client message gets dropped on the floor; we just wait until
        # the client closes.
        try:
            async for _ in ws:
                pass
        except websockets.ConnectionClosed:
            return

    async def main():
        async with websockets.serve(handler, "127.0.0.1", port):
            await asyncio.Future()  # run forever

    def run():
        try:
            asyncio.run(main())
        except (KeyboardInterrupt, SystemExit):
            pass

    t = threading.Thread(target=run, daemon=True, name="synthetic-ws")
    t.start()
    return t


def _wait_for_ws(port: int, deadline_s: float = 5.0) -> bool:
    """Wait for the synthetic WS server's TCP listener to be ready.

    Closing the probe socket without an HTTP upgrade triggers a noisy but
    harmless `InvalidMessage: did not receive a valid HTTP request` on the
    server side; suppress it so it doesn't pollute pytest output.
    """
    import logging as _logging
    import time as _t

    _logging.getLogger("websockets.server").setLevel(_logging.CRITICAL)
    deadline = _t.time() + deadline_s
    while _t.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            _t.sleep(0.1)
    return False


def test_banner_and_badge_render_in_semantics_tree(flutter_static_server):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed")
    # Mirror test_e2e_playwright_dom_render.py: Chromium binary is fetched by
    # a separate `playwright install chromium` step, skip cleanly if missing.
    with sync_playwright() as _p:
        if not Path(_p.chromium.executable_path).exists():
            pytest.skip(
                "playwright chromium binary not installed — run "
                "`uv run playwright install chromium`"
            )

    ws_port = _free_port()
    _start_synthetic_ws_server(ws_port)
    assert _wait_for_ws(ws_port), "synthetic WS server did not come up"

    ws_url = f"ws://127.0.0.1:{ws_port}/"
    dashboard_url = f"{flutter_static_server}/?ws={ws_url}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        console_msgs: list[str] = []
        page.on("console", lambda m: console_msgs.append(f"[{m.type}] {m.text}"))
        page.goto(dashboard_url, wait_until="networkidle", timeout=30_000)

        # 1. STANDALONE badge renders immediately on the first state_update.
        badge_selector = '[flt-semantics-identifier="standalone-badge-drone3"]'
        try:
            page.wait_for_selector(badge_selector, timeout=15_000, state="attached")
        except Exception as e:
            sem_sample = page.evaluate(
                "Array.from(document.querySelectorAll("
                "'flt-semantics, [flt-semantics-identifier]'"
                ")).slice(0, 20).map(e => e.outerHTML.slice(0, 200))"
            )
            raise AssertionError(
                f"selector {badge_selector!r} not attached within 15 s. "
                f"semantics sample={sem_sample!r}, "
                f"console tail={console_msgs[-15:]!r}"
            ) from e

        # 2. EGS LINK SEVERED banner appears only after the heartbeat staleness
        # window (5 s in MissionState.egsHeartbeatStaleAfter). The Timer.periodic
        # in MissionState fires at 1 Hz, so worst case is ~6 s before the banner
        # attaches; we give 15 s to account for CI jitter.
        banner_selector = '[flt-semantics-identifier="egs-link-severed-banner"]'
        try:
            page.wait_for_selector(banner_selector, timeout=15_000, state="attached")
        except Exception as e:
            sem_sample = page.evaluate(
                "Array.from(document.querySelectorAll("
                "'flt-semantics, [flt-semantics-identifier]'"
                ")).slice(0, 20).map(e => e.outerHTML.slice(0, 200))"
            )
            raise AssertionError(
                f"selector {banner_selector!r} not attached within 15 s "
                f"after staleness window. "
                f"semantics sample={sem_sample!r}, "
                f"console tail={console_msgs[-15:]!r}"
            ) from e

        # Sanity: the accessible markup encodes the Beat 4 messaging. Flutter
        # CanvasKit doesn't always promote `Semantics(label: ...)` to a single
        # aria-label attribute (it can merge with descendant text), so check
        # the outerHTML for either the aria-label or the descendant text node.
        badge_outer = page.locator(badge_selector).first.evaluate(
            "el => el.outerHTML")
        banner_outer = page.locator(banner_selector).first.evaluate(
            "el => el.outerHTML")
        assert "STANDALONE" in badge_outer.upper(), (
            f"badge markup missing STANDALONE marker: {badge_outer!r}")
        assert "EGS LINK SEVERED" in banner_outer.upper(), (
            f"banner markup missing EGS LINK SEVERED marker: {banner_outer!r}")

        browser.close()
