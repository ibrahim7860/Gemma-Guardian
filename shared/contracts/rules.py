"""Stable RuleID enum and human-readable registry.

Every Python validator emits a RuleID in its failure_reason. The registry
maps each ID to its layer, a one-line description, and the corrective
prompt template that gets threaded into the retry per docs/10.

For v1, validators construct corrective prompts inline rather than
using these templates directly. The templates are the canonical
reference for the writeup and serve as docs for future template-driven
prompt assembly. Tests assert templates are well-formed, not that they
match the inline prompts.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Literal


class RuleID(str, Enum):
    # Layer 1 — drone function calls
    PROSE_INSTEAD_OF_FUNCTION = "PROSE_INSTEAD_OF_FUNCTION"
    INVALID_FUNCTION_NAME = "INVALID_FUNCTION_NAME"
    STRUCTURAL_VALIDATION_FAILED = "STRUCTURAL_VALIDATION_FAILED"
    GPS_OUTSIDE_ZONE = "GPS_OUTSIDE_ZONE"
    DUPLICATE_FINDING = "DUPLICATE_FINDING"
    SEVERITY_CONFIDENCE_MISMATCH = "SEVERITY_CONFIDENCE_MISMATCH"
    ZONE_ID_NOT_ASSIGNED = "ZONE_ID_NOT_ASSIGNED"
    COVERAGE_DECREASED = "COVERAGE_DECREASED"
    RTB_LOW_BATTERY_INVALID = "RTB_LOW_BATTERY_INVALID"
    RTB_MISSION_COMPLETE_INVALID = "RTB_MISSION_COMPLETE_INVALID"
    RELATED_FINDING_ID_INVALID = "RELATED_FINDING_ID_INVALID"
    FINDING_ID_FORMAT = "FINDING_ID_FORMAT"
    # Layer 2 — EGS coordinator
    ASSIGNMENT_TOTAL_MISMATCH = "ASSIGNMENT_TOTAL_MISMATCH"
    ASSIGNMENT_DUPLICATE_POINT = "ASSIGNMENT_DUPLICATE_POINT"
    ASSIGNMENT_DRONE_MISSING = "ASSIGNMENT_DRONE_MISSING"
    ASSIGNMENT_UNBALANCED = "ASSIGNMENT_UNBALANCED"
    REPLAN_POLYGON_INVALID = "REPLAN_POLYGON_INVALID"
    REPLAN_EXCLUDED_DRONE_NOT_IN_FLEET = "REPLAN_EXCLUDED_DRONE_NOT_IN_FLEET"
    REPLAN_EXCLUDED_POINT_NOT_IN_PREVIOUS = "REPLAN_EXCLUDED_POINT_NOT_IN_PREVIOUS"
    EGS_DUPLICATE_FINDING = "EGS_DUPLICATE_FINDING"
    # Layer 3 — operator commands
    OPERATOR_COMMAND_UNKNOWN = "OPERATOR_COMMAND_UNKNOWN"
    RECALL_DRONE_NOT_ACTIVE = "RECALL_DRONE_NOT_ACTIVE"
    SET_LANGUAGE_INVALID_CODE = "SET_LANGUAGE_INVALID_CODE"


Layer = Literal["drone", "egs", "operator"]


@dataclass(frozen=True)
class RuleSpec:
    id: RuleID
    layer: Layer
    description: str
    corrective_template: str


def _r(id: RuleID, layer: Layer, description: str, corrective: str) -> RuleSpec:
    return RuleSpec(id=id, layer=layer, description=description, corrective_template=corrective)


RULE_REGISTRY: Dict[RuleID, RuleSpec] = {
    RuleID.PROSE_INSTEAD_OF_FUNCTION: _r(
        RuleID.PROSE_INSTEAD_OF_FUNCTION, "drone",
        "Model returned prose instead of a function call.",
        "You returned prose instead of a function call. You must call exactly one function. The available functions are: report_finding, mark_explored, request_assist, return_to_base, continue_mission.",
    ),
    RuleID.INVALID_FUNCTION_NAME: _r(
        RuleID.INVALID_FUNCTION_NAME, "drone",
        "Function name is not in the allowed set.",
        "You called a function that does not exist. The available functions are: report_finding, mark_explored, request_assist, return_to_base, continue_mission. Call exactly one of these.",
    ),
    RuleID.STRUCTURAL_VALIDATION_FAILED: _r(
        RuleID.STRUCTURAL_VALIDATION_FAILED, "drone",
        "JSON Schema validation failed (type, range, required, additionalProperties).",
        "Your call did not match the required JSON shape at field '{field_path}': {message}. Re-emit the call with the correct shape.",
    ),
    RuleID.GPS_OUTSIDE_ZONE: _r(
        RuleID.GPS_OUTSIDE_ZONE, "drone",
        "Reported finding GPS is outside the drone's assigned zone (50m tolerance).",
        "You reported a finding at GPS ({lat}, {lon}) but your assigned zone bounds are {zone}. The finding must be within your zone. Either correct the coordinates if you mistyped, or use continue_mission() if the target is outside your zone.",
    ),
    RuleID.DUPLICATE_FINDING: _r(
        RuleID.DUPLICATE_FINDING, "drone",
        "Same finding type within 10m and 30s of an existing finding from this drone.",
        "You reported a {type} at this location {seconds_ago} seconds ago. Do not duplicate findings. If this is a different target, describe the difference. Otherwise call continue_mission().",
    ),
    RuleID.SEVERITY_CONFIDENCE_MISMATCH: _r(
        RuleID.SEVERITY_CONFIDENCE_MISMATCH, "drone",
        "severity >= 4 requires confidence >= 0.6.",
        "You reported severity {severity} with confidence {confidence}. For severity 4 or higher, confidence must be >= 0.6. Lower severity, raise confidence with stronger evidence, or call continue_mission().",
    ),
    RuleID.ZONE_ID_NOT_ASSIGNED: _r(
        RuleID.ZONE_ID_NOT_ASSIGNED, "drone",
        "mark_explored zone_id is not in this drone's assigned zones.",
        "You marked exploration for zone {zone_id}, which is not assigned to you. Use one of your assigned zones: {assigned_zones}.",
    ),
    RuleID.COVERAGE_DECREASED: _r(
        RuleID.COVERAGE_DECREASED, "drone",
        "mark_explored coverage_pct is less than the previously reported value.",
        "You reported coverage {coverage}% but previously reported {previous}%. Coverage cannot decrease. Provide a value >= {previous}%.",
    ),
    RuleID.RTB_LOW_BATTERY_INVALID: _r(
        RuleID.RTB_LOW_BATTERY_INVALID, "drone",
        "return_to_base(low_battery) called with battery >= 25%.",
        "You called return_to_base(reason='low_battery') but your battery is {battery}% which is above the 25% threshold. Use a different reason or continue_mission().",
    ),
    RuleID.RTB_MISSION_COMPLETE_INVALID: _r(
        RuleID.RTB_MISSION_COMPLETE_INVALID, "drone",
        "return_to_base(mission_complete) called with survey points pending.",
        "You called return_to_base(reason='mission_complete') but have {pending} survey points pending. Complete them or use a different reason.",
    ),
    RuleID.RELATED_FINDING_ID_INVALID: _r(
        RuleID.RELATED_FINDING_ID_INVALID, "drone",
        "request_assist references a finding_id this drone never reported.",
        "related_finding_id={fid} is not a finding you have reported. Either omit it or reference one of your prior findings.",
    ),
    RuleID.FINDING_ID_FORMAT: _r(
        RuleID.FINDING_ID_FORMAT, "drone",
        "Finding ID does not match the required format ^f_drone\\d+_\\d+$.",
        "finding_id must match the pattern f_<drone_id>_<counter>. Example: f_drone1_047.",
    ),
    RuleID.ASSIGNMENT_TOTAL_MISMATCH: _r(
        RuleID.ASSIGNMENT_TOTAL_MISMATCH, "egs",
        "assign_survey_points: total points assigned != total available points.",
        "Your assignments cover {assigned} points but {total} are available. Reassign so every point is covered exactly once.",
    ),
    RuleID.ASSIGNMENT_DUPLICATE_POINT: _r(
        RuleID.ASSIGNMENT_DUPLICATE_POINT, "egs",
        "Same survey_point_id assigned to two drones.",
        "Survey point {point_id} appears in two drones' lists. Each point must belong to exactly one drone.",
    ),
    RuleID.ASSIGNMENT_DRONE_MISSING: _r(
        RuleID.ASSIGNMENT_DRONE_MISSING, "egs",
        "An active drone (not in excluded_drones) has no assignment entry.",
        "Drone {drone_id} is active but missing from assignments. Add an entry with at least one survey point.",
    ),
    RuleID.ASSIGNMENT_UNBALANCED: _r(
        RuleID.ASSIGNMENT_UNBALANCED, "egs",
        "Per-drone counts differ by more than 1 from the average across non-excluded drones.",
        "Workload is unbalanced: counts {counts}, average {avg}. Redistribute so every non-excluded drone is within +/-1 of the average.",
    ),
    RuleID.REPLAN_POLYGON_INVALID: _r(
        RuleID.REPLAN_POLYGON_INVALID, "egs",
        "replan_mission new_zone_polygon is not a valid simple polygon.",
        "new_zone_polygon must have >=3 points and no self-intersection. Provide a corrected polygon.",
    ),
    RuleID.REPLAN_EXCLUDED_DRONE_NOT_IN_FLEET: _r(
        RuleID.REPLAN_EXCLUDED_DRONE_NOT_IN_FLEET, "egs",
        "excluded_drones contains a drone not in the active fleet.",
        "excluded_drones contains {drone_id}, which is not in the fleet {fleet}. Remove or correct it.",
    ),
    RuleID.REPLAN_EXCLUDED_POINT_NOT_IN_PREVIOUS: _r(
        RuleID.REPLAN_EXCLUDED_POINT_NOT_IN_PREVIOUS, "egs",
        "excluded_survey_points references a point not in the previous assignment.",
        "excluded_survey_points contains {point_id}, which was never assigned. Remove or correct it.",
    ),
    RuleID.EGS_DUPLICATE_FINDING: _r(
        RuleID.EGS_DUPLICATE_FINDING, "egs",
        "Cross-drone duplicate finding within 10m and 30s of one already validated.",
        "Drone {sender} reported a {type} at ({lat},{lon}); drone {prev_sender} reported the same type within 10m and 30s. Dropping as duplicate; first-seen-wins.",
    ),
    RuleID.OPERATOR_COMMAND_UNKNOWN: _r(
        RuleID.OPERATOR_COMMAND_UNKNOWN, "operator",
        "Operator text could not be mapped to a known command.",
        "Operator text {text!r} could not be mapped. Emit unknown_command with a clarifying suggestion.",
    ),
    RuleID.RECALL_DRONE_NOT_ACTIVE: _r(
        RuleID.RECALL_DRONE_NOT_ACTIVE, "operator",
        "recall_drone references a drone that is not in active fleet.",
        "Drone {drone_id} is not active (status={status}). Choose an active drone or omit the command.",
    ),
    RuleID.SET_LANGUAGE_INVALID_CODE: _r(
        RuleID.SET_LANGUAGE_INVALID_CODE, "operator",
        "set_language lang_code is not a valid ISO 639-1 code.",
        "lang_code {code!r} is not ISO 639-1. Use a 2-letter lowercase code such as en, es, ar.",
    ),
}
