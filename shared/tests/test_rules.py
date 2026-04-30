"""Coverage tests for shared.contracts.rules.RuleID and RULE_REGISTRY."""
from __future__ import annotations

from shared.contracts.rules import RULE_REGISTRY, RuleID


def test_every_ruleid_is_registered():
    for rule in RuleID:
        assert rule in RULE_REGISTRY, f"missing entry for {rule}"


def test_every_registry_entry_has_nonempty_description_and_template():
    for rule, spec in RULE_REGISTRY.items():
        assert spec.id == rule, f"{rule}: spec.id mismatch"
        assert 1 <= len(spec.description) <= 200, f"{rule}: description out of bounds"
        assert spec.corrective_template.strip(), f"{rule}: empty corrective_template"
        assert spec.layer in ("drone", "egs", "operator"), f"{rule}: invalid layer {spec.layer!r}"


def test_ruleid_values_match_pattern():
    """Per _common.json#/$defs/rule_id: ^[A-Z][A-Z0-9_]{2,}$"""
    import re
    pattern = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
    for rule in RuleID:
        assert pattern.match(rule.value), f"{rule.value} doesn't match rule_id pattern"
