"""Validation node — deterministic constraint checks per docs/09 + corrective prompts per docs/10.

Structural checks (types, ranges, required fields, enums, additionalProperties)
are delegated to shared.contracts.schemas. Stateful checks (duplicates, coverage,
GPS-in-zone, RTB battery, RTB mission_complete) stay here. Every failure_reason
is a RuleID enum value.

NO LLM calls in this module.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Optional

from shared.contracts import RuleID, validate as schema_validate

from .perception import PerceptionBundle

DUPLICATE_WINDOW_S = 30.0
DUPLICATE_DISTANCE_M = 10.0
GPS_ZONE_TOLERANCE_M = 50.0


@dataclass
class ValidationResult:
    valid: bool
    failure_reason: Optional[RuleID] = None
    corrective_prompt: Optional[str] = None
    field_path: Optional[str] = None  # populated only for structural failures


@dataclass
class RecentFinding:
    type: str
    lat: float
    lon: float
    timestamp: float


class ValidationNode:
    def __init__(self):
        self.recent_findings: list = []
        self.last_coverage_by_zone: dict = {}

    def validate(self, call: dict, bundle: PerceptionBundle) -> ValidationResult:
        if call is None:
            return ValidationResult(
                valid=False,
                failure_reason=RuleID.PROSE_INSTEAD_OF_FUNCTION,
                corrective_prompt=(
                    "You returned prose instead of a function call. You must call exactly one function. "
                    "Available: report_finding, mark_explored, request_assist, return_to_base, continue_mission."
                ),
            )

        # 1. Structural validation via JSON Schema.
        outcome = schema_validate("drone_function_calls", call)
        if not outcome.valid:
            err = outcome.errors[0]
            # If the discriminator field itself failed, report as INVALID_FUNCTION_NAME
            # so callers receive a more actionable RuleID than the generic structural one.
            if err.field_path == "function":
                return ValidationResult(
                    valid=False,
                    failure_reason=RuleID.INVALID_FUNCTION_NAME,
                    corrective_prompt=(
                        "You called a function that does not exist. The available functions are: "
                        "report_finding, mark_explored, request_assist, return_to_base, continue_mission. "
                        "Call exactly one of these."
                    ),
                    field_path=err.field_path,
                )
            return ValidationResult(
                valid=False,
                failure_reason=RuleID.STRUCTURAL_VALIDATION_FAILED,
                corrective_prompt=(
                    f"Your call did not match the required JSON shape at field '{err.field_path}': {err.message}. "
                    "Re-emit the call with the correct shape."
                ),
                field_path=err.field_path,
            )

        # 2. Stateful / cross-field checks per function name.
        name = call["function"]
        args = call.get("arguments", {})
        method = getattr(self, f"_validate_{name}")
        return method(args, bundle)

    def record_success(self, call: dict, bundle: PerceptionBundle) -> None:
        name = call.get("function")
        args = call.get("arguments") or {}
        if name == "report_finding":
            self.recent_findings.append(RecentFinding(
                type=args["type"],
                lat=float(args["gps_lat"]),
                lon=float(args["gps_lon"]),
                timestamp=time.time(),
            ))
            cutoff = time.time() - DUPLICATE_WINDOW_S * 3
            self.recent_findings = [f for f in self.recent_findings if f.timestamp > cutoff]
        elif name == "mark_explored":
            self.last_coverage_by_zone[args["zone_id"]] = float(args["coverage_pct"])

    def _validate_report_finding(self, args: dict, bundle: PerceptionBundle) -> ValidationResult:
        severity = int(args["severity"])
        confidence = float(args["confidence"])
        lat = float(args["gps_lat"])
        lon = float(args["gps_lon"])
        ftype = args["type"]

        if severity >= 4 and confidence < 0.6:
            return ValidationResult(
                valid=False,
                failure_reason=RuleID.SEVERITY_CONFIDENCE_MISMATCH,
                corrective_prompt=(
                    f"You reported severity {severity} with confidence {confidence}. "
                    "For severity 4 or higher, confidence must be >= 0.6. "
                    "Lower severity, raise confidence with stronger evidence, or use continue_mission()."
                ),
            )

        if not _within_zone(lat, lon, bundle.state.zone_bounds, GPS_ZONE_TOLERANCE_M):
            return ValidationResult(
                valid=False,
                failure_reason=RuleID.GPS_OUTSIDE_ZONE,
                corrective_prompt=(
                    f"You reported a finding at GPS ({lat}, {lon}) but your assigned zone bounds are "
                    f"{bundle.state.zone_bounds}. The finding must be within your zone. "
                    "Either correct the coordinates or use continue_mission()."
                ),
            )

        now = time.time()
        for prev in self.recent_findings:
            if prev.type != ftype:
                continue
            if (now - prev.timestamp) > DUPLICATE_WINDOW_S:
                continue
            if _haversine_m(lat, lon, prev.lat, prev.lon) <= DUPLICATE_DISTANCE_M:
                seconds_ago = int(now - prev.timestamp)
                return ValidationResult(
                    valid=False,
                    failure_reason=RuleID.DUPLICATE_FINDING,
                    corrective_prompt=(
                        f"You reported a {ftype} at this location {seconds_ago} seconds ago. "
                        "Do not duplicate findings. If this is a different target, describe the difference. "
                        "Otherwise call continue_mission()."
                    ),
                )

        return ValidationResult(valid=True)

    def _validate_mark_explored(self, args: dict, bundle: PerceptionBundle) -> ValidationResult:
        zone_id = args["zone_id"]
        coverage = float(args["coverage_pct"])
        prev = self.last_coverage_by_zone.get(zone_id)
        if prev is not None and coverage < prev:
            return ValidationResult(
                valid=False,
                failure_reason=RuleID.COVERAGE_DECREASED,
                corrective_prompt=(
                    f"You reported coverage {coverage}% but previously reported {prev}%. "
                    f"Coverage cannot decrease. Provide a value >= {prev}%."
                ),
            )
        return ValidationResult(valid=True)

    def _validate_request_assist(self, args: dict, bundle: PerceptionBundle) -> ValidationResult:
        # Length and urgency enum already enforced by JSON Schema.
        # related_finding_id format also enforced by JSON Schema; existence-of-finding
        # check requires drone memory and is layered on by reasoning.py.
        return ValidationResult(valid=True)

    def _validate_return_to_base(self, args: dict, bundle: PerceptionBundle) -> ValidationResult:
        reason = args["reason"]
        if reason == "low_battery" and bundle.state.battery_pct >= 25:
            return ValidationResult(
                valid=False,
                failure_reason=RuleID.RTB_LOW_BATTERY_INVALID,
                corrective_prompt=(
                    f"return_to_base(reason='low_battery') but battery is {bundle.state.battery_pct}%. "
                    "Use a different reason or continue_mission()."
                ),
            )
        if reason == "mission_complete" and bundle.state.assigned_survey_points_remaining > 0:
            return ValidationResult(
                valid=False,
                failure_reason=RuleID.RTB_MISSION_COMPLETE_INVALID,
                corrective_prompt=(
                    f"return_to_base(reason='mission_complete') but {bundle.state.assigned_survey_points_remaining} "
                    "survey points still pending. Complete them or use a different reason."
                ),
            )
        return ValidationResult(valid=True)

    def _validate_continue_mission(self, args: dict, bundle: PerceptionBundle) -> ValidationResult:
        return ValidationResult(valid=True)


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _within_zone(lat: float, lon: float, bounds: dict, tolerance_m: float) -> bool:
    if not bounds:
        return True
    if "lat_min" in bounds:
        lat_min, lat_max = bounds["lat_min"], bounds["lat_max"]
        lon_min, lon_max = bounds["lon_min"], bounds["lon_max"]
        deg_tol = tolerance_m / 111_000.0
        return (lat_min - deg_tol) <= lat <= (lat_max + deg_tol) and (lon_min - deg_tol) <= lon <= (lon_max + deg_tol)
    if "polygon" in bounds:
        return _point_in_polygon(lat, lon, bounds["polygon"], tolerance_m)
    return True


def _point_in_polygon(lat: float, lon: float, polygon: list, tolerance_m: float) -> bool:
    if not polygon:
        return True
    deg_tol = tolerance_m / 111_000.0
    inside = False
    n = len(polygon)
    for i in range(n):
        lat1, lon1 = polygon[i]
        lat2, lon2 = polygon[(i + 1) % n]
        if ((lat1 > lat) != (lat2 > lat)) and (
            lon < (lon2 - lon1) * (lat - lat1) / ((lat2 - lat1) or 1e-12) + lon1
        ):
            inside = not inside
    if inside:
        return True
    for i in range(n):
        lat1, lon1 = polygon[i]
        lat2, lon2 = polygon[(i + 1) % n]
        if abs(lat - lat1) <= deg_tol and abs(lon - lon1) <= deg_tol:
            return True
    return False
