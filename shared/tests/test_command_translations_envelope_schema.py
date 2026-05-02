"""Phase 4: command_translations_envelope wraps EGS Gemma 4 E4B output for
republish onto the egs.command_translations Redis channel.

The `structured` field embeds operator_commands.json so the discriminated
oneOf there is type-checked here too."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.contracts import validate

FIXTURES = Path(__file__).parent.parent / "schemas" / "fixtures"


def _load(rel: str) -> dict:
    return json.loads((FIXTURES / rel).read_text())


def test_valid_recall_translation():
    payload = _load("valid/command_translations_envelope/01_recall.json")
    outcome = validate("command_translations_envelope", payload)
    assert outcome.valid, outcome.errors


def test_valid_unknown_command_translation():
    """unknown_command branch carries valid:false but the envelope itself must
    still validate so the bridge forwards it to Flutter."""
    payload = _load("valid/command_translations_envelope/02_unknown_command.json")
    outcome = validate("command_translations_envelope", payload)
    assert outcome.valid, outcome.errors


def test_missing_preview_rejected():
    payload = _load("invalid/command_translations_envelope/01_missing_preview.json")
    outcome = validate("command_translations_envelope", payload)
    assert not outcome.valid


def test_invalid_structured_payload_rejected():
    """Coverage gap from /plan-eng-review: structured must validate against
    operator_commands.json — a fabricated command name must be rejected."""
    payload = _load("invalid/command_translations_envelope/02_invalid_structured.json")
    outcome = validate("command_translations_envelope", payload)
    assert not outcome.valid


def test_kind_must_be_command_translation():
    payload = _load("valid/command_translations_envelope/01_recall.json")
    payload["kind"] = "operator_command"
    outcome = validate("command_translations_envelope", payload)
    assert not outcome.valid


def test_preview_text_length_cap():
    payload = _load("valid/command_translations_envelope/01_recall.json")
    payload["preview_text"] = "x" * 1025
    outcome = validate("command_translations_envelope", payload)
    assert not outcome.valid


def test_extra_field_rejected():
    payload = _load("valid/command_translations_envelope/01_recall.json")
    payload["foo"] = "bar"
    outcome = validate("command_translations_envelope", payload)
    assert not outcome.valid


def test_valid_true_with_unknown_command_rejected():
    """Adversarial finding #2: valid=true + command=unknown_command is a
    logical contradiction. Schema must reject it via if/then constraint."""
    payload = {
        "kind": "command_translation",
        "command_id": "abcd-1700000000000-3",
        "structured": {
            "command": "unknown_command",
            "args": {"operator_text": "asdf", "suggestion": "Try ..."},
        },
        "valid": True,  # contradicts unknown_command
        "preview_text": "x",
        "preview_text_in_operator_language": "x",
        "egs_published_at_iso_ms": "2026-05-02T12:34:57.123Z",
        "contract_version": "1.0.0",
    }
    outcome = validate("command_translations_envelope", payload)
    assert not outcome.valid


def test_valid_false_with_recall_drone_rejected():
    """Inverse: valid=false but a real command (not unknown_command) — also
    a contradiction; the bridge would otherwise show DISPATCH-disabled on a
    perfectly good translation."""
    payload = {
        "kind": "command_translation",
        "command_id": "abcd-1700000000000-3",
        "structured": {
            "command": "recall_drone",
            "args": {"drone_id": "drone1", "reason": "x"},
        },
        "valid": False,
        "preview_text": "x",
        "preview_text_in_operator_language": "x",
        "egs_published_at_iso_ms": "2026-05-02T12:34:57.123Z",
        "contract_version": "1.0.0",
    }
    outcome = validate("command_translations_envelope", payload)
    assert not outcome.valid
