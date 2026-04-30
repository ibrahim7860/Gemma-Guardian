"""Shared integration contracts for FieldAgent v1.

Source of truth: docs/superpowers/specs/2026-04-30-integration-contracts-design.md
Wire schemas live at shared/schemas/*.json. This package loads them and exposes
runtime validators, Pydantic mirrors, the RuleID enum, and the topic registry.
"""
from pathlib import Path

VERSION = (Path(__file__).parent.parent / "VERSION").read_text().strip()

from .schemas import (
    ContractError,
    StructuralError,
    ValidationOutcome,
    all_schemas,
    schema,
    validate,
    validate_or_raise,
)

__all__ = [
    "VERSION",
    "ContractError",
    "StructuralError",
    "ValidationOutcome",
    "all_schemas",
    "schema",
    "validate",
    "validate_or_raise",
]

from .models import (
    ContinueMission,
    DroneFunctionCall,
    MarkExplored,
    ReportFinding,
    RequestAssist,
    ReturnToBase,
)

__all__ += [
    "ContinueMission",
    "DroneFunctionCall",
    "MarkExplored",
    "ReportFinding",
    "RequestAssist",
    "ReturnToBase",
]

from .models import AssignSurveyPoints, EGSFunctionCall, ReplanMission

__all__ += ["AssignSurveyPoints", "EGSFunctionCall", "ReplanMission"]

from .models import (
    ExcludeZone,
    OperatorCommand,
    RecallDrone,
    RestrictZone,
    SetLanguage,
    SetPriority,
    UnknownCommand,
)

__all__ += [
    "ExcludeZone",
    "OperatorCommand",
    "RecallDrone",
    "RestrictZone",
    "SetLanguage",
    "SetPriority",
    "UnknownCommand",
]

from .models import DroneStateMessage

__all__ += ["DroneStateMessage"]

from .models import EGSStateMessage

__all__ += ["EGSStateMessage"]

from .models import Finding

__all__ += ["Finding"]

from .models import TaskAssignment

__all__ += ["TaskAssignment"]

from .models import PeerBroadcast

__all__ += ["PeerBroadcast"]

from .models import (
    CommandTranslationMessage,
    FindingApprovalMessage,
    OperatorCommandDispatchMessage,
    OperatorCommandMessage,
    StateUpdateMessage,
    WebSocketMessage,
)

__all__ += [
    "CommandTranslationMessage",
    "FindingApprovalMessage",
    "OperatorCommandDispatchMessage",
    "OperatorCommandMessage",
    "StateUpdateMessage",
    "WebSocketMessage",
]

from .models import ValidationEvent

__all__ += ["ValidationEvent"]

from .rules import RULE_REGISTRY, RuleID, RuleSpec

__all__ += ["RULE_REGISTRY", "RuleID", "RuleSpec"]

from .adapters import AdapterError, normalize

__all__ += ["AdapterError", "normalize"]

from . import topics

__all__ += ["topics"]

from .config import CONFIG, FieldAgentConfig, load_config

__all__ += ["CONFIG", "FieldAgentConfig", "load_config"]
