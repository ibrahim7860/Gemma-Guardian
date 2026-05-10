"""Replay-mode regression test for ``scripts/check_beat5.py``.

Builds a synthetic ``ws_frames.jsonl`` whose recorded ``received_at_s``
timestamps mirror the t=100 -> t=180 -> t=200 standalone window, plus a
synthetic ``validation_events.jsonl`` with a drone3 ``report_finding``.
Invokes ``check_beat5`` via subprocess in replay mode and asserts the
exit code is 0 (all six A-assertions pass). Negative test: same WS
frames but an empty validation log -> A2 fails -> exit code != 0.

These tests live alongside the live-mode tests so a regression in the
replay path is caught without standing up a bridge.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CHECK_BEAT5 = _REPO_ROOT / "scripts" / "check_beat5.py"


def _envelope(
    drone3_status: str,
    counts: dict[str, int] | None = None,
) -> dict:
    """Build a minimal bridge state_update envelope for the verifier."""
    return {
        "type": "state_update",
        "active_drones": [
            {"drone_id": "drone1", "agent_status": "active"},
            {"drone_id": "drone2", "agent_status": "active"},
            {"drone_id": "drone3", "agent_status": drone3_status},
        ],
        "egs_state": {
            "findings_count_by_type": dict(counts or {}),
        },
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _build_ws_frames(path: Path) -> None:
    """Synthetic frames spanning anchor -> standalone window -> restore -> tick.

    Timestamps are monotonic-style floats matching the t=100 -> t=180 ->
    t=200 timeline in the resilience_v1 scenario doc. The first envelope
    establishes the anchor; subsequent scenario_t values are derived as
    (received_at_s - anchor).
    """
    rows = [
        # Anchor envelope: drone3 active. scenario_t = 0.0
        {"received_at_s": 0.0, "envelope": _envelope("active", {})},
        # Scenario t=121: drone3 first standalone (passes A1 window 100..150).
        {"received_at_s": 121.0, "envelope": _envelope("standalone", {})},
        # Still standalone at t=180 — counts must remain 0 to satisfy A3
        # (no .delivered ticks while standalone).
        {"received_at_s": 180.0, "envelope": _envelope("standalone", {})},
        # Scenario t=200: drone3 back to active (passes A5 t>=150).
        # counts still 0 -> total_at_restore = 0.
        {"received_at_s": 200.0, "envelope": _envelope("active", {})},
        # Scenario t=200.5: post-restore count tick. delta = 0.5s,
        # satisfies A3 (>=0) and A4 (<=5s).
        {"received_at_s": 200.5, "envelope": _envelope("active", {"victim": 1})},
    ]
    _write_jsonl(path, rows)


def _build_validation_events(path: Path) -> None:
    rows = [
        {
            "agent_id": "drone3",
            "function_or_command": "report_finding",
            "valid": True,
            "raw_call": {
                "finding_id": "drone3-standalone-001",
                "arguments": {"finding_id": "drone3-standalone-001"},
            },
        },
    ]
    _write_jsonl(path, rows)


def _run_check_beat5(
    ws_log: Path,
    validation_log: Path,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(_CHECK_BEAT5),
            "--ws-replay-log",
            str(ws_log),
            "--validation-log",
            str(validation_log),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ},
    )


def test_replay_passes_all_assertions(tmp_path: Path) -> None:
    ws_log = tmp_path / "ws_frames.jsonl"
    val_log = tmp_path / "validation_events.jsonl"
    _build_ws_frames(ws_log)
    _build_validation_events(val_log)

    result = _run_check_beat5(ws_log, val_log)
    combined = result.stdout + result.stderr
    assert result.returncode == 0, (
        f"expected rc=0 (all A1-A6 pass) but got rc={result.returncode}\n"
        f"--- stdout/stderr ---\n{combined}"
    )
    # Sanity check the PASS banner made it to stdout.
    assert "PASS" in combined


def test_replay_a2_fails_with_empty_validation_log(tmp_path: Path) -> None:
    ws_log = tmp_path / "ws_frames.jsonl"
    val_log = tmp_path / "validation_events.jsonl"
    _build_ws_frames(ws_log)
    val_log.write_text("")  # empty file -> no successful report_finding

    result = _run_check_beat5(ws_log, val_log)
    combined = result.stdout + result.stderr
    assert result.returncode != 0, (
        f"expected non-zero rc (A2 should fail) but got rc=0\n"
        f"--- stdout/stderr ---\n{combined}"
    )
    # The failure summary mentions A2 specifically.
    assert "A2" in combined


def test_replay_missing_log_returns_exit_2(tmp_path: Path) -> None:
    ws_log = tmp_path / "does_not_exist.jsonl"
    val_log = tmp_path / "validation_events.jsonl"
    val_log.write_text("")

    result = _run_check_beat5(ws_log, val_log)
    assert result.returncode == 2, (
        f"expected rc=2 for missing replay log, got rc={result.returncode}\n"
        f"stderr={result.stderr}"
    )
    assert "empty or missing" in (result.stdout + result.stderr)


def test_replay_skips_envelopes_with_bad_timestamps(tmp_path: Path) -> None:
    """Lines with missing or non-numeric received_at_s must be skipped, not
    silently re-anchored to time.monotonic().

    If every line is corrupt, the file is effectively empty and the
    "log is empty or missing" exit-2 path should fire — proving the
    skip-on-bad-ts path doesn't fall back to live-mode monotonic clocks.
    """
    ws_log = tmp_path / "ws_frames.jsonl"
    val_log = tmp_path / "validation_events.jsonl"
    val_log.write_text("")

    # All four lines have bad/missing received_at_s. None should ingest.
    rows = [
        {"envelope": _envelope("active", {})},  # missing received_at_s
        {"received_at_s": None, "envelope": _envelope("active", {})},
        {"received_at_s": "not-a-number", "envelope": _envelope("active", {})},
        {"received_at_s": [], "envelope": _envelope("active", {})},
    ]
    _write_jsonl(ws_log, rows)

    result = _run_check_beat5(ws_log, val_log)
    assert result.returncode == 2, (
        f"expected rc=2 (effectively empty after skipping bad ts), "
        f"got rc={result.returncode}\nstderr={result.stderr}"
    )
    assert "empty or missing" in (result.stdout + result.stderr)
