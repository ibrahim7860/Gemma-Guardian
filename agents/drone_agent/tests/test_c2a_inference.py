"""Tests for the C2A adapter integration (loader, parser, translator).

These tests validate the pure-Python parts of c2a_inference.py — the
prompt/parser contract, the report_finding translation, and the adapter
path resolution logic.  They do NOT load a real model (no CUDA needed).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from agents.drone_agent.c2a_inference import (
    C2A_PROMPT,
    FINDING_TYPES,
    parse_c2a_output,
    resolve_adapter_path,
    translate_to_report_finding,
)


# ---------------------------------------------------------------------------
# parse_c2a_output
# ---------------------------------------------------------------------------

class TestParsC2AOutput:
    def test_valid_victim(self):
        raw = json.dumps({
            "finding_type": "victim",
            "confidence": 0.92,
            "visual_evidence": "Person visible amid rubble.",
        })
        result = parse_c2a_output(raw)
        assert result["parse_status"] == "ok"
        assert result["finding_type"] == "victim"
        assert result["confidence"] == 0.92
        assert "rubble" in result["visual_evidence"]

    def test_valid_none(self):
        raw = json.dumps({
            "finding_type": "none",
            "confidence": 0.85,
            "visual_evidence": "No humans visible.",
        })
        result = parse_c2a_output(raw)
        assert result["parse_status"] == "ok"
        assert result["finding_type"] == "none"

    def test_embedded_json(self):
        raw = 'Here is the result: {"finding_type": "victim", "confidence": 0.8, "visual_evidence": "A person on rubble."}'
        result = parse_c2a_output(raw)
        assert result["parse_status"] == "ok"
        assert result["finding_type"] == "victim"

    def test_codefence_json(self):
        raw = '```json\n{"finding_type": "victim", "confidence": 0.7, "visual_evidence": "Human figure visible."}\n```'
        result = parse_c2a_output(raw)
        assert result["parse_status"] == "ok"
        assert result["finding_type"] == "victim"

    def test_empty_string(self):
        result = parse_c2a_output("")
        assert result["parse_status"] == "empty"
        assert result["finding_type"] is None

    def test_none_input(self):
        result = parse_c2a_output(None)
        assert result["parse_status"] == "empty"
        assert result["finding_type"] is None

    def test_off_schema_prose(self):
        result = parse_c2a_output("This image shows a destroyed building.")
        assert result["parse_status"] == "off_schema"
        assert result["finding_type"] is None

    def test_bad_class(self):
        raw = json.dumps({
            "finding_type": "fire",
            "confidence": 0.9,
            "visual_evidence": "Fire visible.",
        })
        result = parse_c2a_output(raw)
        assert result["parse_status"] == "bad_class"
        assert result["finding_type"] is None

    def test_whitespace_only(self):
        result = parse_c2a_output("   \n\t  ")
        assert result["parse_status"] == "empty"


# ---------------------------------------------------------------------------
# translate_to_report_finding
# ---------------------------------------------------------------------------

class TestTranslateToReportFinding:
    def test_victim_produces_call(self):
        c2a = {
            "parse_status": "ok",
            "finding_type": "victim",
            "confidence": 0.85,
            "visual_evidence": "Human figure amid collapsed structure.",
        }
        call = translate_to_report_finding(c2a, lat=34.0, lon=-118.0, alt=25.0)
        assert call is not None
        assert call["function"] == "report_finding"
        args = call["arguments"]
        assert args["type"] == "victim"
        assert args["severity"] == 4
        assert args["gps_lat"] == 34.0
        assert args["gps_lon"] == -118.0
        assert args["confidence"] == 0.85
        assert len(args["visual_description"]) >= 10

    def test_none_returns_none(self):
        c2a = {
            "parse_status": "ok",
            "finding_type": "none",
            "confidence": 0.9,
            "visual_evidence": "No humans visible.",
        }
        call = translate_to_report_finding(c2a, lat=34.0, lon=-118.0, alt=25.0)
        assert call is None

    def test_parse_failure_returns_none(self):
        c2a = {"parse_status": "off_schema", "finding_type": None}
        call = translate_to_report_finding(c2a, lat=34.0, lon=-118.0, alt=25.0)
        assert call is None

    def test_missing_confidence_uses_default(self):
        c2a = {
            "parse_status": "ok",
            "finding_type": "victim",
            "confidence": None,
            "visual_evidence": "Person visible in the scene.",
        }
        call = translate_to_report_finding(c2a, lat=34.0, lon=-118.0, alt=25.0)
        assert call is not None
        assert call["arguments"]["confidence"] == 0.7  # safe default

    def test_confidence_clamped(self):
        c2a = {
            "parse_status": "ok",
            "finding_type": "victim",
            "confidence": 1.5,
            "visual_evidence": "Person visible in the scene.",
        }
        call = translate_to_report_finding(c2a, lat=34.0, lon=-118.0, alt=25.0)
        assert call["arguments"]["confidence"] == 1.0

    def test_short_evidence_padded(self):
        c2a = {
            "parse_status": "ok",
            "finding_type": "victim",
            "confidence": 0.8,
            "visual_evidence": "Person",
        }
        call = translate_to_report_finding(c2a, lat=34.0, lon=-118.0, alt=25.0)
        assert len(call["arguments"]["visual_description"]) >= 10

    def test_no_evidence_uses_default(self):
        c2a = {
            "parse_status": "ok",
            "finding_type": "victim",
            "confidence": 0.8,
            "visual_evidence": None,
        }
        call = translate_to_report_finding(c2a, lat=34.0, lon=-118.0, alt=25.0)
        assert call["arguments"]["visual_description"] is not None
        assert len(call["arguments"]["visual_description"]) >= 10


# ---------------------------------------------------------------------------
# resolve_adapter_path
# ---------------------------------------------------------------------------

class TestResolveAdapterPath:
    def test_env_var_override(self):
        with mock.patch.dict(os.environ, {"C2A_ADAPTER_PATH": "/custom/path"}):
            p = resolve_adapter_path()
            assert p == Path("/custom/path")

    def test_default_fallback(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            p = resolve_adapter_path()
            assert p.name == "adapter"
            assert "kaggle_work_c2a" in str(p)


# ---------------------------------------------------------------------------
# Prompt constant sanity checks
# ---------------------------------------------------------------------------

class TestPromptContract:
    def test_prompt_mentions_json(self):
        assert "JSON" in C2A_PROMPT

    def test_prompt_mentions_finding_type(self):
        assert "finding_type" in C2A_PROMPT

    def test_finding_types_has_victim_and_none(self):
        assert "victim" in FINDING_TYPES
        assert "none" in FINDING_TYPES


# ---------------------------------------------------------------------------
# Schema compliance (report_finding shape matches drone_function_calls.json)
# ---------------------------------------------------------------------------

class TestSchemaCompliance:
    """Verify that the translated call passes the project's JSON Schema."""

    def test_translated_call_validates(self):
        from shared.contracts import validate as schema_validate

        c2a = {
            "parse_status": "ok",
            "finding_type": "victim",
            "confidence": 0.85,
            "visual_evidence": "Human figure amid collapsed structure clearly visible.",
        }
        call = translate_to_report_finding(c2a, lat=34.05, lon=-118.25, alt=25.0)
        assert call is not None
        outcome = schema_validate("drone_function_calls", call)
        assert outcome.valid, f"Schema validation failed: {outcome.errors}"
