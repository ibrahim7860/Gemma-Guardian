"""Layer-2 EGS function-call schema round-trip."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.contracts import validate

FIXTURES = Path(__file__).parent.parent / "schemas" / "fixtures"


def _load(p): return json.loads(p.read_text())


@pytest.mark.parametrize(
    "fixture",
    sorted((FIXTURES / "valid" / "egs_function_calls").glob("*.json")),
    ids=lambda p: p.name,
)
def test_valid(fixture):
    outcome = validate("egs_function_calls", _load(fixture))
    assert outcome.valid is True, outcome.errors


@pytest.mark.parametrize(
    "fixture",
    sorted((FIXTURES / "invalid" / "egs_function_calls").glob("*.json")),
    ids=lambda p: p.name,
)
def test_invalid(fixture):
    outcome = validate("egs_function_calls", _load(fixture))
    assert outcome.valid is False
    assert outcome.errors, "rejected payload must report at least one error"
