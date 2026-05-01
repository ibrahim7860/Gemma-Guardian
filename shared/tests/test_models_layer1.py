"""Pydantic <-> JSON Schema parity for Layer-1 drone function calls."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.contracts import validate
from shared.contracts.models import (
    ContinueMission,
    DroneFunctionCall,
    MarkExplored,
    ReportFinding,
    RequestAssist,
    ReturnToBase,
)

FIXTURES = Path(__file__).parent.parent / "schemas" / "fixtures" / "valid" / "drone_function_calls"

MODEL_BY_FUNCTION = {
    "report_finding": ReportFinding,
    "mark_explored": MarkExplored,
    "request_assist": RequestAssist,
    "return_to_base": ReturnToBase,
    "continue_mission": ContinueMission,
}


def _load(p: Path) -> dict:
    return json.loads(p.read_text())


@pytest.mark.parametrize("fixture", sorted(FIXTURES.glob("*.json")), ids=lambda p: p.name)
def test_pydantic_accepts_what_jsonschema_accepts(fixture):
    payload = _load(fixture)
    model_cls = MODEL_BY_FUNCTION[payload["function"]]
    instance = model_cls(**payload["arguments"])
    rebuilt = {"function": payload["function"], "arguments": instance.model_dump()}
    assert validate("drone_function_calls", rebuilt).valid is True


def test_pydantic_rejects_extra_fields():
    with pytest.raises(ValidationError):
        ReportFinding(
            type="fire",
            severity=2,
            gps_lat=0.0,
            gps_lon=0.0,
            confidence=0.5,
            visual_description="ten characters",
            bonus_field="nope",
        )


def test_dispatcher_picks_correct_branch():
    payload = _load(FIXTURES / "01_report_finding.json")
    parsed = DroneFunctionCall.parse(payload)
    assert isinstance(parsed, ReportFinding)
