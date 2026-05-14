"""Playwright e2e for the Beat 3c "wow moment" `ValidationWowBanner`.

Synth-WS driven (Wave 4, Lane B), mirroring the seam from
``test_e2e_playwright_standalone_mode.py`` and
``test_e2e_playwright_beat5_offline_recovery.py``. The wow moment surfaces
the EGS replan retry loop live in the dashboard: a first attempt that
validates RED on ``ASSIGNMENT_TOTAL_MISMATCH`` followed by a second
attempt that validates GREEN. The storyboard frame (Beat 3c, 0:55 – 1:05)
requires both chips visible in the same frame.

Why synth-WS instead of the real EGS coordinator?

The integrated stack is covered separately by
``test_e2e_egs_replan_attempt_log_real_redis.py`` (sibling lane). This
file proves only one thing: **the Semantics identifiers shipped on the
banner (`validation-wow-banner`, `validation-attempt-<n>`,
``-outcome``, ``-text``) are reachable from a browser when the
dashboard renders a populated `replan_in_flight_attempt_log`**, the
banner appears/disappears with the envelope sequence, and the literal
``corrective_text`` from `RULE_REGISTRY[ASSIGNMENT_TOTAL_MISMATCH]`
lands in the DOM verbatim.

A hand-written sequencer here lets us drive the four scripted states
(empty → red → red+green → cleared) deterministically and assert what
detaches vs attaches, without depending on real Gemma 4 latency.

The single failing-after-retries test case (Phase 3c fallback render)
is also covered here so the capture-day fallback path has DOM proof.
"""
from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(180)]


# ---------------------------------------------------------------------------
# Envelope factories — shape mirrors
# ``shared/schemas/fixtures/valid/websocket_messages/01_state_update.json``
# with the Contract 3 transient field
# ``egs_state.replan_in_flight_attempt_log`` populated.
# ---------------------------------------------------------------------------

_ZONE_POLY = [
    [34.1230, -118.5680], [34.1240, -118.5680],
    [34.1240, -118.5670], [34.1230, -118.5670],
]

# Literal corrective_text emitted by
# ``RULE_REGISTRY[ASSIGNMENT_TOTAL_MISMATCH].corrective_template.format(
#     assigned=27, total=25)``.
# Pinned here so the DOM assertion matches what the server actually emits
# (single source of truth lives in ``shared/contracts/rules.py``). Anchor
# substring ``"27 points but 25"`` is what the storyboard frame relies on.
_CORRECTIVE_TEXT_27_25 = (
    "Your assignments cover 27 points but 25 are available. "
    "Reassign so every point is covered exactly once."
)


def _envelope(*, attempt_log: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "type": "state_update",
        "timestamp": "2026-05-12T15:30:00.000Z",
        "contract_version": "1.1.0",
        "egs_state": {
            "mission_id": "wow_demo",
            "mission_status": "active",
            "timestamp": "2026-05-12T15:30:00.000Z",
            "zone_polygon": _ZONE_POLY,
            "survey_points": [],
            "drones_summary": {},
            "findings_count_by_type": {
                "victim": 0, "fire": 0, "smoke": 0,
                "damaged_structure": 0, "blocked_route": 0,
            },
            "recent_validation_events": [],
            "active_zone_ids": [],
            "replan_in_flight_attempt_log": attempt_log,
        },
        "active_findings": [],
        "active_drones": [],
    }


# --- Pre-baked attempt records --------------------------------------------

_ATTEMPT_1_FAILED = {
    "attempt_n": 1,
    "valid": False,
    "rule_id": "ASSIGNMENT_TOTAL_MISMATCH",
    "corrective_text": _CORRECTIVE_TEXT_27_25,
    "details": {"assigned": 27, "total": 25},
    "timestamp": "2026-05-12T15:30:00.000Z",
}

_ATTEMPT_2_PASSED = {
    "attempt_n": 2,
    "valid": True,
    "rule_id": None,
    "corrective_text": None,
    "details": {},
    "timestamp": "2026-05-12T15:30:08.000Z",
}

# Three back-to-back invalid attempts — the deterministic-fallback /
# max-retries-exceeded shape from Phase 3c. Each row should still render
# with a red FAILED chip, no green chip anywhere in the banner.
_ATTEMPT_1_FAILED_OF_3 = {**_ATTEMPT_1_FAILED, "timestamp": "2026-05-12T15:30:00.000Z"}
_ATTEMPT_2_FAILED_OF_3 = {
    **_ATTEMPT_1_FAILED,
    "attempt_n": 2,
    "timestamp": "2026-05-12T15:30:06.000Z",
}
_ATTEMPT_3_FAILED_OF_3 = {
    **_ATTEMPT_1_FAILED,
    "attempt_n": 3,
    "timestamp": "2026-05-12T15:30:12.000Z",
}


# ---------------------------------------------------------------------------
# Synth-WS server: sends a scripted sequence of envelopes with small gaps
# so the dashboard's AnimatedSwitcher has time to settle between frames.
# ---------------------------------------------------------------------------


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _start_synthetic_ws_server(
    port: int,
    sequence: List[Dict[str, Any]],
    *,
    step_delay_s: float = 1.0,
    hold_forever: bool = True,
) -> threading.Thread:
    """Background thread serving the scripted envelope sequence.

    Each connected client receives every envelope in ``sequence`` with
    ``step_delay_s`` between them. When ``hold_forever`` is True the
    last envelope is republished at 1 Hz indefinitely so the dashboard's
    egs-heartbeat staleness detector never flips the EGS-LINK-SEVERED
    banner (which would race against our wow-banner assertions).
    """
    import websockets

    async def handler(ws):
        try:
            for env in sequence:
                await ws.send(json.dumps(env))
                await asyncio.sleep(step_delay_s)
            if hold_forever and sequence:
                last = sequence[-1]
                while True:
                    await ws.send(json.dumps(last))
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

    t = threading.Thread(target=run, daemon=True, name=f"synthetic-ws-{port}")
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


# ---------------------------------------------------------------------------
# Diagnostic helper: a semantics-tree sample for the failure path.
# Mirrors the pattern used by the standalone-mode and beat-5 tests.
# ---------------------------------------------------------------------------


def _sem_sample(page: Any) -> Any:
    return page.evaluate(
        "Array.from(document.querySelectorAll("
        "'flt-semantics, [flt-semantics-identifier]'"
        ")).slice(0, 30).map(e => e.outerHTML.slice(0, 200))"
    )


def _playwright_or_skip():
    """Skip cleanly if Playwright or its Chromium binary is missing.

    Returns the imported ``sync_playwright`` callable so callers can do
    ``with _playwright_or_skip()() as p:``.
    """
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
    return sync_playwright


# ---------------------------------------------------------------------------
# Selectors. Sourced from
# ``frontend/flutter_dashboard/lib/widgets/validation_wow_banner.dart``.
# ---------------------------------------------------------------------------

BANNER_SELECTOR = '[flt-semantics-identifier="validation-wow-banner"]'


def _attempt_selector(n: int) -> str:
    return f'[flt-semantics-identifier="validation-attempt-{n}"]'


def _outcome_selector(n: int) -> str:
    return f'[flt-semantics-identifier="validation-attempt-{n}-outcome"]'


def _text_selector(n: int) -> str:
    return f'[flt-semantics-identifier="validation-attempt-{n}-text"]'


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_validation_wow_banner_hidden_when_no_replan(flutter_static_server):
    """With an empty ``replan_in_flight_attempt_log`` the banner is not
    rendered at all — `AnimatedSwitcher` shows a ``SizedBox.shrink()``
    and the `validation-wow-banner` Semantics node never attaches.
    """
    sync_playwright_factory = _playwright_or_skip()

    ws_port = _free_port()
    _start_synthetic_ws_server(ws_port, [_envelope(attempt_log=[])])
    assert _wait_for_ws(ws_port), "synthetic WS server did not come up"

    ws_url = f"ws://127.0.0.1:{ws_port}/"
    dashboard_url = f"{flutter_static_server}/?ws={ws_url}"

    with sync_playwright_factory() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            console_msgs: List[str] = []
            page.on("console", lambda m: console_msgs.append(f"[{m.type}] {m.text}"))
            page.goto(dashboard_url, wait_until="networkidle", timeout=30_000)

            # Give the dashboard ample time to ingest the first envelope
            # and the AnimatedSwitcher to settle on the empty branch.
            page.wait_for_timeout(2_000)

            count = page.locator(BANNER_SELECTOR).count()
            assert count == 0, (
                f"banner should be absent when attempt_log is empty; "
                f"got count={count}; "
                f"semantics sample={_sem_sample(page)!r}; "
                f"console tail={console_msgs[-15:]!r}"
            )
        finally:
            browser.close()


def test_validation_wow_banner_shows_red_then_green_sequence(
    flutter_static_server, tmp_path
):
    """The load-bearing case.

    Drives the three-envelope timeline (empty → red → red+green) and
    asserts the banner mounts, the attempt-1 outcome reads FAILED with
    the literal corrective text, then attempt-2 mounts alongside reading
    PASSED. Captures the final mid-state screenshot for visual-regression
    diffing on capture day.
    """
    sync_playwright_factory = _playwright_or_skip()

    sequence = [
        # a) seed: empty log → banner hidden
        _envelope(attempt_log=[]),
        # b) attempt 1 invalid → red banner with corrective text
        _envelope(attempt_log=[_ATTEMPT_1_FAILED]),
        # c) attempt 1 invalid + attempt 2 valid → red + green together
        _envelope(attempt_log=[_ATTEMPT_1_FAILED, _ATTEMPT_2_PASSED]),
    ]
    ws_port = _free_port()
    # 2 s between scripted steps gives the AnimatedSwitcher (250 ms)
    # plenty of slack to settle and the WS publisher to flush.
    _start_synthetic_ws_server(ws_port, sequence, step_delay_s=2.0)
    assert _wait_for_ws(ws_port), "synthetic WS server did not come up"

    ws_url = f"ws://127.0.0.1:{ws_port}/"
    dashboard_url = f"{flutter_static_server}/?ws={ws_url}"

    capture_dir = Path("/tmp/gg_wow_moment_capture")
    capture_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = capture_dir / "wow_moment_passed.png"

    with sync_playwright_factory() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                viewport={"width": 1280, "height": 720},
            )
            page = context.new_page()
            console_msgs: List[str] = []
            page.on(
                "console",
                lambda m: console_msgs.append(f"[{m.type}] {m.text}"),
            )
            page.goto(dashboard_url, wait_until="networkidle", timeout=30_000)

            # --- After envelope (a): banner should not be present ----------
            # Give the dashboard a moment to ingest the seed envelope but
            # NOT long enough for envelope (b) to arrive (step_delay_s=2.0
            # so we check at ~1.0s in).
            page.wait_for_timeout(1_000)
            pre_count = page.locator(BANNER_SELECTOR).count()
            assert pre_count == 0, (
                f"banner should be absent on seed envelope; got "
                f"count={pre_count}; "
                f"semantics sample={_sem_sample(page)!r}"
            )

            # --- After envelope (b): attempt-1 attaches, FAILED chip,
            # corrective text visible. Wait for banner attach (up to 15 s
            # to absorb step-delay + CanvasKit jitter).
            try:
                page.wait_for_selector(
                    BANNER_SELECTOR, timeout=15_000, state="attached",
                )
                page.wait_for_selector(
                    _attempt_selector(1), timeout=10_000, state="attached",
                )
            except Exception as e:
                raise AssertionError(
                    f"banner / attempt-1 did not attach after envelope (b); "
                    f"semantics sample={_sem_sample(page)!r}; "
                    f"console tail={console_msgs[-15:]!r}"
                ) from e

            outcome_1_outer = page.locator(_outcome_selector(1)).first.evaluate(
                "el => el.outerHTML"
            )
            outcome_1_text = page.evaluate(
                f"document.querySelector({_outcome_selector(1)!r}).textContent",
            ) or ""
            assert "FAILED" in (outcome_1_outer + outcome_1_text).upper(), (
                f"attempt-1 outcome chip should read FAILED; "
                f"outerHTML={outcome_1_outer!r}, text={outcome_1_text!r}"
            )

            text_1_outer = page.locator(_text_selector(1)).first.evaluate(
                "el => el.outerHTML"
            )
            text_1_text = page.evaluate(
                f"document.querySelector({_text_selector(1)!r}).textContent",
            ) or ""
            assert "27 points but 25" in (text_1_outer + text_1_text), (
                f"attempt-1 corrective text should contain literal "
                f"'27 points but 25'; outerHTML={text_1_outer!r}, "
                f"text={text_1_text!r}"
            )

            # --- After envelope (c): attempt-2 also attaches; both rows
            # render together. Wait for attempt-2 to attach.
            try:
                page.wait_for_selector(
                    _attempt_selector(2), timeout=15_000, state="attached",
                )
            except Exception as e:
                raise AssertionError(
                    f"attempt-2 did not attach after envelope (c); "
                    f"semantics sample={_sem_sample(page)!r}; "
                    f"console tail={console_msgs[-15:]!r}"
                ) from e

            # attempt-1 must still be present in the same frame — this is
            # the storyboard moment, red + green visible together.
            assert page.locator(_attempt_selector(1)).count() >= 1, (
                "attempt-1 row disappeared when attempt-2 arrived; "
                "banner is supposed to show both rows simultaneously"
            )

            outcome_2_outer = page.locator(_outcome_selector(2)).first.evaluate(
                "el => el.outerHTML"
            )
            outcome_2_text = page.evaluate(
                f"document.querySelector({_outcome_selector(2)!r}).textContent",
            ) or ""
            assert "PASSED" in (outcome_2_outer + outcome_2_text).upper(), (
                f"attempt-2 outcome chip should read PASSED; "
                f"outerHTML={outcome_2_outer!r}, text={outcome_2_text!r}"
            )

            # --- Visual-regression capture ---------------------------------
            # Settle one more frame so the AnimatedSwitcher finishes its
            # 250 ms fade before the screenshot is taken.
            page.wait_for_timeout(500)
            page.screenshot(path=str(screenshot_path), full_page=True)
            assert screenshot_path.exists() and screenshot_path.stat().st_size > 0, (
                f"expected screenshot at {screenshot_path} to be non-empty"
            )
        finally:
            browser.close()


def test_validation_wow_banner_clears_after_empty_envelope(flutter_static_server):
    """After running the full red+green sequence, a follow-up envelope with
    an empty ``replan_in_flight_attempt_log`` must remove the banner
    from the DOM (3 s server-side clear from the EGSCoordinator).
    """
    sync_playwright_factory = _playwright_or_skip()

    sequence = [
        _envelope(attempt_log=[]),
        _envelope(attempt_log=[_ATTEMPT_1_FAILED]),
        _envelope(attempt_log=[_ATTEMPT_1_FAILED, _ATTEMPT_2_PASSED]),
        # Final clear envelope (mimics the coordinator's 3 s callback)
        _envelope(attempt_log=[]),
    ]
    ws_port = _free_port()
    _start_synthetic_ws_server(ws_port, sequence, step_delay_s=2.0)
    assert _wait_for_ws(ws_port), "synthetic WS server did not come up"

    ws_url = f"ws://127.0.0.1:{ws_port}/"
    dashboard_url = f"{flutter_static_server}/?ws={ws_url}"

    with sync_playwright_factory() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            console_msgs: List[str] = []
            page.on(
                "console",
                lambda m: console_msgs.append(f"[{m.type}] {m.text}"),
            )
            page.goto(dashboard_url, wait_until="networkidle", timeout=30_000)

            # First wait for the banner to mount mid-sequence so we know
            # the dashboard actually saw the populated envelopes.
            try:
                page.wait_for_selector(
                    BANNER_SELECTOR, timeout=20_000, state="attached",
                )
            except Exception as e:
                raise AssertionError(
                    f"banner never attached mid-sequence; "
                    f"semantics sample={_sem_sample(page)!r}; "
                    f"console tail={console_msgs[-15:]!r}"
                ) from e

            # Then wait for the clear envelope to detach it.
            try:
                page.wait_for_selector(
                    BANNER_SELECTOR, timeout=15_000, state="detached",
                )
            except Exception as e:
                raise AssertionError(
                    f"banner did not detach after empty-log envelope; "
                    f"semantics sample={_sem_sample(page)!r}; "
                    f"console tail={console_msgs[-15:]!r}"
                ) from e
        finally:
            browser.close()


def test_validation_wow_banner_failed_after_retries_state(flutter_static_server):
    """Three attempts, all ``valid=false`` — the deterministic-fallback
    render path. Every row must show FAILED; no PASSED chip anywhere.
    """
    sync_playwright_factory = _playwright_or_skip()

    sequence = [
        _envelope(attempt_log=[]),
        _envelope(attempt_log=[
            _ATTEMPT_1_FAILED_OF_3,
            _ATTEMPT_2_FAILED_OF_3,
            _ATTEMPT_3_FAILED_OF_3,
        ]),
    ]
    ws_port = _free_port()
    _start_synthetic_ws_server(ws_port, sequence, step_delay_s=2.0)
    assert _wait_for_ws(ws_port), "synthetic WS server did not come up"

    ws_url = f"ws://127.0.0.1:{ws_port}/"
    dashboard_url = f"{flutter_static_server}/?ws={ws_url}"

    with sync_playwright_factory() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            console_msgs: List[str] = []
            page.on(
                "console",
                lambda m: console_msgs.append(f"[{m.type}] {m.text}"),
            )
            page.goto(dashboard_url, wait_until="networkidle", timeout=30_000)

            try:
                page.wait_for_selector(
                    BANNER_SELECTOR, timeout=20_000, state="attached",
                )
                for n in (1, 2, 3):
                    page.wait_for_selector(
                        _attempt_selector(n), timeout=10_000, state="attached",
                    )
            except Exception as e:
                raise AssertionError(
                    f"3-attempt failed-after-retries banner did not fully "
                    f"render; semantics sample={_sem_sample(page)!r}; "
                    f"console tail={console_msgs[-15:]!r}"
                ) from e

            for n in (1, 2, 3):
                outer = page.locator(_outcome_selector(n)).first.evaluate(
                    "el => el.outerHTML"
                )
                txt = page.evaluate(
                    f"document.querySelector({_outcome_selector(n)!r}).textContent",
                ) or ""
                combined = (outer + txt).upper()
                assert "FAILED" in combined, (
                    f"attempt-{n} outcome should be FAILED; "
                    f"outerHTML={outer!r}, text={txt!r}"
                )
                assert "PASSED" not in combined, (
                    f"attempt-{n} should NOT show PASSED in the "
                    f"failed-after-retries state; outerHTML={outer!r}, "
                    f"text={txt!r}"
                )
        finally:
            browser.close()
