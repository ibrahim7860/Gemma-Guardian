"""Contract 4 (finding) schema round-trip."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.contracts import validate

FIXTURES = Path(__file__).parent.parent / "schemas" / "fixtures"


def _load(p): return json.loads(p.read_text())


@pytest.mark.parametrize(
    "fixture",
    sorted((FIXTURES / "valid" / "finding").glob("*.json")),
    ids=lambda p: p.name,
)
def test_valid(fixture):
    outcome = validate("finding", _load(fixture))
    assert outcome.valid is True, outcome.errors


@pytest.mark.parametrize(
    "fixture",
    sorted((FIXTURES / "invalid" / "finding").glob("*.json")),
    ids=lambda p: p.name,
)
def test_invalid(fixture):
    outcome = validate("finding", _load(fixture))
    assert outcome.valid is False
    assert outcome.errors, "rejected payload must report at least one error"
