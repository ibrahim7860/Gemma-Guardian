"""Pydantic v2 mirrors of every contract schema.

Hand-written, hand-maintained. The JSON Schemas in shared/schemas/ are
authoritative for wire shape. These models exist for ergonomics on the
Python construction side. Parity is enforced by tests in shared/tests/.
"""
from __future__ import annotations

from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# -- Layer 1 -----------------------------------------------------------------

FindingType = Literal["victim", "fire", "smoke", "damaged_structure", "blocked_route"]
Urgency = Literal["low", "medium", "high"]
RTBReason = Literal["low_battery", "mission_complete", "ordered", "mechanical", "weather"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class ReportFindingArgs(_StrictModel):
    type: FindingType
    severity: int = Field(ge=1, le=5)
    gps_lat: float = Field(ge=-90, le=90)
    gps_lon: float = Field(ge=-180, le=180)
    confidence: float = Field(ge=0.0, le=1.0)
    visual_description: str = Field(min_length=10)


class MarkExploredArgs(_StrictModel):
    zone_id: str = Field(min_length=1)
    coverage_pct: float = Field(ge=0.0, le=100.0)


class RequestAssistArgs(_StrictModel):
    reason: str = Field(min_length=10)
    urgency: Urgency
    related_finding_id: Optional[str] = None


class ReturnToBaseArgs(_StrictModel):
    reason: RTBReason


class ContinueMissionArgs(_StrictModel):
    pass


# Convenience flat constructors so call sites can write
# ReportFinding(type=..., severity=...) instead of nesting.
class ReportFinding(ReportFindingArgs):
    def to_call(self) -> dict[str, Any]:
        return {"function": "report_finding", "arguments": self.model_dump()}


class MarkExplored(MarkExploredArgs):
    def to_call(self) -> dict[str, Any]:
        return {"function": "mark_explored", "arguments": self.model_dump()}


class RequestAssist(RequestAssistArgs):
    def to_call(self) -> dict[str, Any]:
        d = self.model_dump(exclude_none=True)
        return {"function": "request_assist", "arguments": d}


class ReturnToBase(ReturnToBaseArgs):
    def to_call(self) -> dict[str, Any]:
        return {"function": "return_to_base", "arguments": self.model_dump()}


class ContinueMission(ContinueMissionArgs):
    def to_call(self) -> dict[str, Any]:
        return {"function": "continue_mission", "arguments": {}}


_LAYER1_BY_NAME: dict[str, type[_StrictModel]] = {
    "report_finding": ReportFinding,
    "mark_explored": MarkExplored,
    "request_assist": RequestAssist,
    "return_to_base": ReturnToBase,
    "continue_mission": ContinueMission,
}


class DroneFunctionCall:
    """Discriminated dispatcher for Layer-1 calls."""

    @staticmethod
    def parse(payload: dict[str, Any]) -> _StrictModel:
        name = payload.get("function")
        if name not in _LAYER1_BY_NAME:
            raise ValueError(f"unknown drone function: {name!r}")
        return _LAYER1_BY_NAME[name](**payload.get("arguments", {}))


# -- Layer 2 -----------------------------------------------------------------

ReplanTrigger = Literal["drone_failure", "zone_change", "operator_command", "fire_spread"]


class _AssignmentItem(_StrictModel):
    drone_id: str = Field(pattern=r"^drone\d+$")
    survey_point_ids: List[str]


class AssignSurveyPointsArgs(_StrictModel):
    assignments: List[_AssignmentItem] = Field(min_length=1)


class ReplanMissionArgs(_StrictModel):
    trigger: ReplanTrigger
    new_zone_polygon: List[List[float]] = Field(min_length=3)
    excluded_drones: List[str]
    excluded_survey_points: List[str]


class AssignSurveyPoints(AssignSurveyPointsArgs):
    def to_call(self) -> dict[str, Any]:
        return {"function": "assign_survey_points", "arguments": self.model_dump()}


class ReplanMission(ReplanMissionArgs):
    def to_call(self) -> dict[str, Any]:
        return {"function": "replan_mission", "arguments": self.model_dump()}


_LAYER2_BY_NAME: dict[str, type[_StrictModel]] = {
    "assign_survey_points": AssignSurveyPoints,
    "replan_mission": ReplanMission,
}


class EGSFunctionCall:
    @staticmethod
    def parse(payload: dict[str, Any]) -> _StrictModel:
        name = payload.get("function")
        if name not in _LAYER2_BY_NAME:
            raise ValueError(f"unknown EGS function: {name!r}")
        return _LAYER2_BY_NAME[name](**payload.get("arguments", {}))
