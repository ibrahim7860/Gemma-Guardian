"""Task 6 integration test (per docs/plans/2026-05-07-qasim-egs-gate2.md).

Boots the EGSCoordinator graph in-process (no Redis, no Ollama), injects
three Contract-4-shaped findings from three different drones with three
different finding types, and asserts:

1. ``findings_count_by_type`` increments correctly per type.
2. The full ``egs_state`` after the graph tick passes
   ``validate("egs_state", egs_state)`` — schema validity is the
   load-bearing assertion.

Plus a second integration test that pins the Q3 invariant from the
eng-review (2026-05-07): after the every-5th-tick refresh fires, the
egs_state still passes Contract 3 schema validation. This catches the
silent-poisoning failure mode in an integration setting (the unit-test
coverage in `test_validation_log_tail.py` only exercises `tail()` in
isolation).

GPS coordinates were chosen so:
  * All three pairwise distances are > 280 m (far above the 10 m
    cross-drone dedup threshold).
  * All three finding types differ, so the cross-drone dedup rule
    (which only fires on same-type within 10 m / 30 s) cannot reject
    any of the three.
"""
from __future__ import annotations

import asyncio
import json

from agents.egs_agent import validation_log_tail
from agents.egs_agent.coordinator import EGSCoordinator
from agents.egs_agent.scenario_state import build_initial_egs_state
from agents.egs_agent.validation import EGSValidationNode
from shared.contracts import VERSION, validate


def _finding(
    drone_id: str,
    ftype: str,
    lat: float,
    lon: float,
    fid: str,
    ts: str,
):
    """Produce a Contract-4-shaped finding payload.

    Field shape mirrors `shared/schemas/finding.json` (verified at the time
    of authoring): all 14 required fields are present, severity in [1,5],
    confidence in [0,1], visual_description ≥ 10 chars, validation_retries
    in [0,3], operator_status one of {pending, approved, dismissed}.
    """
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
        "visual_description": "Test fixture finding for integration coverage.",
        "image_path": "/tmp/findings/test.jpg",
        "validated": True,
        "validation_retries": 0,
        "operator_status": "pending",
    }


def test_three_findings_increment_counts_and_remain_schema_valid():
    """Three findings of three types from three drones flow through the
    coordinator graph; counts increment by exactly 1 per type and the
    resulting egs_state remains Contract 3 schema-valid."""

    async def run():
        coord = EGSCoordinator(EGSValidationNode())
        state = {
            "egs_state": build_initial_egs_state("disaster_zone_v1"),
            "incoming_telemetry": [],
            "incoming_findings": [
                _finding(
                    "drone1", "victim",
                    34.0028, -118.5000, "f_drone1_001",
                    "2026-05-07T10:00:00.000Z",
                ),
                _finding(
                    "drone2", "fire",
                    34.0000, -118.4972, "f_drone2_001",
                    "2026-05-07T10:00:01.000Z",
                ),
                _finding(
                    "drone3", "smoke",
                    33.9990, -118.5000, "f_drone3_001",
                    "2026-05-07T10:00:02.000Z",
                ),
            ],
            "incoming_commands": [],
            "messages_to_publish": [],
            # Keep the LLM path off; coordinator's should_replan returns END
            # when trigger_replan is False, so no background replan task is
            # spawned and no Ollama call happens.
            "trigger_replan": False,
        }

        new_state = await coord.graph.ainvoke(state)

        counts = new_state["egs_state"]["findings_count_by_type"]
        assert counts["victim"] == 1, counts
        assert counts["fire"] == 1, counts
        assert counts["smoke"] == 1, counts
        assert counts["damaged_structure"] == 0, counts
        assert counts["blocked_route"] == 0, counts

        # Load-bearing assertion: the full envelope must remain Contract 3
        # valid after the tick. If this fails, the dashboard publish path
        # would be broken.
        outcome = validate("egs_state", new_state["egs_state"])
        assert outcome.valid, (
            f"egs_state failed Contract 3 schema validation after a graph "
            f"tick that processed three findings: {outcome.errors}"
        )

    asyncio.run(run())


def _validation_event(attempt: int, ts: str):
    """Hand-rolled schema-valid validation_event payload.

    Mirrors the helper in `test_coordinator.py` so this integration test is
    insulated from any future fixture-shape drift.
    """
    return {
        "timestamp": ts,
        "agent_id": "drone1",
        "layer": "drone",
        "function_or_command": "report_finding",
        "attempt": attempt,
        "valid": True,
        "rule_id": None,
        "outcome": "success_first_try",
        "raw_call": None,
        "contract_version": VERSION,
    }


def test_egs_state_remains_schema_valid_after_validation_event_refresh(
    tmp_path, monkeypatch,
):
    """Q3 invariant pin (integration setting): after the every-5th-tick
    refresh fires and `recent_validation_events` is repopulated from the
    on-disk JSONL log, every entry that lands in egs_state must have
    survived the `validate("validation_event", ...)` gate inside
    `tail()`. Catches silent-poisoning regressions that the unit-level
    `test_validation_log_tail.py` cannot cover (it only exercises tail()
    in isolation, never through the LangGraph tick).
    """
    # Seed the log with TWO schema-valid events plus ONE schema-invalid
    # poison line (missing `outcome`). After the 5th tick fires the
    # refresh, the two valid events should appear and the poison line
    # should not.
    log = tmp_path / "events.jsonl"
    valid_events = [
        _validation_event(i, f"2026-05-07T10:00:{i:02d}.000Z")
        for i in range(1, 3)
    ]
    poisoned = {
        "timestamp": "2026-05-07T10:00:99.000Z",
        "agent_id": "drone1",
        "layer": "drone",
        "function_or_command": "report_finding",
        "attempt": 99,
        "valid": True,
        "rule_id": None,
        # "outcome": <-- intentionally omitted to fail Contract 11.
        "raw_call": None,
        "contract_version": VERSION,
    }
    # Defensive: confirm poison line really fails Contract 11 so the
    # invariant we're pinning has a real failure mode to guard against.
    assert not validate("validation_event", poisoned).valid

    with log.open("w") as f:
        f.write(json.dumps(valid_events[0]) + "\n")
        f.write(json.dumps(poisoned) + "\n")
        f.write(json.dumps(valid_events[1]) + "\n")
    monkeypatch.setattr(validation_log_tail, "LOG_PATH", log)

    async def run():
        coord = EGSCoordinator(EGSValidationNode())

        def empty_state(egs_state):
            return {
                "egs_state": egs_state,
                "incoming_telemetry": [],
                "incoming_findings": [],
                "incoming_commands": [],
                "messages_to_publish": [],
                "trigger_replan": False,
            }

        last_state = empty_state(build_initial_egs_state("disaster_zone_v1"))
        # Counter goes 1→5 across these 5 ticks; the 5th tick is when
        # (counter % VALIDATION_REFRESH_EVERY_N_TICKS == 0) fires the refresh.
        for _ in range(5):
            last_state = await coord.graph.ainvoke(
                empty_state(last_state["egs_state"]),
            )

        rve = last_state["egs_state"]["recent_validation_events"]
        # Q3 invariant: only the two schema-valid events survived; the
        # poisoned line was filtered by tail()'s validate() gate before
        # ever reaching egs_state.
        assert len(rve) == 2, (
            f"expected 2 events after the 5th-tick refresh (poison line "
            f"filtered), got {len(rve)}: {rve}"
        )
        # Original load-bearing assertion (now reinstated after the
        # Contract 11 -> Contract 3 projection in tail() closed the shape
        # gap): the full envelope must remain Contract 3 schema-valid
        # after the refresh tick fires.
        outcome = validate("egs_state", last_state["egs_state"])
        assert outcome.valid, (
            f"egs_state failed Contract 3 schema validation after the 5-tick "
            f"refresh repopulated recent_validation_events: {outcome.errors}"
        )
        # And the poison line's tell-tale attempt=99 must not appear. The
        # projected entries are in Contract 3 shape so `attempt` is dropped
        # entirely; checking via `.get("attempt")` returns None for every
        # entry, which is correct — the poison value cannot leak through.
        assert all(e.get("attempt") != 99 for e in rve), rve

    asyncio.run(run())
