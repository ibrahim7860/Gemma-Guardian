"""Wave 3a (Component 4) — silent-zero diagnostic log loop.

EGS emits ``egs.findings_consumed total=N`` every 30s in production.
Even N=0 fires — that's the diagnostic signature for broken migrations
(the channel rename regressed) or for a mesh-sim crash mid-run (the
gateway stopped publishing). Without it, an EGS that's seeing zero
findings looks identical in logs to one with no findings produced yet.

These tests pin two properties:
  1. With no findings pushed, ``total=0`` appears within one period;
  2. After the coordinator's accept counter increments to 3 (via the
     real ``process_findings`` path), the log line reports ``total=3``.

We test ``findings_consumed_log_loop`` directly with a tight period
instead of booting full ``main()`` — the loop is the unit under test
and the wiring (one ``asyncio.create_task`` call) is trivially
inspectable in code review.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from agents.egs_agent import main as egs_main
from agents.egs_agent.coordinator import EGSCoordinator
from agents.egs_agent.validation import EGSValidationNode


def _finding(
    fid: str,
    ftype: str = "victim",
    drone_id: str = "drone1",
    lat: float = 34.0,
    lon: float = -118.0,
    ts: str = "2026-05-15T14:00:00.000Z",
) -> dict[str, Any]:
    return {
        "finding_id": fid,
        "source_drone_id": drone_id,
        "timestamp": ts,
        "type": ftype,
        "severity": 3,
        "gps_lat": lat,
        "gps_lon": lon,
        "altitude": 25.0,
        "confidence": 0.85,
        "visual_description": "Test fixture finding for silent-zero coverage.",
        "image_path": "/tmp/findings/test.jpg",
        "validated": True,
        "validation_retries": 0,
        "operator_status": "pending",
    }


async def _run_one_period(
    coord: EGSCoordinator, period_s: float = 0.05,
) -> None:
    """Spawn the diagnostic loop, let it fire once, then cancel."""
    task = asyncio.create_task(
        egs_main.findings_consumed_log_loop(coord, period_s=period_s),
    )
    # Give it enough wall-clock to land at least one log line.
    await asyncio.sleep(period_s * 3)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_silent_zero_warning_logged_within_30s(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The loop must emit ``egs.findings_consumed total=0`` even when no
    findings have been processed.

    Pinned with a tight period (50 ms) instead of literally waiting 30s;
    the contract is "the log fires every period_s ticks regardless of
    counter value", and that doesn't depend on the wall-clock value of
    period_s.
    """
    caplog.set_level(logging.INFO, logger=egs_main.__name__)
    coord = EGSCoordinator(EGSValidationNode())
    await _run_one_period(coord, period_s=0.05)

    consumed_logs = [
        r for r in caplog.records
        if "egs.findings_consumed" in r.getMessage()
    ]
    assert consumed_logs, (
        f"expected at least one egs.findings_consumed log line; "
        f"saw none. records={[r.getMessage() for r in caplog.records]}"
    )
    # Most recent line: total=0 because we never pushed a finding.
    assert "total=0" in consumed_logs[-1].getMessage(), (
        f"expected total=0 (no findings processed), got "
        f"{consumed_logs[-1].getMessage()!r}"
    )


@pytest.mark.asyncio
async def test_finding_count_reflected_in_periodic_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Push 3 unique findings through the real ``process_findings``
    path; the next periodic log must report ``total=3``.

    Uses three distinct types so cross-drone same-type dedup at the
    validator can't suppress them.
    """
    caplog.set_level(logging.INFO, logger=egs_main.__name__)
    coord = EGSCoordinator(EGSValidationNode())

    state = {
        "egs_state": {},
        "incoming_telemetry": [],
        "incoming_findings": [
            _finding("f_drone1_a", ftype="victim", lat=34.0028, lon=-118.5000),
            _finding("f_drone1_b", ftype="fire", lat=34.0000, lon=-118.4972),
            _finding("f_drone1_c", ftype="smoke", lat=33.9990, lon=-118.5000),
        ],
        "incoming_commands": [],
        "messages_to_publish": [],
        "trigger_replan": False,
    }
    coord.process_findings(state)
    assert coord._findings_accepted_total == 3, (
        f"sanity: dedup+validation should have accepted all 3; "
        f"counter={coord._findings_accepted_total}"
    )

    await _run_one_period(coord, period_s=0.05)

    consumed_logs = [
        r for r in caplog.records
        if "egs.findings_consumed" in r.getMessage()
    ]
    assert consumed_logs, "expected periodic log to fire"
    assert "total=3" in consumed_logs[-1].getMessage(), (
        f"expected total=3 after 3 findings accepted; got "
        f"{consumed_logs[-1].getMessage()!r}"
    )
