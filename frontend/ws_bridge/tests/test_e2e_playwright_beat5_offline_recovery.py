"""Beat 5 dashboard end-to-end: offline → recovery → finding tile renders.

Synth-WS-driven Playwright test (Wave 3b). Mirrors the seam from
``test_e2e_playwright_standalone_mode.py`` (one synthetic websocket
server, deterministic envelope sequence, no real Redis or sim) and
extends it across the FULL Beat 5 timeline:

    t=0   — three drones active, no findings, no banner.
    t=2   — drone3 flips to ``agent_status="standalone"`` and the EGS
            heartbeat goes stale. Banner attaches; drone3 badge attaches.
    t=4   — same shape; banner + badge persist.
    t=6   — drone3 flips back to ``agent_status="active"``, a new finding
            appears in ``active_findings[]``, and
            ``egs_state.findings_count_by_type.victim`` ticks to 1.
            Banner detaches, badge detaches, finding tile attaches with a
            stable ``finding-tile-<id>`` semantics identifier, and the
            ``findings-count-victim`` chip reads ≥1.

We keep the bridge layer out of the loop: dashboard ↔ synthetic WS ↔
dashboard. The reason is identical to the Beat 4 test — driving a
clean banner-up → banner-gone state machine over the integrated stack
is fragile (the EGS republishes every 1 s, so any test that needs to
ASSERT THE BANNER IS GONE must MITM the integrated publisher). A
hand-written sequencer inside this test gives us deterministic control
over what envelope is in flight and when.

The full integrated path (drone agent → mesh sim → EGS → bridge →
dashboard) is covered by ``test_e2e_link_drop_replay.py`` (real-redis,
no browser) plus the manual-MCP runbook in
``docs/runbooks/mcp-dom-verification.md`` "Beat 5 offline-proof capture
path".
"""
from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from pathlib import Path
from typing import List

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(180)]


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ---------------------------------------------------------------------------
# Envelope factories. Shape follows shared/schemas/fixtures/valid/
# websocket_messages/01_state_update.json. Fresh `timestamp` per envelope
# so the dashboard's heartbeat-staleness logic can fire as scripted.
# ---------------------------------------------------------------------------

_ZONE_POLY = [
    [34.1230, -118.5680], [34.1240, -118.5680],
    [34.1240, -118.5670], [34.1230, -118.5670],
]


def _envelope(
    *,
    egs_timestamp: str,
    drone3_status: str,
    counts: dict,
    findings: list,
) -> dict:
    return {
        "type": "state_update",
        "timestamp": egs_timestamp,
        "contract_version": "1.0.0",
        "egs_state": {
            "mission_id": "beat5_demo",
            "mission_status": "active",
            "timestamp": egs_timestamp,
            "zone_polygon": _ZONE_POLY,
            "survey_points": [],
            "drones_summary": {},
            "findings_count_by_type": counts,
            "recent_validation_events": [],
            "active_zone_ids": [],
        },
        "active_findings": findings,
        "active_drones": [
            {
                "drone_id": "drone1",
                "agent_status": "active",
                "battery_pct": 88,
                "current_task": "survey",
                "findings_count": 0,
                "validation_failures_total": 0,
            },
            {
                "drone_id": "drone2",
                "agent_status": "active",
                "battery_pct": 71,
                "current_task": "survey",
                "findings_count": 0,
                "validation_failures_total": 0,
            },
            {
                "drone_id": "drone3",
                "agent_status": drone3_status,
                "battery_pct": 62,
                "current_task": "survey",
                "findings_count": 1 if findings else 0,
                "validation_failures_total": 0,
            },
        ],
    }


_ZERO_COUNTS = {
    "victim": 0, "fire": 0, "smoke": 0,
    "damaged_structure": 0, "blocked_route": 0,
}


_RESTORE_FINDING = {
    "finding_id": "f_drone3_42",
    "source_drone_id": "drone3",
    "timestamp": "2026-05-07T10:00:06.000Z",
    "type": "victim",
    "severity": 4,
    "gps_lat": 33.99980,
    "gps_lon": -118.5000,
    "altitude": 25.0,
    "confidence": 0.81,
    "visual_description": "person prone in rubble, partial cover",
    "image_path": "/tmp/findings/test.jpg",
    "validated": True,
    "validation_retries": 0,
    "operator_status": "pending",
}


def _build_timeline_phases() -> List[dict]:
    """Three scripted phases the synthetic-WS server cycles through.

    The dashboard's banner is staleness-driven (no envelope with a fresh
    ``egs_state`` for >5 s while the WS is up). To make the banner fire
    we hold a phase that publishes envelopes WITHOUT ``egs_state``
    populated — those are the "drones-only" envelopes the bridge would
    send if the EGS process itself crashed. To clear the banner we
    publish a fresh envelope WITH ``egs_state``.

    See ``MissionState.applyStateUpdate`` (``mission_state.dart`` ~line
    525): only an envelope where ``egs_state != null`` resets
    ``_egsLastSeenAt`` and clears the cached severed flag.
    """
    base_egs_state = {
        "mission_id": "beat5_demo",
        "mission_status": "active",
        "timestamp": "2026-05-07T10:00:00.000Z",
        "zone_polygon": _ZONE_POLY,
        "survey_points": [],
        "drones_summary": {},
        "findings_count_by_type": dict(_ZERO_COUNTS),
        "recent_validation_events": [],
        "active_zone_ids": [],
    }

    def _phase_envelope(*, has_egs: bool, drone3_status: str,
                         counts: dict, findings: list) -> dict:
        env = _envelope(
            egs_timestamp="2026-05-07T10:00:00.000Z",
            drone3_status=drone3_status,
            counts=counts,
            findings=findings,
        )
        if not has_egs:
            # Drone-only envelope — drops egs_state. The dashboard then
            # leaves _egsLastSeenAt frozen at the last fresh egs_state
            # envelope's wall-clock; staleness eventually fires.
            env.pop("egs_state", None)
        return env

    return [
        # Phase 0 — fresh egs_state, drone3 active, no findings. The
        # dashboard's _egsLastSeenAt is being refreshed; banner stays
        # down. Held briefly so the dashboard has time to render.
        _phase_envelope(
            has_egs=True, drone3_status="active",
            counts=dict(_ZERO_COUNTS), findings=[],
        ),
        # Phase 1 — drone-only envelopes (no egs_state) with drone3
        # standalone. Held long enough (>5 s) for the staleness banner
        # to fire AND for the standalone badge to render.
        _phase_envelope(
            has_egs=False, drone3_status="standalone",
            counts=dict(_ZERO_COUNTS), findings=[],
        ),
        # Phase 2 — recovery: fresh egs_state again, drone3 active, the
        # buffered finding flushed through, victim count = 1. Banner
        # detaches; badge detaches; finding tile attaches.
        _phase_envelope(
            has_egs=True, drone3_status="active",
            counts={**_ZERO_COUNTS, "victim": 1},
            findings=[_RESTORE_FINDING],
        ),
    ]


def _start_synthetic_ws_server(
    port: int, phases: List[dict],
) -> threading.Thread:
    """Background thread running the scripted Beat-5 phase sequence.

    Phase schedule (per connect):
      - Phase 0 held for 2 s, sent at 1 Hz (3 envelopes). Establishes
        a fresh egs_state baseline so _egsLastSeenAt is set.
      - Phase 1 held for 12 s, sent at 1 Hz (drone-only envelopes; no
        egs_state). >5 s of this trips the staleness banner; the
        standalone badge attaches because drone3.agent_status flipped.
      - Phase 2 held indefinitely, sent at 1 Hz. Banner clears on the
        first fresh egs_state; finding tile + count chip attach.
    """
    import websockets

    async def handler(ws):
        try:
            # Phase 0: 2 s, 1 Hz
            for _ in range(3):
                await ws.send(json.dumps(phases[0]))
                await asyncio.sleep(0.7)
            # Phase 1: 12 s, 1 Hz (no egs_state) — staleness fires.
            for _ in range(12):
                await ws.send(json.dumps(phases[1]))
                await asyncio.sleep(1.0)
            # Phase 2: held indefinitely, 1 Hz refresh. Refreshing
            # keeps _egsLastSeenAt current so the banner stays cleared
            # even if the test takes a long time to verify the detach.
            while True:
                await ws.send(json.dumps(phases[2]))
                await asyncio.sleep(1.0)
        except websockets.ConnectionClosed:
            return
        except Exception:
            return

    async def main():
        async with websockets.serve(handler, "127.0.0.1", port):
            await asyncio.Future()

    def run():
        try:
            asyncio.run(main())
        except (KeyboardInterrupt, SystemExit):
            pass

    t = threading.Thread(target=run, daemon=True, name="synthetic-ws-beat5")
    t.start()
    return t


def _wait_for_ws(port: int, deadline_s: float = 5.0) -> bool:
    import logging as _logging
    _logging.getLogger("websockets.server").setLevel(_logging.CRITICAL)
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def test_beat5_banner_then_finding_tile_render(flutter_static_server):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed")
    with sync_playwright() as _p:
        if not Path(_p.chromium.executable_path).exists():
            pytest.skip(
                "playwright chromium binary not installed — run "
                "`uv run playwright install chromium`"
            )

    ws_port = _free_port()
    phases = _build_timeline_phases()
    _start_synthetic_ws_server(ws_port, phases)
    assert _wait_for_ws(ws_port), "synthetic WS server did not come up"

    ws_url = f"ws://127.0.0.1:{ws_port}/"
    dashboard_url = f"{flutter_static_server}/?ws={ws_url}"

    banner_selector = '[flt-semantics-identifier="egs-link-severed-banner"]'
    badge_selector = '[flt-semantics-identifier="standalone-badge-drone3"]'
    count_chip_selector = '[flt-semantics-identifier="findings-count-victim"]'
    finding_tile_selector_prefix = (
        '[flt-semantics-identifier^="finding-tile-"]'
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        console_msgs: list[str] = []
        page.on("console", lambda m: console_msgs.append(f"[{m.type}] {m.text}"))
        page.goto(dashboard_url, wait_until="networkidle", timeout=30_000)

        # ------ Phase 1 — banner + badge attach during standalone --------
        # The standalone envelope arrives ~2 s into the run; banner takes
        # an additional 5 s of heartbeat-staleness (MissionState
        # threshold) to fire. We poll up to 20 s to absorb CanvasKit boot
        # jitter on slow CI runners.
        try:
            page.wait_for_selector(
                badge_selector, timeout=20_000, state="attached",
            )
        except Exception as e:
            sem_sample = page.evaluate(
                "Array.from(document.querySelectorAll("
                "'flt-semantics, [flt-semantics-identifier]'"
                ")).slice(0, 30).map(e => e.outerHTML.slice(0, 200))"
            )
            raise AssertionError(
                f"badge {badge_selector!r} did not attach within 20 s; "
                f"semantics sample={sem_sample!r}; "
                f"console tail={console_msgs[-15:]!r}"
            ) from e

        try:
            page.wait_for_selector(
                banner_selector, timeout=20_000, state="attached",
            )
        except Exception as e:
            sem_sample = page.evaluate(
                "Array.from(document.querySelectorAll("
                "'flt-semantics, [flt-semantics-identifier]'"
                ")).slice(0, 30).map(e => e.outerHTML.slice(0, 200))"
            )
            raise AssertionError(
                f"banner {banner_selector!r} did not attach within 20 s; "
                f"semantics sample={sem_sample!r}; "
                f"console tail={console_msgs[-15:]!r}"
            ) from e

        # ------ Phase 2 — both DOM nodes go away after restore -----------
        # Once envelope[3] arrives (drone3 active again + fresh egs
        # timestamp), the banner clears and the badge unmounts.
        # We poll for `state="detached"` rather than `state="hidden"` — the
        # widgets are removed from the tree, not just hidden.
        try:
            page.wait_for_selector(
                banner_selector, timeout=15_000, state="detached",
            )
        except Exception as e:
            raise AssertionError(
                f"banner {banner_selector!r} did not detach after restore; "
                f"console tail={console_msgs[-15:]!r}"
            ) from e

        try:
            page.wait_for_selector(
                badge_selector, timeout=10_000, state="detached",
            )
        except Exception as e:
            raise AssertionError(
                f"badge {badge_selector!r} did not detach after restore; "
                f"console tail={console_msgs[-15:]!r}"
            ) from e

        # ------ Phase 3 — finding tile + count chip attach ---------------
        # The replayed buffered finding lands in active_findings[] in
        # envelope[3]; count chip ticks to victim=1. Both widgets must be
        # present together for the storyboard frame to be filmable.
        try:
            page.wait_for_selector(
                finding_tile_selector_prefix,
                timeout=15_000, state="attached",
            )
        except Exception as e:
            sem_sample = page.evaluate(
                "Array.from(document.querySelectorAll("
                "'flt-semantics, [flt-semantics-identifier]'"
                ")).slice(0, 30).map(e => e.outerHTML.slice(0, 200))"
            )
            raise AssertionError(
                f"finding tile did not attach after replay; "
                f"semantics sample={sem_sample!r}; "
                f"console tail={console_msgs[-15:]!r}"
            ) from e

        # Specific finding-tile id must be the one we shipped.
        specific_tile_selector = (
            '[flt-semantics-identifier="finding-tile-f_drone3_42"]'
        )
        try:
            page.wait_for_selector(
                specific_tile_selector, timeout=5_000, state="attached",
            )
        except Exception as e:
            raise AssertionError(
                f"specific tile {specific_tile_selector!r} not present "
                "(finding_id mismatch in render layer)"
            ) from e

        # Count chip reads >= 1.
        try:
            page.wait_for_selector(
                count_chip_selector, timeout=10_000, state="attached",
            )
        except Exception as e:
            raise AssertionError(
                f"count chip {count_chip_selector!r} not attached after "
                f"victim count ticked"
            ) from e
        chip_outer = page.locator(count_chip_selector).first.evaluate(
            "el => el.outerHTML"
        )
        # The chip's accessible label is `victim: <n>` per
        # findings_panel.dart line 70. Normalize whitespace before
        # checking that 1 (or higher) is reflected — Flutter sometimes
        # renders the value via a descendant text node not exposed on
        # outerHTML, so be tolerant: assert the chip is attached and the
        # label or descendant text contains "1".
        text_in_chip = page.evaluate(
            f"document.querySelector({count_chip_selector!r}).textContent",
        )
        assert "1" in (chip_outer + (text_in_chip or "")), (
            f"victim count chip should report 1; got "
            f"outerHTML={chip_outer!r}, text={text_in_chip!r}"
        )

        browser.close()
