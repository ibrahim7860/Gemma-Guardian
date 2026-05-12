"""Pydantic unit tests for ReplanAttempt (Phase 1, GATE 4 wow moment).

Five cases per the plan:
 1. accepts valid minimal shape (timestamp, attempt_n, valid)
 2. accepts full shape with rule_id + corrective_text + details
 3. rejects attempt_n=0 (must be >=1)
 4. rejects malformed timestamp (existing pattern guard)
 5. rejects extra fields (_StrictModel parent enforces extra="forbid")
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.contracts import ReplanAttempt


def test_accepts_minimal_shape():
    """Smallest valid shape: only timestamp, attempt_n, valid.
    rule_id, corrective_text default to None; details defaults to {}.
    """
    attempt = ReplanAttempt(
        timestamp="2026-05-12T14:23:11.342Z",
        attempt_n=1,
        valid=False,
    )
    assert attempt.attempt_n == 1
    assert attempt.valid is False
    assert attempt.rule_id is None
    assert attempt.corrective_text is None
    assert attempt.details == {}


def test_accepts_full_shape_with_rule_id_and_corrective_text():
    """Full populated shape — the wow-moment camera path."""
    attempt = ReplanAttempt(
        timestamp="2026-05-12T14:23:11.342Z",
        attempt_n=1,
        valid=False,
        rule_id="ASSIGNMENT_TOTAL_MISMATCH",
        corrective_text=(
            "Your assignments cover 27 points but 25 are available. "
            "Reassign so every point is covered exactly once."
        ),
        details={"assigned": 27, "total": 25},
    )
    assert attempt.rule_id == "ASSIGNMENT_TOTAL_MISMATCH"
    assert "27 points but 25" in attempt.corrective_text
    assert attempt.details == {"assigned": 27, "total": 25}


def test_rejects_attempt_n_zero():
    """attempt_n must be 1-indexed; 0 violates ge=1."""
    with pytest.raises(ValidationError) as exc_info:
        ReplanAttempt(
            timestamp="2026-05-12T14:23:11.342Z",
            attempt_n=0,
            valid=True,
        )
    assert "attempt_n" in str(exc_info.value)


def test_rejects_malformed_timestamp():
    """Pattern is iso_timestamp_utc_ms shape — same guard as
    _RecentValidationEvent. Missing the milliseconds suffix is a typical
    mistake from hand-rolled timestamps.
    """
    with pytest.raises(ValidationError):
        ReplanAttempt(
            timestamp="2026-05-12T14:23:11Z",  # no .ddd before Z
            attempt_n=1,
            valid=True,
        )


def test_rejects_extra_fields():
    """_StrictModel sets extra='forbid'. Any unknown property must raise.
    Defends against contract drift where a future EGS field accidentally
    leaks into the per-attempt record.
    """
    with pytest.raises(ValidationError) as exc_info:
        ReplanAttempt(
            timestamp="2026-05-12T14:23:11.342Z",
            attempt_n=1,
            valid=True,
            future_unknown_field="should_not_be_allowed",
        )
    assert "future_unknown_field" in str(exc_info.value) or "extra" in str(exc_info.value).lower()
