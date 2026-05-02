"""Phase 4 stub EGS: deterministic substring matcher for local round-trip tests."""
from __future__ import annotations

import pytest

from scripts.dev_command_translator import build_translation


def _envelope(raw_text: str, language: str = "en", cid: str = "abcd-1-1") -> dict:
    return {
        "kind": "operator_command",
        "command_id": cid,
        "language": language,
        "raw_text": raw_text,
        "bridge_received_at_iso_ms": "2026-05-02T12:00:00.000Z",
        "contract_version": "1.0.0",
    }


def test_recall_english():
    out = build_translation(_envelope("recall drone1 to base"))
    assert out["structured"]["command"] == "recall_drone"
    assert out["structured"]["args"]["drone_id"] == "drone1"
    assert out["valid"] is True


def test_restrict_zone_english():
    out = build_translation(_envelope("focus on zone east"))
    assert out["structured"]["command"] == "restrict_zone"
    assert out["structured"]["args"]["zone_id"] == "east"
    assert out["valid"] is True


def test_restrict_zone_spanish():
    out = build_translation(_envelope("concéntrate en la zona este", language="es"))
    assert out["structured"]["command"] == "restrict_zone"
    assert out["structured"]["args"]["zone_id"] == "east"
    assert out["valid"] is True


def test_exclude_zone_english():
    out = build_translation(_envelope("avoid zone west"))
    assert out["structured"]["command"] == "exclude_zone"
    assert out["structured"]["args"]["zone_id"] == "west"


def test_unknown_command_falls_back():
    out = build_translation(_envelope("asdf nonsense"))
    assert out["structured"]["command"] == "unknown_command"
    assert out["valid"] is False
    assert "operator_text" in out["structured"]["args"]
    assert "suggestion" in out["structured"]["args"]


def test_concentric_does_not_trigger_restrict_zone():
    """Adversarial finding #9: bare 'concentr' substring used to false-match
    'concentric' or 'concentration'. With \\b word boundaries it should fall
    through to unknown_command."""
    out = build_translation(_envelope("look for concentric debris pattern in east"))
    assert out["structured"]["command"] == "unknown_command"


def test_accent_normalization_concéntrate_matches():
    """Adversarial finding #9: NFKD fold means concéntrate matches
    concentrate. Operator typing with or without the accent should hit the
    same intent."""
    out = build_translation(_envelope("concéntrate en zona este", language="es"))
    assert out["structured"]["command"] == "restrict_zone"
    assert out["structured"]["args"]["zone_id"] == "east"


def test_envelope_validates_against_schema():
    """The entire output envelope must validate against
    command_translations_envelope.json."""
    from shared.contracts import validate
    out = build_translation(_envelope("recall drone1"))
    outcome = validate("command_translations_envelope", out)
    assert outcome.valid, outcome.errors
