import asyncio
import json
import logging
import pytest
from unittest.mock import AsyncMock, patch

from agents.egs_agent import validation_log_tail
from agents.egs_agent.coordinator import EGSCoordinator
from agents.egs_agent.scenario_state import build_initial_egs_state
from agents.egs_agent.validation import EGSValidationNode
from shared.contracts import VERSION

@pytest.fixture
def coordinator():
    validation_node = EGSValidationNode()
    return EGSCoordinator(validation_node)

def test_coordinator_telemetry_offline_triggers_replan(coordinator):
    state = {
        "egs_state": {
            "drones_summary": {"drone1": {"status": "active"}}
        },
        "incoming_telemetry": [
            {"drone_id": "drone1", "agent_status": "offline", "battery_pct": 0, "timestamp": "now"}
        ],
        "incoming_findings": [],
        "incoming_commands": [],
        "messages_to_publish": [],
        "trigger_replan": False
    }
    
    # Run just the process_telemetry node
    new_state = coordinator.process_telemetry(state)
    assert new_state["trigger_replan"] is True
    assert new_state["egs_state"]["drones_summary"]["drone1"]["status"] == "offline"

def test_coordinator_process_findings_aggregates(coordinator):
    state = {
        "egs_state": {},
        "incoming_telemetry": [],
        "incoming_findings": [
            {
                "finding_id": "f_drone1_001",
                "source_drone_id": "drone1",
                "type": "victim",
                "gps_lat": 34.0,
                "gps_lon": -118.0,
                "timestamp": "2026-05-15T14:00:00.000Z"
            }
        ],
        "incoming_commands": [],
        "messages_to_publish": [],
        "trigger_replan": False
    }
    
    new_state = coordinator.process_findings(state)
    assert new_state["egs_state"]["findings_count_by_type"]["victim"] == 1
    
def test_coordinator_process_commands_restrict_zone_triggers_replan(coordinator):
    async def run_test():
        state = {
            "egs_state": {},
            "incoming_telemetry": [],
            "incoming_findings": [],
            "incoming_commands": [
                {"raw_text": "focus on zone A", "language": "en", "command_id": "c1"}
            ],
            "messages_to_publish": [],
            "trigger_replan": False
        }
        
        mock_translate = AsyncMock()
        mock_translate.return_value = {
            "valid": True,
            "structured": {"command": "restrict_zone", "args": {"zone_id": "zone_A"}}
        }
        
        with patch("agents.egs_agent.coordinator.translate_operator_command", new=mock_translate):
            new_state = await coordinator.process_commands(state)
            assert new_state["trigger_replan"] is True
            assert len(new_state["messages_to_publish"]) == 1
            assert new_state["messages_to_publish"][0]["data"]["command_id"] == "c1"

    asyncio.run(run_test())


def test_process_findings_logs_accepted_count(coordinator, caplog):
    """Task 5: accepted findings emit a structured INFO line for live debugging."""
    finding = {
        "finding_id": "f_drone1_001",
        "source_drone_id": "drone1",
        "timestamp": "2026-05-07T10:00:00.000Z",
        "type": "victim",
        "severity": 3,
        "gps_lat": 34.0028,
        "gps_lon": -118.5000,
        "altitude": 25.0,
        "confidence": 0.85,
        "visual_description": "Test fixture finding for integration coverage.",
        "image_path": "/tmp/findings/test.jpg",
        "validated": True,
        "validation_retries": 0,
        "operator_status": "pending",
    }
    state = {
        "egs_state": {},
        "incoming_telemetry": [],
        "incoming_findings": [finding],
        "incoming_commands": [],
        "messages_to_publish": [],
        "trigger_replan": False,
    }

    with caplog.at_level(logging.INFO, logger="agents.egs_agent.coordinator"):
        new_state = coordinator.process_findings(state)

    assert new_state["egs_state"]["findings_count_by_type"]["victim"] == 1
    accepted_records = [r for r in caplog.records if "egs.findings accepted" in r.getMessage()]
    assert len(accepted_records) == 1, [r.getMessage() for r in caplog.records]
    msg = accepted_records[0].getMessage()
    assert "source=drone1" in msg
    assert "type=victim" in msg
    assert "total_victim=1" in msg


def test_process_findings_increments_only_known_types(coordinator, caplog):
    """Task 5: unknown finding types are silently dropped (no count change, no
    accepted log line). The accepted log lives inside the `ftype in counts`
    branch so it never fires for unknown types."""
    finding = {
        "finding_id": "f_drone1_002",
        "source_drone_id": "drone1",
        "timestamp": "2026-05-07T10:00:01.000Z",
        "type": "unknown_thing",
        "severity": 1,
        "gps_lat": 34.0028,
        "gps_lon": -118.5000,
        "altitude": 25.0,
        "confidence": 0.5,
        "visual_description": "Unknown finding type to verify it's silently dropped.",
        "image_path": "/tmp/findings/test.jpg",
        "validated": True,
        "validation_retries": 0,
        "operator_status": "pending",
    }
    state = {
        "egs_state": {},
        "incoming_telemetry": [],
        "incoming_findings": [finding],
        "incoming_commands": [],
        "messages_to_publish": [],
        "trigger_replan": False,
    }

    with caplog.at_level(logging.INFO, logger="agents.egs_agent.coordinator"):
        new_state = coordinator.process_findings(state)

    counts = new_state["egs_state"]["findings_count_by_type"]
    assert counts == {
        "victim": 0, "fire": 0, "smoke": 0,
        "damaged_structure": 0, "blocked_route": 0,
    }
    accepted_records = [r for r in caplog.records if "egs.findings accepted" in r.getMessage()]
    assert accepted_records == [], (
        f"unknown finding type should not emit an accepted log line, got: "
        f"{[r.getMessage() for r in accepted_records]}"
    )


def _validation_event(attempt: int, ts: str):
    """Hand-rolled schema-valid validation_event payload for coordinator tests.

    Uses a per-attempt `function_or_command` so coordinator tests can pin
    refresh ordering on the projected Contract 3 `task` field (since the
    Contract 11 `attempt` field is dropped during projection in tail()).
    """
    return {
        "timestamp": ts,
        "agent_id": "drone1",
        "layer": "drone",
        "function_or_command": f"task_{attempt:02d}",
        "attempt": attempt,
        "valid": True,
        "rule_id": None,
        "outcome": "success_first_try",
        "raw_call": None,
        "contract_version": VERSION,
    }


def _empty_state(egs_state):
    return {
        "egs_state": egs_state,
        "incoming_telemetry": [],
        "incoming_findings": [],
        "incoming_commands": [],
        "messages_to_publish": [],
        "trigger_replan": False,
    }


def test_coordinator_refreshes_recent_validation_events(tmp_path, monkeypatch):
    """Task 4: after VALIDATION_REFRESH_EVERY_N_TICKS=5 invocations of the
    graph, recent_validation_events should reflect the on-disk JSONL log."""
    # Seed a 3-event log file and point the tail module at it.
    log = tmp_path / "validation_events.jsonl"
    events = [
        _validation_event(i, f"2026-05-07T10:00:{i:02d}.000Z")
        for i in range(1, 4)
    ]
    with log.open("w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    monkeypatch.setattr(validation_log_tail, "LOG_PATH", log)

    async def run():
        coord = EGSCoordinator(EGSValidationNode())
        state = _empty_state(build_initial_egs_state("disaster_zone_v1"))
        # The on-disk log has 3 entries; the field starts empty.
        assert state["egs_state"]["recent_validation_events"] == []

        # Run the graph 5 times sequentially. Counter goes 1→5; the 5th tick
        # is when (counter % 5 == 0) fires the refresh.
        last_state = state
        for _ in range(5):
            last_state = await coord.graph.ainvoke(_empty_state(last_state["egs_state"]))

        rve = last_state["egs_state"]["recent_validation_events"]
        assert len(rve) == 3, (
            f"expected 3 events after 5 ticks, got {len(rve)}: {rve}"
        )
        # tail() returns Contract 3 nested shape: {timestamp, agent, task,
        # outcome, issue}. Pin order on the projected `task` field.
        assert [e["task"] for e in rve] == ["task_01", "task_02", "task_03"]

    asyncio.run(run())


def test_coordinator_does_not_refresh_on_off_ticks(tmp_path, monkeypatch):
    """Task 4: the every-5th-tick gate must hold off the refresh on ticks 1-4."""
    log = tmp_path / "validation_events.jsonl"
    events = [
        _validation_event(i, f"2026-05-07T10:00:{i:02d}.000Z")
        for i in range(1, 4)
    ]
    with log.open("w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    monkeypatch.setattr(validation_log_tail, "LOG_PATH", log)

    async def run():
        coord = EGSCoordinator(EGSValidationNode())
        state = _empty_state(build_initial_egs_state("disaster_zone_v1"))

        last_state = state
        for _ in range(4):  # only 4 ticks — short of the 5-tick gate
            last_state = await coord.graph.ainvoke(_empty_state(last_state["egs_state"]))

        rve = last_state["egs_state"]["recent_validation_events"]
        assert rve == [], (
            f"refresh should not fire on ticks 1-4; got {rve}"
        )

    asyncio.run(run())


def test_process_telemetry_drones_summary_passes_egs_state_schema():
    """Regression: drones_summary entries must conform to Contract 3
    (`{status, battery}` with `additionalProperties: false`). A pre-existing
    bug wrote `last_seen` into the entry, breaking every `egs.state`
    publish. Surfaced by the 2026-05-07 GATE 2 live smoke run.
    """
    from agents.egs_agent.scenario_state import build_initial_egs_state
    from shared.contracts import validate

    coord = EGSCoordinator(EGSValidationNode())
    state = {
        "egs_state": build_initial_egs_state("disaster_zone_v1"),
        "incoming_telemetry": [
            {
                "drone_id": "drone1",
                "agent_status": "active",
                "battery_pct": 87,
                "timestamp": "2026-05-07T16:00:00.000Z",
            }
        ],
        "incoming_findings": [],
        "incoming_commands": [],
        "messages_to_publish": [],
        "trigger_replan": False,
    }
    new_state = coord.process_telemetry(state)
    assert "drone1" in new_state["egs_state"]["drones_summary"]
    entry = new_state["egs_state"]["drones_summary"]["drone1"]
    assert set(entry.keys()) == {"status", "battery"}
    outcome = validate("egs_state", new_state["egs_state"])
    assert outcome.valid, outcome.errors
