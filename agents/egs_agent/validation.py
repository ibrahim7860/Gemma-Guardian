"""EGS-side validation node.

Layer-2 (EGS function calls) and Layer-3 (operator commands) structural
validation goes through shared.contracts. The cross-drone duplicate-finding
rule (EGS_DUPLICATE_FINDING) lives here because it requires an EGS-wide
view of recently accepted findings.

This module is the thin contracts plan stub. Qasim builds coordinator.py,
command_translator.py, and replanning.py on top.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from shared.contracts import RuleID, validate as schema_validate

DUPLICATE_WINDOW_S = 30.0
DUPLICATE_DISTANCE_M = 10.0


@dataclass
class ValidationResult:
    valid: bool
    failure_reason: Optional[RuleID] = None
    detail: Optional[str] = None


@dataclass
class _AcceptedFinding:
    source_drone_id: str
    type: str
    lat: float
    lon: float
    timestamp_s: float


def _parse_iso(ts: str) -> float:
    """Parse an ISO 8601 UTC timestamp like '2026-05-15T14:00:00.000Z' to epoch seconds."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


class EGSValidationNode:
    def __init__(self):
        self._accepted: list = []

    def validate_finding(self, finding: dict) -> ValidationResult:
        """Cross-drone dedup: first-seen-wins within 10m and 30s of an existing
        accepted finding from a *different* drone. Same-drone duplicates are
        the drone-side validator's responsibility (RuleID.DUPLICATE_FINDING).
        """
        ts = _parse_iso(finding["timestamp"])
        cutoff = ts - DUPLICATE_WINDOW_S
        # Trim accepted findings older than the dedup window so the list stays bounded.
        self._accepted = [f for f in self._accepted if f.timestamp_s >= cutoff]

        for prev in self._accepted:
            if prev.source_drone_id == finding["source_drone_id"]:
                continue
            if prev.type != finding["type"]:
                continue
            if (ts - prev.timestamp_s) > DUPLICATE_WINDOW_S:
                continue
            d = _haversine_m(prev.lat, prev.lon, finding["gps_lat"], finding["gps_lon"])
            if d <= DUPLICATE_DISTANCE_M:
                return ValidationResult(
                    valid=False,
                    failure_reason=RuleID.EGS_DUPLICATE_FINDING,
                    detail=(
                        f"{finding['source_drone_id']} reported {finding['type']} at "
                        f"({finding['gps_lat']},{finding['gps_lon']}); "
                        f"{prev.source_drone_id} reported the same type within 10m and 30s. "
                        "Dropping; first-seen-wins."
                    ),
                )

        # Accept and remember.
        self._accepted.append(_AcceptedFinding(
            source_drone_id=finding["source_drone_id"],
            type=finding["type"],
            lat=finding["gps_lat"],
            lon=finding["gps_lon"],
            timestamp_s=ts,
        ))
        return ValidationResult(valid=True)

    def validate_egs_function_call(self, call: dict) -> ValidationResult:
        """Layer-2 structural delegation. Stateful checks (assignment balance,
        replan polygon, etc.) belong to Qasim's coordinator.py."""
        outcome = schema_validate("egs_function_calls", call)
        if not outcome.valid:
            return ValidationResult(
                valid=False,
                failure_reason=RuleID.STRUCTURAL_VALIDATION_FAILED,
                detail=outcome.errors[0].message,
            )
        return ValidationResult(valid=True)

    def validate_operator_command(self, command: dict) -> ValidationResult:
        """Layer-3 structural delegation. Stateful checks (recall_drone_not_active,
        etc.) belong to Qasim's command_translator.py."""
        outcome = schema_validate("operator_commands", command)
        if not outcome.valid:
            return ValidationResult(
                valid=False,
                failure_reason=RuleID.STRUCTURAL_VALIDATION_FAILED,
                detail=outcome.errors[0].message,
            )
        return ValidationResult(valid=True)
