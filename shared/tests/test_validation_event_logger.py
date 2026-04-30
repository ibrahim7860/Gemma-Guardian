"""ValidationEventLogger writes schema-valid JSONL records."""
from __future__ import annotations

import json

from shared.contracts import validate
from shared.contracts.logging import ValidationEventLogger


def test_logger_writes_schema_valid_lines(tmp_path):
    log_path = tmp_path / "validation_events.jsonl"
    logger = ValidationEventLogger(log_path)
    logger.log(
        agent_id="drone1",
        layer="drone",
        function_or_command="report_finding",
        attempt=1,
        valid=False,
        rule_id="DUPLICATE_FINDING",
        outcome="corrected_after_retry",
        raw_call={"function": "report_finding", "arguments": {}},
    )
    lines = log_path.read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert validate("validation_event", record).valid is True


def test_logger_appends(tmp_path):
    log_path = tmp_path / "validation_events.jsonl"
    logger = ValidationEventLogger(log_path)
    for i in range(3):
        logger.log(
            agent_id="drone1", layer="drone",
            function_or_command="continue_mission",
            attempt=i + 1, valid=True, rule_id=None,
            outcome="success_first_try", raw_call=None,
        )
    assert len(log_path.read_text().splitlines()) == 3


def test_logger_creates_parent_directory(tmp_path):
    nested = tmp_path / "deep" / "nested" / "events.jsonl"
    logger = ValidationEventLogger(nested)
    logger.log(
        agent_id="egs", layer="egs",
        function_or_command="assign_survey_points",
        attempt=1, valid=True, rule_id=None,
        outcome="success_first_try", raw_call=None,
    )
    assert nested.exists()


def test_logger_records_egs_agent_id(tmp_path):
    """agent_id="egs" is a valid value per the schema (oneOf drone_id | const "egs")."""
    log_path = tmp_path / "events.jsonl"
    logger = ValidationEventLogger(log_path)
    logger.log(
        agent_id="egs", layer="egs",
        function_or_command="replan_mission",
        attempt=1, valid=False, rule_id="REPLAN_POLYGON_INVALID",
        outcome="failed_after_retries", raw_call=None,
    )
    record = json.loads(log_path.read_text().splitlines()[0])
    assert validate("validation_event", record).valid is True
    assert record["agent_id"] == "egs"
