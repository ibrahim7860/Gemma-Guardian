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

from agents.egs_agent.scenario_state import build_initial_egs_state
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
    # Vary `function_or_command` per event so we can pin order on the
    # projected Contract 3 `task` field. The factory still writes Contract 11
    # lines; tail() returns Contract 3 shape (no `attempt`).
    events = [
        _valid_event(
            attempt=i,
            function_or_command=f"task_{i:02d}",
            timestamp=f"2026-05-07T10:00:{i:02d}.000Z",
        )
        for i in range(1, 13)  # 12 events
    ]
    with log.open("w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")

    got = tail(n=10, path=log)
    assert len(got) == 10
    # Last 10 in original write order are events[2..11] (function_or_command
    # task_03 .. task_12). The projection renames that field to `task`.
    expected_tasks = [f"task_{i:02d}" for i in range(3, 13)]
    assert [e["task"] for e in got] == expected_tasks
    # Sanity: every entry has the Contract 3 nested shape, not Contract 11.
    for e in got:
        assert set(e.keys()) == {"timestamp", "agent", "task", "outcome", "issue"}


def test_tail_skips_malformed_json_lines(tmp_path):
    log = tmp_path / "events.jsonl"
    valid_events = [
        _valid_event(
            attempt=i,
            function_or_command=f"task_{i:02d}",
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
    assert [e["task"] for e in got] == [f"task_{i:02d}" for i in range(1, 6)]


def test_tail_skips_schema_invalid_events(tmp_path):
    """Q3 critical: a JSON-valid but schema-invalid event must be filtered out
    so it cannot poison egs_state.recent_validation_events downstream."""
    log = tmp_path / "events.jsonl"
    valid_events = [
        _valid_event(
            attempt=i,
            function_or_command=f"task_{i:02d}",
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
    assert [e["task"] for e in got] == ["task_01", "task_02", "task_03"]
    # And the bad event's tell-tale task name must not appear (the poison
    # line had no `function_or_command` projected because it failed the
    # Contract 11 gate before projection ran).
    assert all(e.get("task") != "poison_task" for e in got)


def test_tail_drops_in_progress_events(tmp_path):
    """Contract 3 `recent_validation_events.outcome` only allows the three
    terminal outcomes. Contract 11 validation_event also allows
    `in_progress` (non-terminal). The projector must drop those entirely so
    they never reach egs_state."""
    log = tmp_path / "events.jsonl"
    terminal_a = _valid_event(
        attempt=1,
        function_or_command="task_terminal_a",
        timestamp="2026-05-07T10:00:01.000Z",
        outcome="success_first_try",
    )
    in_progress = _valid_event(
        attempt=2,
        function_or_command="task_in_progress",
        timestamp="2026-05-07T10:00:02.000Z",
        outcome="in_progress",
    )
    terminal_b = _valid_event(
        attempt=3,
        function_or_command="task_terminal_b",
        timestamp="2026-05-07T10:00:03.000Z",
        outcome="success_first_try",
    )
    with log.open("w") as f:
        f.write(json.dumps(terminal_a) + "\n")
        f.write(json.dumps(in_progress) + "\n")
        f.write(json.dumps(terminal_b) + "\n")

    got = tail(n=10, path=log)
    assert len(got) == 2, (
        f"expected 2 entries (in_progress dropped), got {len(got)}: {got}"
    )
    assert [e["task"] for e in got] == ["task_terminal_a", "task_terminal_b"]
    # And the in-progress entry must not appear by any of its tell-tale fields.
    assert all(e.get("task") != "task_in_progress" for e in got)
    assert all(e.get("outcome") != "in_progress" for e in got)


def test_tail_output_passes_egs_state_recent_validation_events_shape(tmp_path):
    """Load-bearing assertion that the projection actually unblocks Contract 3.

    For each entry returned by tail() against three valid Contract 11 events,
    construct a minimal egs_state (via build_initial_egs_state) with that
    entry installed in `recent_validation_events`, and assert
    validate("egs_state", ...) passes.
    """
    log = tmp_path / "events.jsonl"
    events = [
        _valid_event(
            attempt=i,
            function_or_command=f"task_{i:02d}",
            timestamp=f"2026-05-07T10:00:{i:02d}.000Z",
        )
        for i in range(1, 4)
    ]
    with log.open("w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")

    got = tail(n=10, path=log)
    assert len(got) == 3, got

    # Whole list at once: drop tail() output into egs_state and validate.
    egs_state = build_initial_egs_state("disaster_zone_v1")
    egs_state["recent_validation_events"] = got
    outcome = validate("egs_state", egs_state)
    assert outcome.valid, (
        f"egs_state with tail() output as recent_validation_events failed "
        f"Contract 3 validation: {outcome.errors}"
    )

    # Per-entry: each individual projected entry must also be acceptable on
    # its own as a single-element recent_validation_events list.
    for entry in got:
        per_entry_state = build_initial_egs_state("disaster_zone_v1")
        per_entry_state["recent_validation_events"] = [entry]
        per_outcome = validate("egs_state", per_entry_state)
        assert per_outcome.valid, (
            f"single-entry projection failed Contract 3 validation; "
            f"entry={entry}, errors={per_outcome.errors}"
        )
