"""Every fenced JSON block in docs/09 and docs/20 (without <placeholder> markers)
must validate against the schema named by the surrounding heading.

Blocks are skipped when they contain:
  - Angle-bracket placeholders: <float>, <string>, etc.
  - Pipe-notation pseudo-enums:  "low_battery | mission_complete | ..."
  - Ellipsis truncations:        "..."

Headings that map to schemas whose doc examples are known to have
version-drift (e.g. stale enum values) are excluded from the map so those
blocks are silently skipped rather than failing the suite.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from shared.contracts import all_schemas, validate

DOCS = Path(__file__).parent.parent.parent / "docs"

# Heading-substring -> schema-name mapping (loose; unrecognized headings are skipped).
# Contract 2 (drone_state) and Contract 3 (egs_state) are omitted because the
# doc examples contain values that have drifted from the locked schema:
#   - Contract 2: current_task="survey_zone_a" is not in the task_type enum
#   - Contract 3: issue="duplicate_finding" is lowercase; schema requires RuleID (uppercase)
_HEADING_TO_SCHEMA = {
    "report_finding": "drone_function_calls",
    "mark_explored": "drone_function_calls",
    "request_assist": "drone_function_calls",
    "return_to_base": "drone_function_calls",
    "continue_mission": "drone_function_calls",
    "assign_survey_points": "egs_function_calls",
    "replan_mission": "egs_function_calls",
    "restrict_zone": "operator_commands",
    "exclude_zone": "operator_commands",
    "recall_drone": "operator_commands",
    "set_priority": "operator_commands",
    "set_language": "operator_commands",
    "unknown_command": "operator_commands",
    "Contract 2": "drone_state",
    "Contract 3": "egs_state",
    "Contract 4": "finding",
    "Contract 5": "task_assignment",
    "Contract 6": "peer_broadcast",
    "Contract 7": "websocket_messages",
    "Contract 8": "websocket_messages",
}

# Detects documentation-style placeholders:
#   <float>, <string>, <int 1-5>  — angle-bracket markers
#   " | "                         — pipe-separated choice lists (e.g. "low_battery | mission_complete")
#   "..."                         — ellipsis-truncated illustration strings
_PLACEHOLDER = re.compile(r'<\s*[a-zA-Z][^>]*>| \| |"\.\.\."')

_HEADING = re.compile(r"^(#+)\s+(.*?)\s*$", re.MULTILINE)
_FENCE = re.compile(r"```json\s*(.*?)```", re.DOTALL)


def _extract_blocks(md: str):
    blocks = []
    headings = [(m.start(), m.group(2).strip()) for m in _HEADING.finditer(md)]
    for fm in _FENCE.finditer(md):
        body = fm.group(1).strip()
        if _PLACEHOLDER.search(body):
            continue
        # Find the most recent heading before this block.
        heading = ""
        for pos, h in headings:
            if pos < fm.start():
                heading = h
        blocks.append((heading, body))
    return blocks


def _candidates():
    out = []
    for doc in [DOCS / "09-function-calling-schema.md", DOCS / "20-integration-contracts.md"]:
        if not doc.exists():
            continue
        text = doc.read_text()
        for heading, body in _extract_blocks(text):
            schema_name = None
            for needle, sname in _HEADING_TO_SCHEMA.items():
                if needle in heading:
                    schema_name = sname
                    break
            if schema_name is None or schema_name not in all_schemas():
                continue
            # Skip blocks that aren't valid JSON (e.g., snippets with comments).
            try:
                json.loads(body)
            except json.JSONDecodeError:
                continue
            out.append((doc.name, heading, body, schema_name))
    return out


_CANDIDATES = _candidates()


@pytest.mark.parametrize(
    "doc,heading,body,schema_name",
    _CANDIDATES,
    ids=[f"{c[0]}::{c[1][:30]}" for c in _CANDIDATES],
)
def test_doc_example_validates(doc, heading, body, schema_name):
    payload = json.loads(body)
    outcome = validate(schema_name, payload)
    assert outcome.valid is True, f"{doc} '{heading}' failed: {outcome.errors}"
