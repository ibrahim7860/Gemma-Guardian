import asyncio
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
