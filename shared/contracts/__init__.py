"""Shared integration contracts for FieldAgent v1.

Source of truth: docs/superpowers/specs/2026-04-30-integration-contracts-design.md
Wire schemas live at shared/schemas/*.json. This package loads them and exposes
runtime validators, Pydantic mirrors, the RuleID enum, and the topic registry.
"""
from pathlib import Path

VERSION = (Path(__file__).parent.parent / "VERSION").read_text().strip()

__all__ = ["VERSION"]
