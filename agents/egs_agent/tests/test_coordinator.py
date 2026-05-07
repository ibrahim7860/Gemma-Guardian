import asyncio
import logging
import pytest
from unittest.mock import AsyncMock, patch
from agents.egs_agent.validation import EGSValidationNode
from agents.egs_agent.coordinator import EGSCoordinator

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
