"""Validation node — deterministic constraint checks per docs/09 + corrective prompts per docs/10.

NO LLM calls in this module. The whole point is to catch the LLM with code.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Optional

from .perception import PerceptionBundle

ALLOWED_FUNCTIONS = {
    "report_finding",
    "mark_explored",
    "request_assist",
    "return_to_base",
    "continue_mission",
}

FINDING_TYPES = {"victim", "fire", "smoke", "damaged_structure", "blocked_route"}
URGENCIES = {"low", "medium", "high"}
RTB_REASONS = {"low_battery", "mission_complete", "ordered", "mechanical", "weather"}

DUPLICATE_WINDOW_S = 30.0
DUPLICATE_DISTANCE_M = 10.0
GPS_ZONE_TOLERANCE_M = 50.0


@dataclass
class ValidationResult:
    valid: bool
    failure_reason: Optional[str] = None
    corrective_prompt: Optional[str] = None


@dataclass
class RecentFinding:
    type: str
    lat: float
    lon: float
    timestamp: float


class ValidationNode:
    def __init__(self):
        self.recent_findings: list[RecentFinding] = []
        self.last_coverage_by_zone: dict[str, float] = {}

    def validate(self, call: dict | None, bundle: PerceptionBundle) -> ValidationResult:
        if call is None:
            return ValidationResult(
                valid=False,
                failure_reason="prose_instead_of_function",
                corrective_prompt=(
                    "You returned prose instead of a function call. You must call exactly one function. "
                    "The available functions are: report_finding, mark_explored, request_assist, return_to_base, continue_mission."
                ),
            )

        name = call.get("function")
        args = call.get("arguments") or {}

        if name not in ALLOWED_FUNCTIONS:
            return ValidationResult(
                valid=False,
                failure_reason="invalid_function_name",
                corrective_prompt=(
                    "You called a function that does not exist. The available functions are: "
                    "report_finding, mark_explored, request_assist, return_to_base, continue_mission. "
                    "Call exactly one of these."
                ),
            )

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
        ftype = args.get("type")
        if ftype not in FINDING_TYPES:
            return ValidationResult(False, "invalid_finding_type",
                f"type must be one of {sorted(FINDING_TYPES)}, got {ftype!r}.")

        try:
            severity = int(args.get("severity"))
            confidence = float(args.get("confidence"))
            lat = float(args.get("gps_lat"))
            lon = float(args.get("gps_lon"))
        except (TypeError, ValueError):
            return ValidationResult(False, "invalid_argument_type",
                "severity, confidence, gps_lat, gps_lon must be numeric.")

        if not 1 <= severity <= 5:
            return ValidationResult(False, "severity_out_of_range",
                f"severity must be in [1,5], got {severity}.")
        if not 0.0 <= confidence <= 1.0:
            return ValidationResult(False, "confidence_out_of_range",
                f"confidence must be in [0,1], got {confidence}.")

        desc = args.get("visual_description", "")
        if not isinstance(desc, str) or len(desc.strip()) < 10:
            return ValidationResult(False, "visual_description_too_short",
                "Your visual description was too short or empty. Provide at least 10 characters describing what you see in the image that supports this classification.")

        if severity >= 4 and confidence < 0.6:
            return ValidationResult(False, "severity_confidence_mismatch",
                f"You reported a severity {severity} finding with confidence {confidence}. "
                "For severity 4 or higher, confidence must be at least 0.6. "
                "Either lower the severity or increase confidence with stronger visual evidence, or use continue_mission() if you are uncertain.")

        if not _within_zone(lat, lon, bundle.state.zone_bounds, GPS_ZONE_TOLERANCE_M):
            return ValidationResult(False, "gps_outside_zone",
                f"You reported a finding at GPS ({lat}, {lon}) but your assigned zone bounds are {bundle.state.zone_bounds}. "
                "The finding must be within your zone. Either correct the coordinates if you mistyped, or use continue_mission() if the target is outside your zone.")

        now = time.time()
        for prev in self.recent_findings:
            if prev.type != ftype:
                continue
            if (now - prev.timestamp) > DUPLICATE_WINDOW_S:
                continue
            if _haversine_m(lat, lon, prev.lat, prev.lon) <= DUPLICATE_DISTANCE_M:
                seconds_ago = int(now - prev.timestamp)
                return ValidationResult(False, "duplicate_finding",
                    f"You reported a {ftype} at this location {seconds_ago} seconds ago. "
                    "Do not duplicate findings. If this is a different target, describe the difference. Otherwise call continue_mission().")

        return ValidationResult(True)

    def _validate_mark_explored(self, args: dict, bundle: PerceptionBundle) -> ValidationResult:
        zone_id = args.get("zone_id")
        if not isinstance(zone_id, str) or not zone_id:
            return ValidationResult(False, "invalid_zone_id", "zone_id must be a non-empty string.")

        try:
            coverage = float(args.get("coverage_pct"))
        except (TypeError, ValueError):
            return ValidationResult(False, "invalid_argument_type", "coverage_pct must be numeric.")

        if not 0.0 <= coverage <= 100.0:
            return ValidationResult(False, "coverage_out_of_range",
                f"coverage_pct must be in [0,100], got {coverage}.")

        prev = self.last_coverage_by_zone.get(zone_id)
        if prev is not None and coverage < prev:
            return ValidationResult(False, "coverage_decreased",
                f"You reported coverage of {coverage}% but previously reported {prev}%. "
                f"Coverage cannot decrease. Provide a coverage value greater than or equal to {prev}%.")

        return ValidationResult(True)

    def _validate_request_assist(self, args: dict, bundle: PerceptionBundle) -> ValidationResult:
        reason = args.get("reason", "")
        if not isinstance(reason, str) or len(reason.strip()) < 10:
            return ValidationResult(False, "reason_too_short", "request_assist reason must be at least 10 characters.")

        urgency = args.get("urgency")
        if urgency not in URGENCIES:
            return ValidationResult(False, "invalid_urgency",
                f"urgency must be one of {sorted(URGENCIES)}, got {urgency!r}.")

        return ValidationResult(True)

    def _validate_return_to_base(self, args: dict, bundle: PerceptionBundle) -> ValidationResult:
        reason = args.get("reason")
        if reason not in RTB_REASONS:
            return ValidationResult(False, "invalid_rtb_reason",
                f"reason must be one of {sorted(RTB_REASONS)}, got {reason!r}.")

        if reason == "low_battery" and bundle.state.battery_pct >= 25:
            return ValidationResult(False, "return_to_base_low_battery_invalid",
                f"You called return_to_base(reason=\"low_battery\") but your battery is at {bundle.state.battery_pct}% which is above the 25% threshold. "
                "Use a different reason or continue_mission().")

        if reason == "mission_complete" and bundle.state.assigned_survey_points_remaining > 0:
            return ValidationResult(False, "return_to_base_mission_complete_invalid",
                f"You called return_to_base(reason=\"mission_complete\") but you have {bundle.state.assigned_survey_points_remaining} survey points still pending. "
                "Complete them or use a different reason.")

        return ValidationResult(True)

    def _validate_continue_mission(self, args: dict, bundle: PerceptionBundle) -> ValidationResult:
        return ValidationResult(True)


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
        if ((lat1 > lat) != (lat2 > lat)) and (lon < (lon2 - lon1) * (lat - lat1) / ((lat2 - lat1) or 1e-12) + lon1):
            inside = not inside
    if inside:
        return True
    for i in range(n):
        lat1, lon1 = polygon[i]
        lat2, lon2 = polygon[(i + 1) % n]
        if abs(lat - lat1) <= deg_tol and abs(lon - lon1) <= deg_tol:
            return True
    return False
