"""Phase 4: operator_commands_envelope wraps the operator_command WS frame
for republish onto the egs.operator_commands Redis channel."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.contracts import validate

FIXTURES = Path(__file__).parent.parent / "schemas" / "fixtures"


def _load(rel: str) -> dict:
    return json.loads((FIXTURES / rel).read_text())


def test_valid_recall_envelope():
    payload = _load("valid/operator_commands_envelope/01_recall.json")
    outcome = validate("operator_commands_envelope", payload)
    assert outcome.valid, outcome.errors


def test_missing_raw_text_rejected():
    payload = _load("invalid/operator_commands_envelope/01_missing_raw_text.json")
    outcome = validate("operator_commands_envelope", payload)
    assert not outcome.valid


def test_raw_text_length_cap_enforced():
    payload = _load("invalid/operator_commands_envelope/02_raw_text_too_long.json")
    outcome = validate("operator_commands_envelope", payload)
    assert not outcome.valid


def test_empty_raw_text_rejected():
    """Coverage gap from /plan-eng-review: minLength=1 on raw_text."""
    payload = _load("invalid/operator_commands_envelope/03_empty_raw_text.json")
    outcome = validate("operator_commands_envelope", payload)
    assert not outcome.valid


def test_kind_must_be_operator_command():
    payload = _load("valid/operator_commands_envelope/01_recall.json")
    payload["kind"] = "finding_approval"  # any other discriminator
    outcome = validate("operator_commands_envelope", payload)
    assert not outcome.valid


def test_iso_lang_code_pattern_enforced():
    payload = _load("valid/operator_commands_envelope/01_recall.json")
    payload["language"] = "EN"  # uppercase — must fail [a-z]{2}
    outcome = validate("operator_commands_envelope", payload)
    assert not outcome.valid


def test_command_id_charset_enforced():
    payload = _load("valid/operator_commands_envelope/01_recall.json")
    payload["command_id"] = "abcd; DROP TABLE x"
    outcome = validate("operator_commands_envelope", payload)
    assert not outcome.valid


def test_extra_field_rejected():
    payload = _load("valid/operator_commands_envelope/01_recall.json")
    payload["foo"] = "bar"
    outcome = validate("operator_commands_envelope", payload)
    assert not outcome.valid
