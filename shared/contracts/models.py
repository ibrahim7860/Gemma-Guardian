"""Pydantic v2 mirrors of every contract schema.

Hand-written, hand-maintained. The JSON Schemas in shared/schemas/ are
authoritative for wire shape. These models exist for ergonomics on the
Python construction side. Parity is enforced by tests in shared/tests/.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

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


# -- Layer 3 -----------------------------------------------------------------

PriorityLevel = Literal["low", "normal", "high", "critical"]


class _RestrictZoneArgs(_StrictModel):
    zone_id: str = Field(min_length=1)


class _ExcludeZoneArgs(_StrictModel):
    zone_id: str = Field(min_length=1)


class _RecallDroneArgs(_StrictModel):
    drone_id: str = Field(pattern=r"^drone\d+$")
    reason: str = Field(min_length=1)


class _SetPriorityArgs(_StrictModel):
    finding_type: FindingType
    priority_level: PriorityLevel


class _SetLanguageArgs(_StrictModel):
    lang_code: str = Field(pattern=r"^[a-z]{2}$")


class _UnknownCommandArgs(_StrictModel):
    operator_text: str = Field(min_length=1)
    suggestion: str = Field(min_length=1)


def _op(name: str, args_cls: type[_StrictModel]) -> type[_StrictModel]:
    class _Op(args_cls):
        def to_call(self) -> dict[str, Any]:
            return {"command": name, "args": self.model_dump()}
    _Op.__name__ = "".join(p.capitalize() for p in name.split("_"))
    return _Op


RestrictZone = _op("restrict_zone", _RestrictZoneArgs)
ExcludeZone = _op("exclude_zone", _ExcludeZoneArgs)
RecallDrone = _op("recall_drone", _RecallDroneArgs)
SetPriority = _op("set_priority", _SetPriorityArgs)
SetLanguage = _op("set_language", _SetLanguageArgs)
UnknownCommand = _op("unknown_command", _UnknownCommandArgs)


_LAYER3_BY_NAME: dict[str, type[_StrictModel]] = {
    "restrict_zone": RestrictZone,
    "exclude_zone": ExcludeZone,
    "recall_drone": RecallDrone,
    "set_priority": SetPriority,
    "set_language": SetLanguage,
    "unknown_command": UnknownCommand,
}


class OperatorCommand:
    @staticmethod
    def parse(payload: dict[str, Any]) -> _StrictModel:
        name = payload.get("command")
        if name not in _LAYER3_BY_NAME:
            raise ValueError(f"unknown operator command: {name!r}")
        return _LAYER3_BY_NAME[name](**payload.get("args", {}))


# -- Contract 2: drone_state --------------------------------------------------

LastAction = Literal[
    "report_finding", "mark_explored", "request_assist",
    "return_to_base", "continue_mission", "none",
]
TaskType = Literal["survey", "investigate_finding", "return_to_base", "hold_position"]
AgentStatus = Literal["active", "standalone", "returning", "offline", "error"]


class _Position3D(_StrictModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    alt: float = Field(ge=0)


class _Velocity3D(_StrictModel):
    vx: float
    vy: float
    vz: float


class DroneStateMessage(_StrictModel):
    drone_id: str = Field(pattern=r"^drone\d+$")
    timestamp: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
    position: _Position3D
    velocity: _Velocity3D
    battery_pct: int = Field(ge=0, le=100)
    heading_deg: float = Field(ge=0, le=360)
    current_task: Optional[TaskType]
    current_waypoint_id: Optional[str]
    assigned_survey_points_remaining: int = Field(ge=0)
    last_action: LastAction
    last_action_timestamp: Optional[str] = Field(
        default=None, pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
    )
    validation_failures_total: int = Field(ge=0)
    findings_count: int = Field(ge=0)
    in_mesh_range_of: List[str]
    agent_status: AgentStatus


# -- Contract 3: egs_state ----------------------------------------------------

MissionStatus = Literal["idle", "active", "paused", "aborted", "complete"]
SurveyPointStatus = Literal["unassigned", "assigned", "completed", "failed"]
FindingsOutcome = Literal["success_first_try", "corrected_after_retry", "failed_after_retries"]


class _SurveyPoint(_StrictModel):
    id: str = Field(min_length=1)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    assigned_to: Optional[str] = Field(default=None, pattern=r"^drone\d+$")
    status: SurveyPointStatus
    priority: Optional[PriorityLevel] = None


class _DroneSummary(_StrictModel):
    status: AgentStatus
    battery: Optional[int] = Field(default=None, ge=0, le=100)


class _FindingsCountByType(_StrictModel):
    victim: int = Field(ge=0)
    fire: int = Field(ge=0)
    smoke: int = Field(ge=0)
    damaged_structure: int = Field(ge=0)
    blocked_route: int = Field(ge=0)


class _RecentValidationEvent(_StrictModel):
    timestamp: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
    agent: str
    task: str = Field(min_length=1)
    outcome: FindingsOutcome
    issue: Optional[str] = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,}$")


class EGSStateMessage(_StrictModel):
    mission_id: str = Field(min_length=1)
    mission_status: MissionStatus
    timestamp: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
    zone_polygon: List[List[float]] = Field(min_length=3)
    survey_points: List[_SurveyPoint]
    drones_summary: Dict[str, _DroneSummary]
    findings_count_by_type: _FindingsCountByType
    recent_validation_events: List[_RecentValidationEvent]
    active_zone_ids: List[str]
