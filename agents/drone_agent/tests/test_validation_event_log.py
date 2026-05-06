"""Validation event log must conform to Contract 11 (shared/schemas/validation_event.json)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.drone_agent.main import DroneAgent
from agents.drone_agent.perception import DroneState, PerceptionBundle
from shared.contracts import validate


@pytest.fixture
def tmp_log_path(tmp_path, monkeypatch):
    log = tmp_path / "validation_events.jsonl"
    monkeypatch.setattr(
        "agents.drone_agent.main.VALIDATION_LOG_PATH", log
    )
    return log


@pytest.mark.asyncio
async def test_first_try_success_logs_contract_11_record(tmp_log_path):
    agent = DroneAgent(drone_id="drone1")
    agent.reasoning.call = AsyncMock(return_value={
        "message": {
            "tool_calls": [{
                "function": {
                    "name": "continue_mission",
                    "arguments": "{}",
                },
            }],
        },
    })
    state = DroneState(
        drone_id="drone1", lat=34.0, lon=-118.5, alt=25.0,
        battery_pct=87.0, heading_deg=0.0, current_task="survey",
        assigned_survey_points_remaining=5,
        zone_bounds={"lat_min": 33.99, "lat_max": 34.01,
                     "lon_min": -118.51, "lon_max": -118.49},
    )
    bundle = PerceptionBundle(frame_jpeg=b"\xff\xd8\xff\xd9", state=state)
    await agent.step(bundle)

    lines = tmp_log_path.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    outcome = validate("validation_event", record)
    assert outcome.valid, outcome.errors
    assert record["agent_id"] == "drone1"
    assert record["layer"] == "drone"
    assert record["function_or_command"] == "continue_mission"
    assert record["attempt"] == 1
    assert record["valid"] is True
    assert record["outcome"] == "success_first_try"
    assert record["rule_id"] is None


@pytest.mark.asyncio
async def test_corrected_after_retry_logs_in_progress_then_corrected(tmp_log_path):
    agent = DroneAgent(drone_id="drone1")
    bad = {
        "message": {
            "tool_calls": [{
                "function": {
                    "name": "report_finding",
                    "arguments": json.dumps({
                        "type": "victim", "severity": 5, "gps_lat": 34.0,
                        "gps_lon": -118.5, "confidence": 0.3,
                        "visual_description": "person prone in rubble",
                    }),
                },
            }],
        },
    }
    good = {
        "message": {
            "tool_calls": [{
                "function": {
                    "name": "continue_mission",
                    "arguments": "{}",
                },
            }],
        },
    }
    agent.reasoning.call = AsyncMock(side_effect=[bad, good])
    state = DroneState(
        drone_id="drone1", lat=34.0, lon=-118.5, alt=25.0,
        battery_pct=87.0, heading_deg=0.0, current_task="survey",
        assigned_survey_points_remaining=5,
        zone_bounds={"lat_min": 33.99, "lat_max": 34.01,
                     "lon_min": -118.51, "lon_max": -118.49},
    )
    bundle = PerceptionBundle(frame_jpeg=b"\xff\xd8\xff\xd9", state=state)
    await agent.step(bundle)

    lines = tmp_log_path.read_text().strip().splitlines()
    assert len(lines) == 2
    rec1 = json.loads(lines[0])
    rec2 = json.loads(lines[1])
    assert rec1["valid"] is False
    assert rec1["outcome"] == "in_progress"
    assert rec1["rule_id"] == "SEVERITY_CONFIDENCE_MISMATCH"
    assert rec1["attempt"] == 1
    assert rec2["valid"] is True
    assert rec2["outcome"] == "corrected_after_retry"
    assert rec2["attempt"] == 2


@pytest.mark.asyncio
async def test_failed_after_retries_logs_terminal_record(tmp_log_path):
    """Eng-review test gap: max_retries exhausted writes a failed_after_retries record."""
    agent = DroneAgent(drone_id="drone1", max_retries=2)
    bad = {
        "message": {
            "tool_calls": [{
                "function": {
                    "name": "report_finding",
                    "arguments": json.dumps({
                        "type": "victim", "severity": 5, "gps_lat": 34.0,
                        "gps_lon": -118.5, "confidence": 0.3,
                        "visual_description": "person prone in rubble",
                    }),
                },
            }],
        },
    }
    agent.reasoning.call = AsyncMock(side_effect=[bad, bad])
    state = DroneState(
        drone_id="drone1", lat=34.0, lon=-118.5, alt=25.0,
        battery_pct=87.0, heading_deg=0.0, current_task="survey",
        assigned_survey_points_remaining=5,
        zone_bounds={"lat_min": 33.99, "lat_max": 34.01,
                     "lon_min": -118.51, "lon_max": -118.49},
    )
    bundle = PerceptionBundle(frame_jpeg=b"\xff\xd8\xff\xd9", state=state)
    result = await agent.step(bundle)
    assert result == {"function": "continue_mission", "arguments": {}}

    lines = tmp_log_path.read_text().strip().splitlines()
    assert len(lines) == 3
    rec_terminal = json.loads(lines[2])
    outcome = validate("validation_event", rec_terminal)
    assert outcome.valid, outcome.errors
    assert rec_terminal["outcome"] == "failed_after_retries"
    assert rec_terminal["valid"] is False
    assert rec_terminal["attempt"] == 2  # max_retries
