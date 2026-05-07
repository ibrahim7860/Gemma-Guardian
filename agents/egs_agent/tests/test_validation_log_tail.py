"""Tests for agents.egs_agent.validation_log_tail (Contract 11 consumer).

Per eng-review Q3 (2026-05-07), tail() must filter through the
`validate("validation_event", ...)` gate so that one malformed log line
cannot poison `egs_state.recent_validation_events` and break the locked
Contract 3 schema downstream.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from agents.egs_agent.validation_log_tail import tail
from shared.contracts import VERSION, validate


def _valid_event(
    *,
    agent_id: str = "drone1",
    layer: str = "drone",
    function_or_command: str = "report_finding",
    attempt: int = 1,
    valid: bool = True,
    rule_id: Optional[str] = None,
    outcome: str = "success_first_try",
    raw_call: Optional[Dict[str, Any]] = None,
    timestamp: str = "2026-05-07T10:00:00.000Z",
) -> Dict[str, Any]:
    """Produce a schema-valid validation_event dict.

    Mirrors the shape ValidationEventLogger.log writes per Contract 11.
    Asserts schema validity at construction so a fixture mistake fails loud.
    """
    evt = {
        "timestamp": timestamp,
        "agent_id": agent_id,
        "layer": layer,
        "function_or_command": function_or_command,
        "attempt": attempt,
        "valid": valid,
        "rule_id": rule_id,
        "outcome": outcome,
        "raw_call": raw_call,
        "contract_version": VERSION,
    }
    outcome_check = validate("validation_event", evt)
    assert outcome_check.valid, (
        f"_valid_event factory produced a schema-invalid payload: "
        f"{outcome_check.errors}"
    )
    return evt


def test_tail_returns_empty_when_file_missing():
    assert tail(n=5, path=Path("/tmp/nonexistent_test_file.jsonl")) == []


def test_tail_returns_last_n_in_order(tmp_path):
    log = tmp_path / "events.jsonl"
    events = [
        _valid_event(
            attempt=i,
            timestamp=f"2026-05-07T10:00:{i:02d}.000Z",
        )
        for i in range(1, 13)  # 12 events
    ]
    with log.open("w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")

    got = tail(n=10, path=log)
    assert len(got) == 10
    # Last 10 in original write order are events[2..11] (attempts 3..12).
    expected_attempts = list(range(3, 13))
    assert [e["attempt"] for e in got] == expected_attempts


def test_tail_skips_malformed_json_lines(tmp_path):
    log = tmp_path / "events.jsonl"
    valid_events = [
        _valid_event(
            attempt=i,
            timestamp=f"2026-05-07T10:00:{i:02d}.000Z",
        )
        for i in range(1, 6)  # 5 events
    ]
    with log.open("w") as f:
        for e in valid_events[:2]:
            f.write(json.dumps(e) + "\n")
        f.write("{this is not valid json\n")  # garbage line
        for e in valid_events[2:]:
            f.write(json.dumps(e) + "\n")

    got = tail(n=10, path=log)
    assert len(got) == 5  # garbage line silently skipped
    assert [e["attempt"] for e in got] == [1, 2, 3, 4, 5]


def test_tail_skips_schema_invalid_events(tmp_path):
    """Q3 critical: a JSON-valid but schema-invalid event must be filtered out
    so it cannot poison egs_state.recent_validation_events downstream."""
    log = tmp_path / "events.jsonl"
    valid_events = [
        _valid_event(
            attempt=i,
            timestamp=f"2026-05-07T10:00:{i:02d}.000Z",
        )
        for i in range(1, 4)  # 3 valid events
    ]
    # JSON-valid but missing the required `outcome` field. The schema lists
    # `outcome` in `required` so this must fail validate("validation_event").
    schema_invalid = {
        "timestamp": "2026-05-07T10:00:99.000Z",
        "agent_id": "drone1",
        "layer": "drone",
        "function_or_command": "report_finding",
        "attempt": 99,
        "valid": True,
        "rule_id": None,
        # "outcome": <-- intentionally omitted
        "raw_call": None,
        "contract_version": VERSION,
    }
    # Defensive: confirm the fixture actually fails Contract 11 — the test
    # only protects against a real failure mode if this is genuinely invalid.
    assert not validate("validation_event", schema_invalid).valid

    with log.open("w") as f:
        f.write(json.dumps(valid_events[0]) + "\n")
        f.write(json.dumps(schema_invalid) + "\n")  # poisoned line
        f.write(json.dumps(valid_events[1]) + "\n")
        f.write(json.dumps(valid_events[2]) + "\n")

    got = tail(n=10, path=log)
    assert len(got) == 3, (
        f"schema-invalid event should be filtered; got: {got}"
    )
    assert [e["attempt"] for e in got] == [1, 2, 3]
    # And the bad event's tell-tale attempt=99 must not appear.
    assert all(e.get("attempt") != 99 for e in got)
