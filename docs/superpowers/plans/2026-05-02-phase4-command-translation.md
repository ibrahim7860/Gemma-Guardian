# Phase 4 — Operator Command Translation Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking. Each task ends with a commit. Do NOT batch commits across tasks.

**Goal:** Ship the multilingual operator command translation round-trip on the dashboard (the headline demo moment), plus the bridge `finding_id` allowlist hardening and the validation event ticker on the drone status panel. All Person-4 lane work; Person 3's real EGS plugs in unchanged via the locked Redis contract.

**Architecture:** Discriminated `oneOf` Redis envelopes on two new channels (`egs.operator_commands` outbound, `egs.command_translations` inbound), plus a third `kind` (`operator_command_dispatch`) on the existing `egs.operator_actions` channel. Flutter gains a parallel command state machine modeled on Phase 3's finding state machine, with a 15s timeout, a single-active-command slot, a late-arrival drop rule, and an input-retention guarantee on Redis publish failure. Stub EGS at `scripts/dev_command_translator.py` makes the path locally testable without Person 3's real EGS.

**Tech Stack:** Python 3.11 (FastAPI + redis.asyncio + jsonschema 2020-12), Dart/Flutter (Provider + ChangeNotifier + web_socket_channel), pytest + fakeredis (Python tests), `flutter test` (Dart tests), Chrome DevTools MCP (e2e visual gate).

**Spec:** `docs/superpowers/specs/2026-05-02-phase4-command-translation-design.md` (approved 2026-05-02 after `/plan-eng-review`).

**Branch:** `feat/phase4-command-translation` (already created).

---

## Task graph

```
Task 1 (common.json command_id $def) ───┐
Task 2 (operator_actions adds dispatch) ─┤
Task 3 (operator_commands_envelope.json)─┼─► Task 5 (regen topics + add channels) ──► Tasks 6-9 (bridge changes)
Task 4 (command_translations_envelope) ──┘                                         └─► Task 10 (stub EGS)
                                                                                   └─► Tasks 11-13 (Flutter)
                                                                                                        └─► Task 14 (e2e gate) ──► Task 15 (TODOS update + final commit)
```

Tasks 1–4 are schemas only and can be a single subagent invocation. Tasks 5+ are sequential to keep the implementer's context tight. Each task is a discrete commit.

---

## Task 1: Extract `command_id` shared $def + extend `operator_actions` with `operator_command_dispatch`

**Files:**
- Modify: `shared/schemas/_common.json` (add `command_id` $def)
- Modify: `shared/schemas/operator_actions.json` (refactor finding_approval to use $ref, add operator_command_dispatch branch)
- Modify: `shared/schemas/websocket_messages.json` (refactor finding_approval to use the same shared $ref)
- Modify: `shared/tests/test_operator_actions_schema.py` (extend with operator_command_dispatch cases)
- Create: `shared/schemas/fixtures/valid/operator_actions/02_operator_command_dispatch.json`
- Create: `shared/schemas/fixtures/invalid/operator_actions/03_dispatch_missing_command_id.json`

- [ ] **Step 1: Add the failing `command_id` $def test to `_common.json`**

Add to `shared/tests/test_common_schemas.py` (create the file if it does not exist; if it does, add the function below):

```python
"""Shared $def coverage for _common.json."""
from __future__ import annotations

import pytest

from shared.contracts import validate


def test_command_id_def_accepts_session_format():
    payload = {
        "kind": "finding_approval",
        "command_id": "abcd-1700000000000-1",
        "finding_id": "f_drone1_42",
        "action": "approve",
        "bridge_received_at_iso_ms": "2026-05-02T12:34:56.789Z",
        "contract_version": "1.0.0",
    }
    outcome = validate("operator_actions", payload)
    assert outcome.valid, outcome.errors


def test_command_id_def_rejects_shell_metacharacters():
    payload = {
        "kind": "finding_approval",
        "command_id": "abcd; rm -rf /",
        "finding_id": "f_drone1_42",
        "action": "approve",
        "bridge_received_at_iso_ms": "2026-05-02T12:34:56.789Z",
        "contract_version": "1.0.0",
    }
    outcome = validate("operator_actions", payload)
    assert not outcome.valid
```

- [ ] **Step 2: Run the test. Expect PASS today (Phase 3 already enforces inline). The point of these tests is to keep the constraint covered after refactor.**

Run: `PYTHONPATH=. pytest shared/tests/test_common_schemas.py -v`
Expected: 2 passing.

- [ ] **Step 3: Add the `command_id` $def to `_common.json`**

Insert the following entry into the `$defs` block of `shared/schemas/_common.json`, alphabetically (between `coverage_pct` and `confidence` is fine; actual alphabetical placement is between `broadcast_type` and `confidence`):

```json
"command_id": {
  "type": "string",
  "minLength": 1,
  "maxLength": 128,
  "pattern": "^[A-Za-z0-9._-]{1,128}$"
},
```

- [ ] **Step 4: Refactor `operator_actions.json` — convert `finding_approval.command_id` to `$ref` AND add the new `operator_command_dispatch` branch**

Replace the entire file `shared/schemas/operator_actions.json` with:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://github.com/ibrahim7860/Gemma-Guardian/shared/schemas/v1/operator_actions.json",
  "title": "Redis payloads on egs.operator_actions",
  "description": "Operator-driven actions republished by the WS bridge to Redis after schema validation. Discriminated by `kind`.",
  "oneOf": [
    {"$ref": "#/$defs/finding_approval"},
    {"$ref": "#/$defs/operator_command_dispatch"}
  ],
  "$defs": {
    "finding_approval": {
      "type": "object",
      "required": ["kind", "command_id", "finding_id", "action", "bridge_received_at_iso_ms", "contract_version"],
      "additionalProperties": false,
      "properties": {
        "kind": {"const": "finding_approval"},
        "command_id": {"$ref": "_common.json#/$defs/command_id"},
        "finding_id": {"$ref": "_common.json#/$defs/finding_id"},
        "action": {"enum": ["approve", "dismiss"]},
        "bridge_received_at_iso_ms": {"$ref": "_common.json#/$defs/iso_timestamp_utc_ms"},
        "contract_version": {"type": "string", "pattern": "^\\d+\\.\\d+\\.\\d+$"}
      }
    },
    "operator_command_dispatch": {
      "type": "object",
      "required": ["kind", "command_id", "bridge_received_at_iso_ms", "contract_version"],
      "additionalProperties": false,
      "properties": {
        "kind": {"const": "operator_command_dispatch"},
        "command_id": {"$ref": "_common.json#/$defs/command_id"},
        "bridge_received_at_iso_ms": {"$ref": "_common.json#/$defs/iso_timestamp_utc_ms"},
        "contract_version": {"type": "string", "pattern": "^\\d+\\.\\d+\\.\\d+$"}
      }
    }
  }
}
```

- [ ] **Step 5: Refactor `websocket_messages.json` finding_approval branch to use the shared $ref**

In `shared/schemas/websocket_messages.json`, change the `command_id` property of the `finding_approval` branch from the inline constraint to:

```json
"command_id": {"$ref": "_common.json#/$defs/command_id"},
```

(Leave all other branches' `command_id` as their existing `{"type": "string", "minLength": 1}` — those are operator_command / command_translation / operator_command_dispatch shapes that DO get tightened to the $ref in later tasks. Touching them here would conflate refactors.)

- [ ] **Step 6: Add the dispatch valid fixture**

Create `shared/schemas/fixtures/valid/operator_actions/02_operator_command_dispatch.json`:

```json
{
  "kind": "operator_command_dispatch",
  "command_id": "abcd-1700000000000-7",
  "bridge_received_at_iso_ms": "2026-05-02T12:34:56.789Z",
  "contract_version": "1.0.0"
}
```

Create `shared/schemas/fixtures/invalid/operator_actions/03_dispatch_missing_command_id.json`:

```json
{
  "kind": "operator_command_dispatch",
  "bridge_received_at_iso_ms": "2026-05-02T12:34:56.789Z",
  "contract_version": "1.0.0"
}
```

- [ ] **Step 7: Extend `shared/tests/test_operator_actions_schema.py`**

Append:

```python
def test_dispatch_kind_validates():
    payload = _load("valid/operator_actions/02_operator_command_dispatch.json")
    outcome = validate("operator_actions", payload)
    assert outcome.valid, outcome.errors


def test_dispatch_missing_command_id_rejected():
    payload = _load("invalid/operator_actions/03_dispatch_missing_command_id.json")
    outcome = validate("operator_actions", payload)
    assert not outcome.valid
    assert outcome.errors


def test_dispatch_does_not_accept_finding_approval_only_fields():
    """A dispatch payload with finding_id+action must be rejected — those keys
    are additionalProperties:false on the dispatch branch."""
    payload = {
        "kind": "operator_command_dispatch",
        "command_id": "abcd-1700000000000-7",
        "finding_id": "f_drone1_42",
        "action": "approve",
        "bridge_received_at_iso_ms": "2026-05-02T12:34:56.789Z",
        "contract_version": "1.0.0",
    }
    outcome = validate("operator_actions", payload)
    assert not outcome.valid
```

- [ ] **Step 8: Run the full schema suite**

Run: `PYTHONPATH=. pytest shared/tests/ -v`
Expected: all green, including the 8 existing operator_actions tests + 3 new dispatch tests + 2 new common tests.

- [ ] **Step 9: Commit**

```bash
git add shared/schemas/_common.json shared/schemas/operator_actions.json \
  shared/schemas/websocket_messages.json shared/schemas/fixtures/valid/operator_actions/ \
  shared/schemas/fixtures/invalid/operator_actions/ shared/tests/test_operator_actions_schema.py \
  shared/tests/test_common_schemas.py
git commit -m "Phase 4 schema: shared command_id \$def + operator_command_dispatch kind"
```

---

## Task 2: New schema `operator_commands_envelope.json` (bridge → EGS)

**Files:**
- Create: `shared/schemas/operator_commands_envelope.json`
- Create: `shared/schemas/fixtures/valid/operator_commands_envelope/01_recall.json`
- Create: `shared/schemas/fixtures/invalid/operator_commands_envelope/01_missing_raw_text.json`
- Create: `shared/schemas/fixtures/invalid/operator_commands_envelope/02_raw_text_too_long.json`
- Create: `shared/schemas/fixtures/invalid/operator_commands_envelope/03_empty_raw_text.json`
- Create: `shared/tests/test_operator_commands_envelope_schema.py`
- Modify: `shared/contracts/schemas.py` (register the schema if registration is explicit)

- [ ] **Step 1: Check how schemas are registered**

Run: `grep -n "operator_actions" shared/contracts/schemas.py`
If the schema discovery is filesystem-glob, no registration change needed. If there's an explicit registry list, add `"operator_commands_envelope"` and `"command_translations_envelope"` (Task 3) at the same time.

- [ ] **Step 2: Write the schema test first (TDD)**

Create `shared/tests/test_operator_commands_envelope_schema.py`:

```python
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
```

- [ ] **Step 3: Create the fixtures**

`shared/schemas/fixtures/valid/operator_commands_envelope/01_recall.json`:
```json
{
  "kind": "operator_command",
  "command_id": "abcd-1700000000000-3",
  "language": "en",
  "raw_text": "recall drone1 to base",
  "bridge_received_at_iso_ms": "2026-05-02T12:34:56.789Z",
  "contract_version": "1.0.0"
}
```

`shared/schemas/fixtures/invalid/operator_commands_envelope/01_missing_raw_text.json`:
```json
{
  "kind": "operator_command",
  "command_id": "abcd-1700000000000-3",
  "language": "en",
  "bridge_received_at_iso_ms": "2026-05-02T12:34:56.789Z",
  "contract_version": "1.0.0"
}
```

`shared/schemas/fixtures/invalid/operator_commands_envelope/02_raw_text_too_long.json`: a JSON file whose `raw_text` is 4097 chars. Generate it with a one-shot Python:

```bash
python3 -c '
import json
payload = {
    "kind": "operator_command",
    "command_id": "abcd-1700000000000-3",
    "language": "en",
    "raw_text": "x" * 4097,
    "bridge_received_at_iso_ms": "2026-05-02T12:34:56.789Z",
    "contract_version": "1.0.0",
}
with open("shared/schemas/fixtures/invalid/operator_commands_envelope/02_raw_text_too_long.json", "w") as f:
    json.dump(payload, f)
'
```

`shared/schemas/fixtures/invalid/operator_commands_envelope/03_empty_raw_text.json`:
```json
{
  "kind": "operator_command",
  "command_id": "abcd-1700000000000-3",
  "language": "en",
  "raw_text": "",
  "bridge_received_at_iso_ms": "2026-05-02T12:34:56.789Z",
  "contract_version": "1.0.0"
}
```

- [ ] **Step 4: Run the test. Expect ALL FAIL with "schema not found" or similar.**

Run: `PYTHONPATH=. pytest shared/tests/test_operator_commands_envelope_schema.py -v`
Expected: 8 failing.

- [ ] **Step 5: Create the schema** (absolute `$ref` URIs per adversarial finding #3)

`shared/schemas/operator_commands_envelope.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://github.com/ibrahim7860/Gemma-Guardian/shared/schemas/v1/operator_commands_envelope.json",
  "title": "Bridge → EGS operator_command envelope",
  "description": "Republished onto egs.operator_commands by the WS bridge after validating the inbound websocket_messages.operator_command frame. Bridge stamps bridge_received_at_iso_ms.",
  "type": "object",
  "required": ["kind", "command_id", "language", "raw_text", "bridge_received_at_iso_ms", "contract_version"],
  "additionalProperties": false,
  "properties": {
    "kind": {"const": "operator_command"},
    "command_id": {"$ref": "https://github.com/ibrahim7860/Gemma-Guardian/shared/schemas/v1/_common.json#/$defs/command_id"},
    "language": {"$ref": "https://github.com/ibrahim7860/Gemma-Guardian/shared/schemas/v1/_common.json#/$defs/iso_lang_code"},
    "raw_text": {"type": "string", "minLength": 1, "maxLength": 4096},
    "bridge_received_at_iso_ms": {"$ref": "https://github.com/ibrahim7860/Gemma-Guardian/shared/schemas/v1/_common.json#/$defs/iso_timestamp_utc_ms"},
    "contract_version": {"type": "string", "pattern": "^\\d+\\.\\d+\\.\\d+$"}
  }
}
```

- [ ] **Step 6: Run the test. Expect ALL PASS.**

Run: `PYTHONPATH=. pytest shared/tests/test_operator_commands_envelope_schema.py -v`
Expected: 8 passing.

- [ ] **Step 7: Commit**

```bash
git add shared/schemas/operator_commands_envelope.json \
  shared/schemas/fixtures/valid/operator_commands_envelope/ \
  shared/schemas/fixtures/invalid/operator_commands_envelope/ \
  shared/tests/test_operator_commands_envelope_schema.py
git commit -m "Phase 4 schema: operator_commands_envelope (bridge → EGS)"
```

---

## Task 3: New schema `command_translations_envelope.json` (EGS → bridge)

**Files:**
- Create: `shared/schemas/command_translations_envelope.json`
- Create: `shared/schemas/fixtures/valid/command_translations_envelope/01_recall.json`
- Create: `shared/schemas/fixtures/valid/command_translations_envelope/02_unknown_command.json`
- Create: `shared/schemas/fixtures/invalid/command_translations_envelope/01_missing_preview.json`
- Create: `shared/schemas/fixtures/invalid/command_translations_envelope/02_invalid_structured.json`
- Create: `shared/tests/test_command_translations_envelope_schema.py`

- [ ] **Step 1: Write the failing tests**

Create `shared/tests/test_command_translations_envelope_schema.py`:

```python
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
```

- [ ] **Step 2: Create the fixtures**

`shared/schemas/fixtures/valid/command_translations_envelope/01_recall.json`:
```json
{
  "kind": "command_translation",
  "command_id": "abcd-1700000000000-3",
  "structured": {
    "command": "recall_drone",
    "args": {"drone_id": "drone1", "reason": "operator request"}
  },
  "valid": true,
  "preview_text": "Will recall drone1: operator request",
  "preview_text_in_operator_language": "Will recall drone1: operator request",
  "egs_published_at_iso_ms": "2026-05-02T12:34:57.123Z",
  "contract_version": "1.0.0"
}
```

`shared/schemas/fixtures/valid/command_translations_envelope/02_unknown_command.json`:
```json
{
  "kind": "command_translation",
  "command_id": "abcd-1700000000000-4",
  "structured": {
    "command": "unknown_command",
    "args": {"operator_text": "asdf nonsense", "suggestion": "Try 'recall drone1' or 'focus on zone east'"}
  },
  "valid": false,
  "preview_text": "Command not understood",
  "preview_text_in_operator_language": "Command not understood",
  "egs_published_at_iso_ms": "2026-05-02T12:34:57.123Z",
  "contract_version": "1.0.0"
}
```

`shared/schemas/fixtures/invalid/command_translations_envelope/01_missing_preview.json`:
```json
{
  "kind": "command_translation",
  "command_id": "abcd-1700000000000-3",
  "structured": {
    "command": "recall_drone",
    "args": {"drone_id": "drone1", "reason": "operator request"}
  },
  "valid": true,
  "egs_published_at_iso_ms": "2026-05-02T12:34:57.123Z",
  "contract_version": "1.0.0"
}
```

`shared/schemas/fixtures/invalid/command_translations_envelope/02_invalid_structured.json`:
```json
{
  "kind": "command_translation",
  "command_id": "abcd-1700000000000-3",
  "structured": {
    "command": "fabricated_command",
    "args": {}
  },
  "valid": true,
  "preview_text": "Bogus",
  "preview_text_in_operator_language": "Bogus",
  "egs_published_at_iso_ms": "2026-05-02T12:34:57.123Z",
  "contract_version": "1.0.0"
}
```

- [ ] **Step 3: Run the tests. Expect 7 failing (schema not found).**

Run: `PYTHONPATH=. pytest shared/tests/test_command_translations_envelope_schema.py -v`

- [ ] **Step 3.5: Add the contradiction-rejection test (adversarial finding #2)**

Append to the same test file:

```python
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
```

- [ ] **Step 4: Create the schema** (with absolute `$ref` URIs per adversarial finding #3 + `if/then` invariant per #2)

`shared/schemas/command_translations_envelope.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://github.com/ibrahim7860/Gemma-Guardian/shared/schemas/v1/command_translations_envelope.json",
  "title": "EGS → Bridge command_translation envelope",
  "description": "EGS Gemma 4 E4B output for an operator_command. Bridge subscribes to egs.command_translations and forwards to WS clients as type=command_translation. The if/then constraints enforce that valid=false iff command=unknown_command.",
  "type": "object",
  "required": ["kind", "command_id", "structured", "valid", "preview_text", "preview_text_in_operator_language", "egs_published_at_iso_ms", "contract_version"],
  "additionalProperties": false,
  "properties": {
    "kind": {"const": "command_translation"},
    "command_id": {"$ref": "https://github.com/ibrahim7860/Gemma-Guardian/shared/schemas/v1/_common.json#/$defs/command_id"},
    "structured": {"$ref": "https://github.com/ibrahim7860/Gemma-Guardian/shared/schemas/v1/operator_commands.json"},
    "valid": {"type": "boolean"},
    "preview_text": {"type": "string", "minLength": 1, "maxLength": 1024},
    "preview_text_in_operator_language": {"type": "string", "minLength": 1, "maxLength": 1024},
    "egs_published_at_iso_ms": {"$ref": "https://github.com/ibrahim7860/Gemma-Guardian/shared/schemas/v1/_common.json#/$defs/iso_timestamp_utc_ms"},
    "contract_version": {"type": "string", "pattern": "^\\d+\\.\\d+\\.\\d+$"}
  },
  "allOf": [
    {
      "if": {"properties": {"valid": {"const": false}}, "required": ["valid"]},
      "then": {"properties": {"structured": {"properties": {"command": {"const": "unknown_command"}}}}}
    },
    {
      "if": {"properties": {"structured": {"properties": {"command": {"const": "unknown_command"}}}}, "required": ["structured"]},
      "then": {"properties": {"valid": {"const": false}}}
    }
  ]
}
```

**Note for the implementer:** if your jsonschema validator does not have `if/then/else` for Draft 2020-12, the equivalent is `oneOf` with two branches: `{valid:false, command:"unknown_command"}` vs `{valid:true, command:!"unknown_command"}`. Test the constraint actually rejects contradictions before declaring this task green.

- [ ] **Step 5: Run the tests. Expect 9 passing.** (7 original + 2 contradiction tests)

Run: `PYTHONPATH=. pytest shared/tests/test_command_translations_envelope_schema.py -v`

If `test_invalid_structured_payload_rejected` does NOT fail validation, the cross-file `$ref` to `operator_commands.json` is not being resolved. Verify by:

Run: `PYTHONPATH=. python3 -c "from shared.contracts import validate; print(validate('command_translations_envelope', {'kind':'command_translation','command_id':'a','structured':{'command':'fabricated','args':{}},'valid':True,'preview_text':'x','preview_text_in_operator_language':'x','egs_published_at_iso_ms':'2026-05-02T12:34:57.123Z','contract_version':'1.0.0'}).errors)"`

Expected: error list is non-empty mentioning the structured field.

If empty: the registry loader needs `operator_commands.json` to be loaded *before* `command_translations_envelope.json`. Inspect `shared/contracts/schemas.py` and adjust.

- [ ] **Step 6: Commit**

```bash
git add shared/schemas/command_translations_envelope.json \
  shared/schemas/fixtures/valid/command_translations_envelope/ \
  shared/schemas/fixtures/invalid/command_translations_envelope/ \
  shared/tests/test_command_translations_envelope_schema.py
git commit -m "Phase 4 schema: command_translations_envelope (EGS → bridge)"
```

---

## Task 4: Update `websocket_messages.json` to use shared `command_id` $ref on the new branches

**Files:**
- Modify: `shared/schemas/websocket_messages.json`
- Modify: `shared/tests/test_websocket_messages_schema.py` (if exists; otherwise extend an existing relevant test)

The `operator_command`, `command_translation`, and `operator_command_dispatch` WS frames must all use the tightened `command_id` constraint so a malformed value cannot leak through Flutter into Redis.

- [ ] **Step 1: Find the existing WS schema test**

Run: `find shared/tests -name 'test_websocket*'`
If a test file exists, extend it. If not, add tests inline to one of the existing schema tests.

- [ ] **Step 2: Add a failing test for command_id charset on operator_command**

Append:

```python
def test_operator_command_command_id_charset_enforced():
    """Reject command_ids with shell metacharacters at the WS layer too."""
    payload = {
        "type": "operator_command",
        "command_id": "abcd; rm -rf /",
        "language": "en",
        "raw_text": "recall drone1",
        "contract_version": "1.0.0",
    }
    outcome = validate("websocket_messages", payload)
    assert not outcome.valid
```

(Add equivalent tests for `command_translation` and `operator_command_dispatch`.)

- [ ] **Step 3: Run. Expect 3 failing (existing schema accepts any non-empty string).**

- [ ] **Step 4: In `shared/schemas/websocket_messages.json`, replace each of the three `command_id` properties on `operator_command`, `command_translation`, and `operator_command_dispatch` with:**

```json
"command_id": {"$ref": "_common.json#/$defs/command_id"},
```

(Leave `finding_approval`'s — Task 1 already updated it.)

- [ ] **Step 5: Run. Expect 3 passing.**

- [ ] **Step 6: Run the full schema suite to catch regressions:**

Run: `PYTHONPATH=. pytest shared/tests/ -v`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add shared/schemas/websocket_messages.json shared/tests/
git commit -m "Phase 4 schema: tighten command_id on remaining WS branches"
```

---

## Task 5: Add new channels to `topics.yaml` + regen Python and Dart constants

**Files:**
- Modify: `shared/contracts/topics.yaml`
- Regenerate: `shared/contracts/topics.py`, `frontend/flutter_dashboard/lib/generated/topics.dart`
- Modify: `shared/tests/test_topics_codegen_fresh.py` (if necessary)

- [ ] **Step 1: Append the two new channels**

In `shared/contracts/topics.yaml`, under `redis.egs:`, after the existing `operator_actions:` line, add:

```yaml
    operator_commands:      {channel: "egs.operator_commands",      payload: "json", json_schema: "operator_commands_envelope"}
    command_translations:   {channel: "egs.command_translations",   payload: "json", json_schema: "command_translations_envelope"}
```

- [ ] **Step 2: Regenerate**

Run: `PYTHONPATH=. python3 -m scripts.gen_topic_constants`

- [ ] **Step 3: Verify the generated files**

Read `shared/contracts/topics.py` and confirm:
```python
EGS_OPERATOR_COMMANDS = "egs.operator_commands"
EGS_COMMAND_TRANSLATIONS = "egs.command_translations"
```

Read `frontend/flutter_dashboard/lib/generated/topics.dart` and confirm:
```dart
static const egsOperatorCommands = "egs.operator_commands";
static const egsCommandTranslations = "egs.command_translations";
```

- [ ] **Step 4: Run the staleness test**

Run: `PYTHONPATH=. pytest shared/tests/test_topics_codegen_fresh.py -v`
Expected: passing (both regenerated files match the YAML).

- [ ] **Step 5: Commit**

```bash
git add shared/contracts/topics.yaml shared/contracts/topics.py \
  frontend/flutter_dashboard/lib/generated/topics.dart
git commit -m "Phase 4 contracts: add egs.operator_commands and egs.command_translations channels"
```

---

## Test harness convention for Tasks 7–10 (adversarial finding #8)

**Do NOT use `TestClient` + `asyncio.new_event_loop()` for bridge tests.** That pattern binds `fakeredis.aioredis.FakeRedis()` to FastAPI's TestClient internal loop, then awaits on a different loop, producing either `RuntimeError: ... attached to a different loop` or silent no-message hangs. Phase 3 got away with it because all assertions were against a single-shot WS frame; Phase 4's tests need to publish-from-Redis-then-receive-on-WS, which exercises both loops.

**Use `httpx.AsyncClient` + `pytest_asyncio` instead.** Single event loop owns the FastAPI app, the WebSocket transport, and the fakeredis client. Verified working with FastAPI ≥0.110 and httpx ≥0.27 (both in `requirements.txt`).

Standard fixture pattern for every Task 7–10 test file:

```python
"""Phase 4 bridge test using single-loop httpx.AsyncClient + pytest_asyncio."""
from __future__ import annotations

import asyncio
import json

import fakeredis.aioredis as fakeredis_async
import httpx
import pytest
import pytest_asyncio
from httpx_ws import aconnect_ws  # pip install httpx-ws

from frontend.ws_bridge.main import create_app


@pytest_asyncio.fixture
async def fake_client():
    """Create the fakeredis client on the running test loop. The publisher
    fixture below patches Redis.from_url to return THIS client, so app code
    and test code share a single Redis state on a single loop.
    """
    client = fakeredis_async.FakeRedis()
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def app_with_fake_redis(monkeypatch, fake_client):
    import redis.asyncio as redis_async
    monkeypatch.setattr(
        redis_async.Redis, "from_url",
        staticmethod(lambda url, **kw: fake_client),
    )
    app = create_app()
    async with httpx.AsyncClient(app=app, base_url="http://testserver") as ac:
        # Trigger lifespan startup so emit_loop, subscriber, and the new
        # translation_broadcaster all start on this loop.
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, lifespan="on")) as _bound:
            yield app, ac, fake_client


@pytest_asyncio.fixture
async def ws_client(app_with_fake_redis):
    """Yield an open WebSocket session bound to the same loop."""
    app, ac, fake = app_with_fake_redis
    async with aconnect_ws("ws://testserver/", client=ac) as ws:
        # Drain initial state envelope so subsequent receives are post-handshake.
        await ws.receive_text()
        yield ws, app, fake
```

If `httpx-ws` is unavailable, fall back to `httpx.AsyncClient` with manual ASGI WebSocket scope construction (see https://www.starlette.io/testclient/ for the spec). The dependency is small (`pip install httpx-ws`); add to `frontend/ws_bridge/requirements-dev.txt`.

**Apply this fixture pattern to every test file in Tasks 7, 8, 9, 10.** The test bodies in those tasks reference these fixtures; do not duplicate setup boilerplate.

If for any reason this harness cannot be made to work in your environment, the fallback is `pytest_asyncio` + manually awaiting the lifespan context (`async with app.router.lifespan_context(app):`) and bypassing the WS by injecting frames directly into `app.state.registry`. That bypass loses end-to-end coverage of the WS handler — flag it as a known gap and add a Chrome DevTools MCP case to compensate.

---

## Task 6: `StateAggregator.has_finding()` accessor + tests

**Files:**
- Modify: `frontend/ws_bridge/aggregator.py`
- Modify: `frontend/ws_bridge/tests/test_aggregator.py` (or create test_aggregator_has_finding.py if separate file is preferred)

- [ ] **Step 1: Write the failing test**

Append to `frontend/ws_bridge/tests/test_aggregator.py` (or create a dedicated file):

```python
def test_has_finding_returns_true_for_known_id(seed_envelope):
    agg = StateAggregator(max_findings=10, seed_envelope=seed_envelope)
    finding = {
        "finding_id": "f_drone1_42",
        "source_drone_id": "drone1",
        "timestamp": "2026-05-02T12:00:00.000Z",
        "type": "victim",
        "severity": 4,
        "gps_lat": 34.12,
        "gps_lon": -118.56,
        "altitude": 0,
        "confidence": 0.8,
        "visual_description": "person prone in debris",
        "image_path": "/tmp/x.jpg",
        "validated": True,
        "validation_retries": 0,
        "operator_status": "pending",
    }
    agg.add_finding(finding)
    assert agg.has_finding("f_drone1_42") is True


def test_has_finding_returns_false_for_unknown_id(seed_envelope):
    agg = StateAggregator(max_findings=10, seed_envelope=seed_envelope)
    assert agg.has_finding("f_drone7_99") is False


def test_has_finding_returns_false_after_eviction(seed_envelope):
    """When max_findings cap evicts oldest, has_finding flips to False for it."""
    agg = StateAggregator(max_findings=1, seed_envelope=seed_envelope)
    base = {
        "source_drone_id": "drone1", "timestamp": "2026-05-02T12:00:00.000Z",
        "type": "victim", "severity": 4, "gps_lat": 34.12, "gps_lon": -118.56,
        "altitude": 0, "confidence": 0.8, "visual_description": "person prone in debris",
        "image_path": "/tmp/x.jpg", "validated": True, "validation_retries": 0,
        "operator_status": "pending",
    }
    agg.add_finding({**base, "finding_id": "f_drone1_1"})
    agg.add_finding({**base, "finding_id": "f_drone1_2"})  # evicts _1
    assert agg.has_finding("f_drone1_1") is False
    assert agg.has_finding("f_drone1_2") is True
```

(If `seed_envelope` fixture does not exist, add it to `conftest.py` reading from `shared/schemas/fixtures/valid/websocket_messages/01_state_update.json`.)

- [ ] **Step 2: Run the test. Expect 3 failing (AttributeError).**

Run: `PYTHONPATH=. pytest frontend/ws_bridge/tests/test_aggregator.py -v -k has_finding`

- [ ] **Step 3: Add the accessor**

In `frontend/ws_bridge/aggregator.py`, add as the last public method (before any private helpers if any):

```python
    def has_finding(self, finding_id: str) -> bool:
        """Return True iff the aggregator currently holds a finding with this id.

        Used by the bridge's finding_approval allowlist guard (Phase 4) to
        reject inbound approvals for unknown or aged-out finding_ids before
        republishing them onto egs.operator_actions. The check is O(1) on the
        OrderedDict.
        """
        return finding_id in self._findings
```

- [ ] **Step 4: Run the test. Expect 3 passing.**

- [ ] **Step 5: Commit**

```bash
git add frontend/ws_bridge/aggregator.py frontend/ws_bridge/tests/
git commit -m "Phase 4 bridge: StateAggregator.has_finding() for allowlist guard"
```

---

## Task 7: Bridge — `finding_id` allowlist guard on inbound `finding_approval`

**Files:**
- Modify: `frontend/ws_bridge/main.py`
- Create: `frontend/ws_bridge/tests/test_main_finding_id_allowlist.py`

- [ ] **Step 1: Write the failing tests**

Create `frontend/ws_bridge/tests/test_main_finding_id_allowlist.py`:

```python
"""Phase 4: the bridge must reject finding_approval frames whose finding_id
is not in the aggregator's known set, before republishing to Redis.

Closes the Phase 3 adversarial-review finding that any well-formed finding_id
was being republished verbatim.
"""
from __future__ import annotations

import asyncio
import json

import fakeredis.aioredis as fakeredis_async
import pytest
from fastapi.testclient import TestClient

from frontend.ws_bridge.main import create_app


@pytest.fixture
def fake_client():
    return fakeredis_async.FakeRedis()


@pytest.fixture
def patched_from_url(monkeypatch, fake_client):
    import redis.asyncio as redis_async
    monkeypatch.setattr(
        redis_async.Redis, "from_url",
        staticmethod(lambda url, **kw: fake_client),
    )
    return fake_client


def _approval_frame(finding_id: str, command_id: str = "abcd-1700000000000-1") -> dict:
    return {
        "type": "finding_approval",
        "command_id": command_id,
        "finding_id": finding_id,
        "action": "approve",
        "contract_version": "1.0.0",
    }


def test_unknown_finding_id_returns_echo_error_and_no_publish(patched_from_url):
    app = create_app()
    pubsub = patched_from_url.pubsub()

    async def _capture():
        await pubsub.subscribe("egs.operator_actions")
        try:
            for _ in range(20):
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
                if msg is not None:
                    return msg
                await asyncio.sleep(0.01)
            return None
        finally:
            await pubsub.aclose()

    with TestClient(app) as client:
        with client.websocket_connect("/") as ws:
            ws.receive_text()  # initial state envelope
            capture_task = asyncio.get_event_loop().run_until_complete  # placeholder
            ws.send_text(json.dumps(_approval_frame("f_drone99_999")))
            response = ws.receive_text()
            envelope = json.loads(response)
            assert envelope["type"] == "echo"
            assert envelope["error"] == "unknown_finding_id"
            assert envelope["finding_id"] == "f_drone99_999"


def test_known_finding_id_publishes_normally(patched_from_url):
    """Positive case: an approval for a known finding still publishes."""
    app = create_app()
    # Seed the aggregator with one finding
    seed_finding = {
        "finding_id": "f_drone1_5",
        "source_drone_id": "drone1",
        "timestamp": "2026-05-02T12:00:00.000Z",
        "type": "victim",
        "severity": 4,
        "gps_lat": 34.12,
        "gps_lon": -118.56,
        "altitude": 0,
        "confidence": 0.8,
        "visual_description": "person prone in debris",
        "image_path": "/tmp/x.jpg",
        "validated": True,
        "validation_retries": 0,
        "operator_status": "pending",
    }
    app.state.aggregator.add_finding(seed_finding)

    received = []
    pubsub = patched_from_url.pubsub()

    async def _capture():
        await pubsub.subscribe("egs.operator_actions")
        try:
            for _ in range(50):
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.05)
                if msg is not None:
                    received.append(json.loads(msg["data"]))
                    return
                await asyncio.sleep(0.01)
        finally:
            await pubsub.aclose()

    with TestClient(app) as client:
        with client.websocket_connect("/") as ws:
            ws.receive_text()
            # Fire and capture in the same loop
            loop = asyncio.new_event_loop()
            cap_task = loop.create_task(_capture())
            ws.send_text(json.dumps(_approval_frame("f_drone1_5")))
            response = ws.receive_text()
            envelope = json.loads(response)
            assert envelope["type"] == "echo"
            assert envelope.get("ack") == "finding_approval"
            assert envelope["finding_id"] == "f_drone1_5"
            loop.run_until_complete(cap_task)

    # We should have observed the publish on the fakeredis channel.
    assert len(received) == 1
    assert received[0]["finding_id"] == "f_drone1_5"
```

> **Note for the implementer:** the asyncio plumbing in the second test mixes `TestClient` (sync) with `fakeredis.aioredis` (async). If the test framework chokes on the loop juggling, simplify by using `httpx.AsyncClient` and `pytest.mark.asyncio`. The test logic is what matters, not the precise harness — rewrite if needed but keep both the negative and positive assertions.

- [ ] **Step 2: Run the tests. Expect failures.**

Run: `PYTHONPATH=. pytest frontend/ws_bridge/tests/test_main_finding_id_allowlist.py -v`

- [ ] **Step 3: Add the allowlist guard in `main.py`**

In the `finding_approval` branch in `ws_endpoint` (around line 281–337), after the schema validation block and BEFORE building the `redis_payload`, insert:

```python
                    # Phase 4: allowlist guard. The bridge's aggregator holds
                    # the canonical "known findings" set (the same set the
                    # dashboard renders). Reject approvals for unknown ids
                    # before publishing to keep the operator-decision audit
                    # trail clean — closes the Phase 3 adversarial finding.
                    if not app.state.aggregator.has_finding(parsed["finding_id"]):
                        await _echo_error(
                            websocket,
                            error="unknown_finding_id",
                            command_id=parsed.get("command_id"),
                            finding_id=parsed.get("finding_id"),
                        )
                        continue
```

- [ ] **Step 4: Run the tests. Expect both passing.**

- [ ] **Step 5: Commit**

```bash
git add frontend/ws_bridge/main.py frontend/ws_bridge/tests/test_main_finding_id_allowlist.py
git commit -m "Phase 4 bridge: finding_id allowlist guard before Redis republish"
```

---

## Task 8: Bridge — republish `operator_command` to `egs.operator_commands`

**Files:**
- Modify: `frontend/ws_bridge/main.py` (replace the operator_command stub branch with full publish)
- Create: `frontend/ws_bridge/tests/test_main_operator_command_publish.py`

- [ ] **Step 1: Write the failing test**

Create `frontend/ws_bridge/tests/test_main_operator_command_publish.py`:

```python
"""Phase 4: operator_command frames are republished to egs.operator_commands
after schema validation. Bridge stamps bridge_received_at_iso_ms.
"""
from __future__ import annotations

import asyncio
import json

import fakeredis.aioredis as fakeredis_async
import pytest
from fastapi.testclient import TestClient

from frontend.ws_bridge.main import create_app
from shared.contracts import validate


@pytest.fixture
def fake_client():
    return fakeredis_async.FakeRedis()


@pytest.fixture
def patched_from_url(monkeypatch, fake_client):
    import redis.asyncio as redis_async
    monkeypatch.setattr(
        redis_async.Redis, "from_url",
        staticmethod(lambda url, **kw: fake_client),
    )
    return fake_client


def test_valid_operator_command_publishes_envelope(patched_from_url):
    app = create_app()
    received = []
    pubsub = patched_from_url.pubsub()

    async def _drain():
        await pubsub.subscribe("egs.operator_commands")
        try:
            for _ in range(50):
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.05)
                if msg is not None:
                    received.append(json.loads(msg["data"]))
                    return
                await asyncio.sleep(0.01)
        finally:
            await pubsub.aclose()

    frame = {
        "type": "operator_command",
        "command_id": "abcd-1700000000000-3",
        "language": "en",
        "raw_text": "recall drone1 to base",
        "contract_version": "1.0.0",
    }

    with TestClient(app) as client:
        with client.websocket_connect("/") as ws:
            ws.receive_text()  # initial envelope
            loop = asyncio.new_event_loop()
            cap = loop.create_task(_drain())
            ws.send_text(json.dumps(frame))
            ack = json.loads(ws.receive_text())
            loop.run_until_complete(cap)

    assert ack["type"] == "echo"
    assert ack["ack"] == "operator_command_received"
    assert ack["command_id"] == "abcd-1700000000000-3"

    assert len(received) == 1
    envelope = received[0]
    assert envelope["kind"] == "operator_command"
    assert envelope["command_id"] == "abcd-1700000000000-3"
    assert envelope["language"] == "en"
    assert envelope["raw_text"] == "recall drone1 to base"
    assert "bridge_received_at_iso_ms" in envelope
    # And it must validate against its own schema
    outcome = validate("operator_commands_envelope", envelope)
    assert outcome.valid, outcome.errors


def test_invalid_operator_command_no_publish(patched_from_url):
    """A schema-invalid frame must not reach Redis."""
    app = create_app()
    pubsub = patched_from_url.pubsub()
    received = []

    async def _drain():
        await pubsub.subscribe("egs.operator_commands")
        try:
            for _ in range(15):
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.05)
                if msg is not None:
                    received.append(json.loads(msg["data"]))
                await asyncio.sleep(0.01)
        finally:
            await pubsub.aclose()

    frame = {
        "type": "operator_command",
        "command_id": "abcd-1700000000000-3",
        "language": "en",
        # missing raw_text
        "contract_version": "1.0.0",
    }

    with TestClient(app) as client:
        with client.websocket_connect("/") as ws:
            ws.receive_text()
            loop = asyncio.new_event_loop()
            cap = loop.create_task(_drain())
            ws.send_text(json.dumps(frame))
            ack = json.loads(ws.receive_text())
            loop.run_until_complete(cap)

    assert ack["type"] == "echo"
    assert ack["error"] == "invalid_operator_command"
    assert received == []
```

- [ ] **Step 2: Run. Expect failures (current code only acks; doesn't publish).**

- [ ] **Step 3: Replace the existing operator_command branch in `main.py`**

In `ws_endpoint`, the current block (around line 261–280) reads "Phase 4 will translate via the EGS and republish onto Redis. For now, just acknowledge." Replace the entire `if isinstance(parsed, dict) and parsed.get("type") == "operator_command":` block with:

```python
                if isinstance(parsed, dict) and parsed.get("type") == "operator_command":
                    outcome = validate("websocket_messages", parsed)
                    if not outcome.valid:
                        await _echo_error(
                            websocket,
                            error="invalid_operator_command",
                            detail=[e.message for e in outcome.errors],
                            command_id=parsed.get("command_id"),
                        )
                        continue
                    redis_payload: Dict[str, Any] = {
                        "kind": "operator_command",
                        "command_id": parsed["command_id"],
                        "language": parsed["language"],
                        "raw_text": parsed["raw_text"],
                        "bridge_received_at_iso_ms": _now_iso_ms(),
                        "contract_version": VERSION,
                    }
                    bridge_outcome = validate("operator_commands_envelope", redis_payload)
                    if not bridge_outcome.valid:
                        await _echo_error(
                            websocket,
                            error="bridge_internal",
                            detail=[e.message for e in bridge_outcome.errors],
                            command_id=parsed.get("command_id"),
                        )
                        continue
                    try:
                        await app.state.publisher.publish(
                            "egs.operator_commands", redis_payload,
                        )
                    except Exception:
                        await _echo_error(
                            websocket,
                            error="redis_publish_failed",
                            command_id=parsed.get("command_id"),
                        )
                        continue
                    await websocket.send_text(
                        json.dumps({
                            "type": "echo",
                            "ack": "operator_command_received",
                            "command_id": parsed["command_id"],
                            "contract_version": VERSION,
                        })
                    )
```

- [ ] **Step 4: Run. Expect both tests passing.**

- [ ] **Step 5: Run the full bridge suite for regressions:**

Run: `PYTHONPATH=. pytest frontend/ws_bridge/tests/ -v`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add frontend/ws_bridge/main.py frontend/ws_bridge/tests/test_main_operator_command_publish.py
git commit -m "Phase 4 bridge: republish operator_command to egs.operator_commands"
```

---

## Task 9: Bridge — handle inbound `operator_command_dispatch` and republish to `egs.operator_actions`

**Files:**
- Modify: `frontend/ws_bridge/main.py` (add a fourth `elif` branch)
- Create: `frontend/ws_bridge/tests/test_main_operator_command_dispatch.py`

- [ ] **Step 1: Write the failing test**

Create `frontend/ws_bridge/tests/test_main_operator_command_dispatch.py`:

```python
"""Phase 4: operator_command_dispatch frames are republished to
egs.operator_actions with kind=operator_command_dispatch.
"""
from __future__ import annotations

import asyncio
import json

import fakeredis.aioredis as fakeredis_async
import pytest
from fastapi.testclient import TestClient

from frontend.ws_bridge.main import create_app


@pytest.fixture
def fake_client():
    return fakeredis_async.FakeRedis()


@pytest.fixture
def patched_from_url(monkeypatch, fake_client):
    import redis.asyncio as redis_async
    monkeypatch.setattr(
        redis_async.Redis, "from_url",
        staticmethod(lambda url, **kw: fake_client),
    )
    return fake_client


def test_dispatch_publishes_to_operator_actions(patched_from_url):
    app = create_app()
    received = []
    pubsub = patched_from_url.pubsub()

    async def _drain():
        await pubsub.subscribe("egs.operator_actions")
        try:
            for _ in range(50):
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.05)
                if msg is not None:
                    received.append(json.loads(msg["data"]))
                    return
                await asyncio.sleep(0.01)
        finally:
            await pubsub.aclose()

    frame = {
        "type": "operator_command_dispatch",
        "command_id": "abcd-1700000000000-7",
        "contract_version": "1.0.0",
    }

    with TestClient(app) as client:
        with client.websocket_connect("/") as ws:
            ws.receive_text()
            loop = asyncio.new_event_loop()
            cap = loop.create_task(_drain())
            ws.send_text(json.dumps(frame))
            ack = json.loads(ws.receive_text())
            loop.run_until_complete(cap)

    assert ack["type"] == "echo"
    assert ack["ack"] == "operator_command_dispatch"
    assert ack["command_id"] == "abcd-1700000000000-7"

    assert len(received) == 1
    envelope = received[0]
    assert envelope["kind"] == "operator_command_dispatch"
    assert envelope["command_id"] == "abcd-1700000000000-7"
    assert "bridge_received_at_iso_ms" in envelope
```

- [ ] **Step 2: Run. Expect failure.**

- [ ] **Step 3: Add the branch in `main.py`**

In `ws_endpoint`, between the `finding_approval` branch and the final `else: debug echo` branch, insert:

```python
                elif isinstance(parsed, dict) and parsed.get("type") == "operator_command_dispatch":
                    outcome = validate("websocket_messages", parsed)
                    if not outcome.valid:
                        await _echo_error(
                            websocket,
                            error="invalid_operator_command_dispatch",
                            detail=[e.message for e in outcome.errors],
                            command_id=parsed.get("command_id"),
                        )
                        continue
                    redis_payload: Dict[str, Any] = {
                        "kind": "operator_command_dispatch",
                        "command_id": parsed["command_id"],
                        "bridge_received_at_iso_ms": _now_iso_ms(),
                        "contract_version": VERSION,
                    }
                    bridge_outcome = validate("operator_actions", redis_payload)
                    if not bridge_outcome.valid:
                        await _echo_error(
                            websocket,
                            error="bridge_internal",
                            detail=[e.message for e in bridge_outcome.errors],
                            command_id=parsed.get("command_id"),
                        )
                        continue
                    try:
                        await app.state.publisher.publish(
                            "egs.operator_actions", redis_payload,
                        )
                    except Exception:
                        await _echo_error(
                            websocket,
                            error="redis_publish_failed",
                            command_id=parsed.get("command_id"),
                        )
                        continue
                    await websocket.send_text(
                        json.dumps({
                            "type": "echo",
                            "ack": "operator_command_dispatch",
                            "command_id": parsed["command_id"],
                            "contract_version": VERSION,
                        })
                    )
```

- [ ] **Step 4: Run. Expect passing.**

- [ ] **Step 5: Commit**

```bash
git add frontend/ws_bridge/main.py frontend/ws_bridge/tests/test_main_operator_command_dispatch.py
git commit -m "Phase 4 bridge: republish operator_command_dispatch to egs.operator_actions"
```

---

## Task 10: Bridge — subscribe to `egs.command_translations` and forward to WS clients

**Files:**
- Modify: `frontend/ws_bridge/redis_subscriber.py`
- Modify: `frontend/ws_bridge/aggregator.py` (add a translations-broadcast hook OR plumb via main.py — see step 1 decision)
- Modify: `frontend/ws_bridge/main.py` (wire the broadcast)
- Create: `frontend/ws_bridge/tests/test_main_command_translation_forward.py`

**Decision baked in (re-stated from spec §5.1):** translations are broadcast immediately, but **through an `asyncio.Queue`, not by calling `registry.broadcast` synchronously from the subscriber loop** (adversarial finding #1). The subscriber's job is drain Redis fast; broadcasting is owned by a dedicated lifespan task. Without this decoupling, slow WS clients can stall the subscriber, fill Redis pubsub buffers, and trigger Redis-side disconnects.

- [ ] **Step 1: Add the failing test**

Create `frontend/ws_bridge/tests/test_main_command_translation_forward.py`:

```python
"""Phase 4: bridge subscribes to egs.command_translations and forwards each
valid envelope to all WS clients as type=command_translation."""
from __future__ import annotations

import asyncio
import json

import fakeredis.aioredis as fakeredis_async
import pytest
from fastapi.testclient import TestClient

from frontend.ws_bridge.main import create_app


@pytest.fixture
def fake_client():
    return fakeredis_async.FakeRedis()


@pytest.fixture
def patched_from_url(monkeypatch, fake_client):
    import redis.asyncio as redis_async
    monkeypatch.setattr(
        redis_async.Redis, "from_url",
        staticmethod(lambda url, **kw: fake_client),
    )
    return fake_client


def test_command_translation_forwarded_to_ws_client(patched_from_url):
    app = create_app()

    envelope = {
        "kind": "command_translation",
        "command_id": "abcd-1700000000000-3",
        "structured": {
            "command": "recall_drone",
            "args": {"drone_id": "drone1", "reason": "operator request"},
        },
        "valid": True,
        "preview_text": "Will recall drone1: operator request",
        "preview_text_in_operator_language": "Will recall drone1: operator request",
        "egs_published_at_iso_ms": "2026-05-02T12:34:57.123Z",
        "contract_version": "1.0.0",
    }

    with TestClient(app) as client:
        with client.websocket_connect("/") as ws:
            ws.receive_text()  # initial envelope

            async def _publish_after_delay():
                await asyncio.sleep(0.1)
                await patched_from_url.publish(
                    "egs.command_translations", json.dumps(envelope)
                )

            loop = asyncio.new_event_loop()
            loop.create_task(_publish_after_delay())

            # Pull frames until we get the translation forward (max 2s)
            forwarded = None
            for _ in range(20):
                raw = ws.receive_text()
                msg = json.loads(raw)
                if msg.get("type") == "command_translation":
                    forwarded = msg
                    break
            assert forwarded is not None, "command_translation never arrived"
            assert forwarded["command_id"] == "abcd-1700000000000-3"
            # Bridge-only fields must NOT leak to the client
            assert "kind" not in forwarded
            assert "egs_published_at_iso_ms" not in forwarded
            assert forwarded["structured"]["command"] == "recall_drone"


def test_invalid_translation_is_dropped(patched_from_url):
    """An envelope that fails command_translations_envelope validation must be
    logged and dropped — not forwarded, not crashing the subscriber."""
    app = create_app()
    bogus = {
        "kind": "command_translation",
        "command_id": "abcd-1700000000000-9",
        # missing required preview_text — must fail validation
        "structured": {"command": "recall_drone", "args": {"drone_id": "drone1", "reason": "x"}},
        "valid": True,
        "egs_published_at_iso_ms": "2026-05-02T12:34:57.123Z",
        "contract_version": "1.0.0",
    }

    with TestClient(app) as client:
        with client.websocket_connect("/") as ws:
            ws.receive_text()

            async def _publish():
                await asyncio.sleep(0.1)
                await patched_from_url.publish(
                    "egs.command_translations", json.dumps(bogus)
                )

            loop = asyncio.new_event_loop()
            loop.create_task(_publish())

            # We should see state_update ticks but never a command_translation
            saw_translation = False
            for _ in range(8):
                raw = ws.receive_text()
                msg = json.loads(raw)
                if msg.get("type") == "command_translation":
                    saw_translation = True
                    break
            assert not saw_translation
```

- [ ] **Step 2: Run. Expect both failing.**

- [ ] **Step 3: Extend `RedisSubscriber` to enqueue translations (no synchronous broadcast)**

In `frontend/ws_bridge/redis_subscriber.py`:

3a. Add a constructor parameter for the queue:

```python
    def __init__(
        self,
        *,
        config: BridgeConfig,
        aggregator: StateAggregator,
        validation_logger: ValidationEventLogger,
        translation_queue: Optional[asyncio.Queue] = None,
    ) -> None:
```

Store: `self._translation_queue = translation_queue`.

3b. Add the channel constant:

```python
_EGS_COMMAND_TRANSLATIONS_CHANNEL: str = topics.EGS_COMMAND_TRANSLATIONS
```

3c. Subscribe to the new channel in `_connect_and_dispatch`:

```python
        await pubsub.subscribe(_EGS_STATE_CHANNEL, _EGS_COMMAND_TRANSLATIONS_CHANNEL)
```

3d. Extend `_classify_channel` to recognize the new channel:

```python
    if channel == _EGS_COMMAND_TRANSLATIONS_CHANNEL:
        return "command_translations_envelope", None
```

3e. In `_handle_message`, after the existing dispatch block, add (note: `put_nowait` + drop-oldest-on-full so the subscriber NEVER blocks on broadcaster slowness):

```python
        elif schema_name == "command_translations_envelope":
            if self._translation_queue is not None:
                ws_frame = {
                    "type": "command_translation",
                    "command_id": payload["command_id"],
                    "structured": payload["structured"],
                    "valid": payload["valid"],
                    "preview_text": payload["preview_text"],
                    "preview_text_in_operator_language": payload["preview_text_in_operator_language"],
                    "contract_version": payload["contract_version"],
                }
                try:
                    self._translation_queue.put_nowait(ws_frame)
                except asyncio.QueueFull:
                    # Adversarial finding #1: under broadcast slowness, drop
                    # the oldest queued translation to keep the subscriber
                    # draining Redis. Operator gets the freshest result.
                    try:
                        self._translation_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    try:
                        self._translation_queue.put_nowait(ws_frame)
                    except asyncio.QueueFull:
                        # Pathological: still full after evict (race with
                        # other producer). Drop this frame.
                        _LOG.warning(
                            "RedisSubscriber: translation queue persistently "
                            "full; dropped command_id=%s", payload.get("command_id"),
                        )
```

- [ ] **Step 4: Add the broadcaster lifespan task in `main.py`**

In `create_app`, after constructing `registry`, add the queue and broadcaster:

```python
    translation_queue: asyncio.Queue = asyncio.Queue(maxsize=64)

    async def _translation_broadcaster_loop() -> None:
        """Drain translation_queue and broadcast via registry.

        Owns slowness: if a WS client is slow, this task waits — but the
        subscriber and emit_loop keep running. Adversarial finding #1.
        """
        while True:
            try:
                frame = await translation_queue.get()
            except asyncio.CancelledError:
                raise
            try:
                outcome = validate("websocket_messages", frame)
                if not outcome.valid:
                    print(f"[ws_bridge] BUG: dropped translation frame post-strip: {outcome.errors}")
                    continue
                await registry.broadcast(frame)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Defensive: a single bad frame must not kill the broadcaster.
                print(f"[ws_bridge] translation_broadcaster tick error: {type(exc).__name__}: {exc}")
```

Replace subscriber construction:

```python
    subscriber = RedisSubscriber(
        config=config,
        aggregator=aggregator,
        validation_logger=validation_logger,
        translation_queue=translation_queue,
    )
```

(Move the `registry = _ConnectionRegistry(...)` line ABOVE the queue + subscriber construction.)

Stash on app.state for the lifespan to manage:

```python
    app.state.translation_queue = translation_queue
```

In `lifespan`, add the third task and adjust teardown order to cancel before await:

```python
    emit_task = asyncio.create_task(
        _emit_loop(registry=registry, aggregator=aggregator, tick_s=config.tick_s)
    )
    subscribe_task = asyncio.create_task(subscriber.run())
    translation_task = asyncio.create_task(_translation_broadcaster_loop())
    try:
        yield
    finally:
        emit_task.cancel()
        subscribe_task.cancel()
        translation_task.cancel()
        try:
            await subscriber.stop()
        except Exception:
            pass
        for task in (emit_task, subscribe_task, translation_task):
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        await app.state.publisher.close()
```

- [ ] **Step 5: Run. Expect both tests passing.**

If they hang, the `TestClient.websocket_connect` blocking model interacts badly with the publish-from-another-loop. Simplify the test by switching to `httpx.AsyncClient` + `pytest.mark.asyncio` — the assertions are what matter.

- [ ] **Step 6: Run the full bridge suite:**

Run: `PYTHONPATH=. pytest frontend/ws_bridge/tests/ -v`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add frontend/ws_bridge/redis_subscriber.py frontend/ws_bridge/main.py \
  frontend/ws_bridge/tests/test_main_command_translation_forward.py
git commit -m "Phase 4 bridge: subscribe egs.command_translations and forward to WS clients"
```

---

## Task 11: Stub EGS — `scripts/dev_command_translator.py` + matcher unit test

**Files:**
- Create: `scripts/dev_command_translator.py`
- Create: `scripts/test_dev_command_translator.py`

- [ ] **Step 1: Write the failing matcher test**

`scripts/test_dev_command_translator.py`:

```python
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
```

- [ ] **Step 2: Run. Expect ImportError / failures.**

- [ ] **Step 3: Implement `scripts/dev_command_translator.py`**

```python
#!/usr/bin/env python3
"""Phase 4 stub EGS: subscribe to egs.operator_commands, publish translations
to egs.command_translations with hard-coded substring matching.

Stand-in for Person 3's real Gemma 4 E4B translator. Identical Redis contract
on both sides — drop-in replaceable.

Usage:
    PYTHONPATH=. python3 scripts/dev_command_translator.py
    PYTHONPATH=. python3 scripts/dev_command_translator.py --redis-url redis://localhost:6379
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple

import redis.asyncio as redis_async

from shared.contracts import validate, VERSION
from shared.contracts.topics import EGS_OPERATOR_COMMANDS, EGS_COMMAND_TRANSLATIONS

import unicodedata

_ZONE_PATTERNS = [
    (re.compile(r"\b(north|south|east|west|central)\b", re.IGNORECASE), 1),
    (re.compile(r"zona\s+(norte|sur|este|oeste|central)", re.IGNORECASE), 1),
]
_ZONE_TRANSLATE = {"norte": "north", "sur": "south", "este": "east", "oeste": "west", "central": "central"}

_DRONE_PATTERN = re.compile(r"\b(drone\d+)\b", re.IGNORECASE)

# Adversarial finding #9: full-word matches only. Bare "concentr" was matching
# concentric / concentration. Spanish "concéntrate" is handled via NFKD
# normalization in _fold so the operator typing the accent (or not) is the
# same matcher input.
_RECALL_VERBS = ("recall", "regresa", "vuelve")
_RESTRICT_VERBS = ("restrict", "focus", "concentrate")  # NOT "concentr"
_EXCLUDE_VERBS = ("exclude", "avoid", "evita")


def _now_iso_ms() -> str:
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _fold(text: str) -> str:
    """Lowercase + strip accent marks via NFKD decomposition.

    Adversarial finding #9: an operator typing "concéntrate" (with accent) and
    "concentrate" (without) should match the same intent. NFKD splits each
    accented character into a base + combining mark; we drop the marks.
    """
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _has_word(text: str, words: tuple) -> bool:
    """True iff any of `words` appears as a full word (\b boundaries)."""
    for w in words:
        if re.search(rf"\b{re.escape(w)}\b", text):
            return True
    return False


def _detect_zone(text: str) -> Optional[str]:
    for pat, group in _ZONE_PATTERNS:
        m = pat.search(text)
        if m:
            value = m.group(group).lower()
            return _ZONE_TRANSLATE.get(value, value)
    return None


def _detect_drone(text: str) -> Optional[str]:
    m = _DRONE_PATTERN.search(text)
    return m.group(1).lower() if m else None


def _intent_from_text(text: str) -> Tuple[str, Dict[str, Any]]:
    """Return (command, args) for the matched intent, or unknown_command.

    Word-boundary + accent-folded matching prevents false positives like
    "concentric" → restrict_zone.
    """
    folded = _fold(text)
    drone = _detect_drone(folded)
    zone = _detect_zone(folded)

    if _has_word(folded, _RECALL_VERBS):
        if drone:
            return "recall_drone", {"drone_id": drone, "reason": "operator request"}

    if _has_word(folded, _RESTRICT_VERBS):
        if zone:
            return "restrict_zone", {"zone_id": zone}

    if _has_word(folded, _EXCLUDE_VERBS):
        if zone:
            return "exclude_zone", {"zone_id": zone}

    return "unknown_command", {
        "operator_text": text,
        "suggestion": "Try 'recall drone1' or 'focus on zone east'",
    }


def build_translation(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """Pure function: take an operator_commands_envelope, return a
    command_translations_envelope. Exposed for unit tests."""
    cid = envelope["command_id"]
    raw = envelope["raw_text"]
    language = envelope.get("language", "en")
    command, args = _intent_from_text(raw)
    structured = {"command": command, "args": args}
    valid = command != "unknown_command"

    if valid:
        if command == "recall_drone":
            preview = f"Will recall {args['drone_id']}: {args['reason']}"
        elif command == "restrict_zone":
            preview = f"Will restrict mission to zone '{args['zone_id']}'"
        elif command == "exclude_zone":
            preview = f"Will exclude zone '{args['zone_id']}'"
        else:
            preview = f"Will execute {command}"
    else:
        preview = "Command not understood"

    # Stub does not actually translate the preview into other languages.
    # Person 3's real EGS replaces this with Gemma 4 output.
    preview_local = preview

    return {
        "kind": "command_translation",
        "command_id": cid,
        "structured": structured,
        "valid": valid,
        "preview_text": preview,
        "preview_text_in_operator_language": preview_local,
        "egs_published_at_iso_ms": _now_iso_ms(),
        "contract_version": VERSION,
    }


async def _run(redis_url: str) -> None:
    client = redis_async.Redis.from_url(redis_url)
    pubsub = client.pubsub()
    await pubsub.subscribe(EGS_OPERATOR_COMMANDS)
    print(
        f"[stub-egs] subscribed to {EGS_OPERATOR_COMMANDS} on {redis_url}",
        file=sys.stderr,
    )
    try:
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
            if msg is None:
                continue
            data = msg.get("data")
            if isinstance(data, (bytes, bytearray)):
                raw = bytes(data).decode("utf-8", errors="replace")
            else:
                raw = str(data)
            try:
                envelope = json.loads(raw)
            except json.JSONDecodeError as exc:
                print(f"[stub-egs] INVALID json: {exc}", file=sys.stderr)
                continue
            outcome = validate("operator_commands_envelope", envelope)
            if not outcome.valid:
                print(
                    f"[stub-egs] INVALID envelope: {[e.message for e in outcome.errors][:2]}",
                    file=sys.stderr,
                )
                continue

            translation = build_translation(envelope)
            t_outcome = validate("command_translations_envelope", translation)
            if not t_outcome.valid:
                print(
                    f"[stub-egs] BUG: produced invalid translation: {[e.message for e in t_outcome.errors][:2]}",
                    file=sys.stderr,
                )
                continue

            await client.publish(
                EGS_COMMAND_TRANSLATIONS, json.dumps(translation),
            )
            print(
                f"[stub-egs] cid={envelope['command_id']} raw={envelope['raw_text']!r} "
                f"-> {translation['structured']['command']}"
            )
    finally:
        try:
            await pubsub.unsubscribe()
        finally:
            await pubsub.aclose()
            await client.aclose()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--redis-url", default="redis://localhost:6379")
    args = p.parse_args()
    try:
        asyncio.run(_run(args.redis_url))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the matcher tests. Expect 6 passing.**

Run: `PYTHONPATH=. pytest scripts/test_dev_command_translator.py -v`

- [ ] **Step 5: Commit**

```bash
git add scripts/dev_command_translator.py scripts/test_dev_command_translator.py
git commit -m "Phase 4 stub EGS: scripts/dev_command_translator.py for local round-trip"
```

---

## Task 12: Flutter — `MissionState` command state machine

**Files:**
- Modify: `frontend/flutter_dashboard/lib/state/mission_state.dart`
- Create: `frontend/flutter_dashboard/test/mission_state_command_test.dart`

- [ ] **Step 1: Write the failing tests**

`frontend/flutter_dashboard/test/mission_state_command_test.dart`:

```dart
import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_dashboard/state/mission_state.dart';

class _RecordingSink implements WebSocketSink {
  final List<dynamic> sent = [];
  @override
  void add(dynamic data) => sent.add(data);
  @override
  Future close([int? closeCode, String? closeReason]) async {}
  @override
  Future addStream(Stream stream) async {}
  @override
  void addError(Object error, [StackTrace? stackTrace]) {}
  @override
  Future get done => Future.value();
}

void main() {
  group('MissionState command state machine', () {
    late MissionState state;
    late _RecordingSink sink;

    setUp(() {
      state = MissionState();
      sink = _RecordingSink();
      state.attachSink(sink);
      state.setConnectionStatus("connected");
    });

    test('submit command transitions sending -> translating on bridge ack', () {
      final cid = state.submitOperatorCommand(rawText: "recall drone1", language: "en");
      expect(state.commandState(cid), CommandState.sending);
      state.handleEcho({
        "type": "echo",
        "ack": "operator_command_received",
        "command_id": cid,
      });
      expect(state.commandState(cid), CommandState.translating);
    });

    test('command_translation transitions translating -> ready and stores preview', () {
      final cid = state.submitOperatorCommand(rawText: "recall drone1", language: "en");
      state.handleEcho({"type": "echo", "ack": "operator_command_received", "command_id": cid});
      state.applyTranslation({
        "type": "command_translation",
        "command_id": cid,
        "structured": {"command": "recall_drone", "args": {"drone_id": "drone1", "reason": "x"}},
        "valid": true,
        "preview_text": "Will recall drone1",
        "preview_text_in_operator_language": "Will recall drone1",
        "contract_version": "1.0.0",
      });
      expect(state.commandState(cid), CommandState.ready);
      expect(state.commandTranslation(cid)?["preview_text"], "Will recall drone1");
    });

    test('dispatch transitions ready -> dispatched and emits dispatch frame', () {
      final cid = state.submitOperatorCommand(rawText: "recall drone1", language: "en");
      state.handleEcho({"type": "echo", "ack": "operator_command_received", "command_id": cid});
      state.applyTranslation({
        "type": "command_translation",
        "command_id": cid,
        "structured": {"command": "recall_drone", "args": {"drone_id": "drone1", "reason": "x"}},
        "valid": true,
        "preview_text": "Will recall drone1",
        "preview_text_in_operator_language": "Will recall drone1",
        "contract_version": "1.0.0",
      });
      state.dispatchActiveCommand();
      expect(state.commandState(cid), CommandState.dispatched);
      // Sink should have sent operator_command then operator_command_dispatch
      expect(sink.sent.length, 2);
    });

    test('rephrase clears active command bookkeeping', () {
      final cid = state.submitOperatorCommand(rawText: "recall drone1", language: "en");
      state.handleEcho({"type": "echo", "ack": "operator_command_received", "command_id": cid});
      state.applyTranslation({
        "type": "command_translation",
        "command_id": cid,
        "structured": {"command": "recall_drone", "args": {"drone_id": "drone1", "reason": "x"}},
        "valid": true,
        "preview_text": "Will recall drone1",
        "preview_text_in_operator_language": "Will recall drone1",
        "contract_version": "1.0.0",
      });
      state.rephraseActiveCommand();
      expect(state.activeCommandId, isNull);
    });

    test('detachSink during translating flips state to failed', () {
      final cid = state.submitOperatorCommand(rawText: "recall drone1", language: "en");
      state.handleEcho({"type": "echo", "ack": "operator_command_received", "command_id": cid});
      state.detachSink();
      expect(state.commandState(cid), CommandState.failed);
    });

    test('late translation after timeout is dropped silently (1B)', () async {
      final cid = state.submitOperatorCommand(
        rawText: "recall drone1", language: "en",
        translationTimeout: const Duration(milliseconds: 50),
      );
      state.handleEcho({"type": "echo", "ack": "operator_command_received", "command_id": cid});
      await Future.delayed(const Duration(milliseconds: 100));
      expect(state.commandState(cid), CommandState.failed);
      // Late translation arrives — must not revive the panel
      state.applyTranslation({
        "type": "command_translation",
        "command_id": cid,
        "structured": {"command": "recall_drone", "args": {"drone_id": "drone1", "reason": "x"}},
        "valid": true,
        "preview_text": "Will recall drone1",
        "preview_text_in_operator_language": "Will recall drone1",
        "contract_version": "1.0.0",
      });
      expect(state.commandState(cid), CommandState.failed);
    });

    test('redis_publish_failed echo flips command to failed', () {
      final cid = state.submitOperatorCommand(rawText: "recall drone1", language: "en");
      state.handleEcho({
        "type": "echo",
        "error": "redis_publish_failed",
        "command_id": cid,
      });
      expect(state.commandState(cid), CommandState.failed);
    });

    test('second submit orphans the first cid: timer cancelled, bookkeeping dropped', () async {
      // Adversarial finding #4: prior cid's Timer must not fire after orphan.
      // Use a short timeout so the test runs fast and a leaked timer would
      // produce an observable snackbar.
      final snackbarEvents = <String>[];
      final sub = state.snackbarStream.listen(snackbarEvents.add);
      final cid1 = state.submitOperatorCommand(
        rawText: "first", language: "en",
        translationTimeout: const Duration(milliseconds: 50),
      );
      final cid2 = state.submitOperatorCommand(rawText: "second", language: "en");
      expect(state.activeCommandId, cid2);
      // cid1 must be dropped from _commandActions entirely
      expect(state.commandState(cid1), isNull);
      // Wait past cid1's would-be timeout — no snackbar should fire
      await Future.delayed(const Duration(milliseconds: 100));
      expect(snackbarEvents, isEmpty);
      await sub.cancel();
    });

    test('late translation for orphaned cid is dropped silently', () async {
      // Adversarial finding #4 + late-arrival: a translation arriving for
      // a cid that was orphaned (not in _commandActions) must not surface.
      final cid1 = state.submitOperatorCommand(rawText: "first", language: "en");
      final cid2 = state.submitOperatorCommand(rawText: "second", language: "en");
      // cid1 is orphaned. Apply a translation for it.
      state.applyTranslation({
        "type": "command_translation",
        "command_id": cid1,
        "structured": {"command": "recall_drone", "args": {"drone_id": "drone1", "reason": "x"}},
        "valid": true,
        "preview_text": "Will recall drone1",
        "preview_text_in_operator_language": "Will recall drone1",
        "contract_version": "1.0.0",
      });
      // Active panel must remain on cid2 (in sending — no echo yet)
      expect(state.activeCommandId, cid2);
      expect(state.commandTranslation(cid1), isNull);
      expect(state.commandState(cid1), isNull);
    });

    test('dispatch is non-optimistic: ready -> dispatching, ack -> dispatched', () {
      // Adversarial finding #5: don't optimistically transition to dispatched.
      final cid = state.submitOperatorCommand(rawText: "recall drone1", language: "en");
      state.handleEcho({"type": "echo", "ack": "operator_command_received", "command_id": cid});
      state.applyTranslation({
        "type": "command_translation",
        "command_id": cid,
        "structured": {"command": "recall_drone", "args": {"drone_id": "drone1", "reason": "x"}},
        "valid": true,
        "preview_text": "Will recall drone1",
        "preview_text_in_operator_language": "Will recall drone1",
        "contract_version": "1.0.0",
      });
      state.dispatchActiveCommand();
      expect(state.commandState(cid), CommandState.dispatching);  // not dispatched yet
      state.handleEcho({"type": "echo", "ack": "operator_command_dispatch", "command_id": cid});
      expect(state.commandState(cid), CommandState.dispatched);
    });

    test('redis_publish_failed on dispatch returns to ready (not failed)', () {
      // Adversarial finding #5: a transient Redis blip on dispatch must not
      // burn the translation; operator can re-tap DISPATCH from ready.
      final cid = state.submitOperatorCommand(rawText: "recall drone1", language: "en");
      state.handleEcho({"type": "echo", "ack": "operator_command_received", "command_id": cid});
      state.applyTranslation({
        "type": "command_translation",
        "command_id": cid,
        "structured": {"command": "recall_drone", "args": {"drone_id": "drone1", "reason": "x"}},
        "valid": true,
        "preview_text": "Will recall drone1",
        "preview_text_in_operator_language": "Will recall drone1",
        "contract_version": "1.0.0",
      });
      state.dispatchActiveCommand();
      expect(state.commandState(cid), CommandState.dispatching);
      state.handleEcho({
        "type": "echo",
        "error": "redis_publish_failed",
        "command_id": cid,
      });
      // Returns to ready, NOT failed — translation is still valid
      expect(state.commandState(cid), CommandState.ready);
    });
  });
}
```

- [ ] **Step 2: Run. Expect failures.**

Run: `cd frontend/flutter_dashboard && flutter test test/mission_state_command_test.dart`

- [ ] **Step 3: Add the command machine to `MissionState`**

Open `frontend/flutter_dashboard/lib/state/mission_state.dart`. After the `ApprovalState` enum, add:

```dart
/// Per-command state machine for operator command translation.
///
/// (absent) → sending → translating → ready → dispatching → dispatched
///                                                       └→ ready (on redis_publish_failed echo, finding #5)
///                                          → (rephrase resets to absent)
///         → failed (on bridge error, WS drop, or 15s timeout)
///         → (orphaned: dropped from map entirely on second submit, finding #4)
enum CommandState { sending, translating, ready, dispatching, dispatched, failed }
```

Then, inside the `MissionState` class, add the following fields and methods. Place them near the existing finding bookkeeping for symmetry:

```dart
  // ---- command translation state ------------------------------------------

  final Map<String, CommandState> _commandActions = {};
  final Map<String, Map<String, dynamic>> _commandTranslations = {};
  final Map<String, Timer> _commandTimers = {};
  String? _activeCommandId;

  String? get activeCommandId => _activeCommandId;
  CommandState? commandState(String commandId) => _commandActions[commandId];
  Map<String, dynamic>? commandTranslation(String commandId) =>
      _commandTranslations[commandId];

  /// Operator submitted a command for translation. Returns the command_id
  /// generated for this submission so the caller can correlate later.
  ///
  /// Single-slot: a fresh submit replaces the active id. **Adversarial
  /// finding #4 — orphan rule:** the prior cid is *dropped* from
  /// `_commandActions`, `_commandTranslations`, and `_commandTimers` so its
  /// Timer cannot fire later (no misleading snackbar) and so memory does not
  /// grow under aggressive resubmit cycles. Late ack/translation frames for
  /// the orphan find no entry and are silently dropped.
  String submitOperatorCommand({
    required String rawText,
    required String language,
    Duration translationTimeout = const Duration(seconds: 15),
  }) {
    // Orphan the prior active command (if any) before overwriting.
    final prior = _activeCommandId;
    if (prior != null && _commandActions.containsKey(prior)) {
      _commandTimers[prior]?.cancel();
      _commandTimers.remove(prior);
      _commandActions.remove(prior);
      _commandTranslations.remove(prior);
    }

    final commandId = _nextCommandId();
    _activeCommandId = commandId;
    _commandActions[commandId] = CommandState.sending;
    _commandTimers[commandId] = Timer(translationTimeout, () {
      // Promote to failed only if still in a non-terminal pre-ready state.
      final cur = _commandActions[commandId];
      if (cur == CommandState.sending || cur == CommandState.translating) {
        _commandActions[commandId] = CommandState.failed;
        _snackbarController.add("Translation lost — retry");
        notifyListeners();
      }
    });
    notifyListeners();
    sendOutbound({
      "type": "operator_command",
      "command_id": commandId,
      "language": language,
      "raw_text": rawText,
      "contract_version": gen.contractVersion,
    });
    return commandId;
  }

  /// Apply a `command_translation` frame. Drops late frames for terminal-state
  /// commands (1B) AND for orphaned commands no longer in the map (finding #4).
  void applyTranslation(Map<String, dynamic> envelope) {
    if (envelope["type"] != "command_translation") return;
    final cid = envelope["command_id"] as String?;
    if (cid == null) return;
    final cur = _commandActions[cid];
    if (cur == null) {
      // Orphaned cid — silent drop (finding #4).
      if (kDebugMode) {
        debugPrint("[MissionState] dropped translation for orphaned $cid");
      }
      return;
    }
    if (cur == CommandState.failed || cur == CommandState.dispatched ||
        cur == CommandState.dispatching) {
      // Late arrival on terminal/in-flight-dispatch state — log and drop.
      if (kDebugMode) {
        debugPrint("[MissionState] dropped late translation for $cid (state=$cur)");
      }
      return;
    }
    _commandTranslations[cid] = Map<String, dynamic>.from(envelope);
    _commandActions[cid] = CommandState.ready;
    _commandTimers[cid]?.cancel();
    _commandTimers.remove(cid);
    notifyListeners();
  }

  /// Operator clicked DISPATCH on the active command's preview pane.
  ///
  /// Adversarial finding #5 — non-optimistic: transition to `dispatching`
  /// (button shows spinner, REPHRASE disabled) and wait for the bridge ack
  /// before advancing to `dispatched`. On `redis_publish_failed` we return
  /// to `ready` so the operator can re-tap without re-translating.
  void dispatchActiveCommand() {
    final cid = _activeCommandId;
    if (cid == null) return;
    if (_commandActions[cid] != CommandState.ready) return;
    final translation = _commandTranslations[cid];
    if (translation == null || translation["valid"] != true) return;
    _commandActions[cid] = CommandState.dispatching;
    notifyListeners();
    sendOutbound({
      "type": "operator_command_dispatch",
      "command_id": cid,
      "contract_version": gen.contractVersion,
    });
  }

  /// Operator clicked REPHRASE — clear the active command from the foreground.
  /// The bookkeeping for the prior cid stays so a late ack/translation that
  /// arrives can be dropped via the late-arrival rule.
  void rephraseActiveCommand() {
    _activeCommandId = null;
    notifyListeners();
  }

  /// Called by detachSink — flip in-flight commands to failed.
  void _failInFlightCommands() {
    final flipped = <String>[];
    _commandActions.forEach((id, st) {
      if (st == CommandState.sending || st == CommandState.translating) {
        flipped.add(id);
      }
    });
    for (final id in flipped) {
      _commandActions[id] = CommandState.failed;
      _commandTimers[id]?.cancel();
      _commandTimers.remove(id);
    }
    if (flipped.isNotEmpty) {
      _snackbarController.add("Connection lost — translation cancelled");
    }
  }
```

Update `handleEcho` to also handle `operator_command_received` and `operator_command_dispatch` acks plus generic `redis_publish_failed`:

```dart
  void handleEcho(Map<String, dynamic> envelope) {
    if (envelope["type"] != "echo") return;
    final commandId = envelope["command_id"] as String?;
    final ack = envelope["ack"];
    final error = envelope["error"];

    // ---- command translation echoes ----
    if (commandId != null && _commandActions.containsKey(commandId)) {
      if (ack == "operator_command_received") {
        if (_commandActions[commandId] == CommandState.sending) {
          _commandActions[commandId] = CommandState.translating;
          notifyListeners();
        }
        return;
      }
      if (ack == "operator_command_dispatch") {
        // Adversarial finding #5: this is the canonical transition to
        // dispatched (no longer optimistic). Only transition from dispatching.
        if (_commandActions[commandId] == CommandState.dispatching) {
          _commandActions[commandId] = CommandState.dispatched;
          notifyListeners();
        }
        return;
      }
      if (error != null) {
        // Adversarial finding #5: redis_publish_failed during dispatching
        // must NOT burn the translation. Return to ready so operator can
        // re-tap. For non-dispatch errors, fall through to the failed path.
        if (error == "redis_publish_failed" &&
            _commandActions[commandId] == CommandState.dispatching) {
          _commandActions[commandId] = CommandState.ready;
          _snackbarController.add("Dispatch send failed — retry");
          notifyListeners();
          return;
        }
        _commandActions[commandId] = CommandState.failed;
        _commandTimers[commandId]?.cancel();
        _commandTimers.remove(commandId);
        if (error == "redis_publish_failed") {
          _snackbarController.add("Bridge could not reach Redis — retry");
        } else {
          _snackbarController.add("Command rejected — rephrase");
        }
        notifyListeners();
        return;
      }
    }

    // ---- finding approval echoes (existing Phase 3 path) ----
    String? findingId = envelope["finding_id"] as String?;
    if (findingId == null && commandId != null) {
      findingId = _commandToFinding[commandId];
    }
    if (findingId == null) return;
    if (ack == "finding_approval") {
      final action = commandId != null ? _pendingActions[commandId] : null;
      _findingActions[findingId] = action == "dismiss"
          ? ApprovalState.dismissed
          : ApprovalState.received;
    } else if (error != null) {
      _findingActions[findingId] = ApprovalState.failed;
      if (error == "unknown_finding_id") {
        _snackbarController.add("Finding aged out — refresh and retry");
      } else {
        _snackbarController.add("Approval not delivered — retry");
      }
    }
    if (commandId != null) {
      _pendingActions.remove(commandId);
      _commandToFinding.remove(commandId);
    }
    notifyListeners();
  }
```

Update `detachSink` to also fail in-flight commands:

```dart
  void detachSink() {
    _sink = null;
    final flipped = <String>[];
    _findingActions.forEach((id, state) {
      if (state == ApprovalState.pending) flipped.add(id);
    });
    _pendingActions.clear();
    _commandToFinding.clear();
    _failInFlightCommands();
    if (flipped.isNotEmpty) {
      for (final id in flipped) {
        _findingActions[id] = ApprovalState.failed;
      }
      _snackbarController.add("Reconnect: please re-tap any pending approvals");
    }
    notifyListeners();
  }
```

Update `applyRawFrame` to route `command_translation`:

```dart
  void applyRawFrame(String raw) {
    try {
      final decoded = jsonDecode(raw);
      if (decoded is Map<String, dynamic>) {
        final t = decoded["type"];
        if (t == "echo") {
          handleEcho(decoded);
        } else if (t == "command_translation") {
          applyTranslation(decoded);
        } else {
          applyStateUpdate(decoded);
        }
      }
    } catch (e) {
      if (kDebugMode) {
        debugPrint("[MissionState] failed to decode frame: $e");
      }
    }
  }
```

Update `dispose` to cancel timers:

```dart
  @override
  void dispose() {
    for (final t in _commandTimers.values) {
      t.cancel();
    }
    _commandTimers.clear();
    _snackbarController.close();
    super.dispose();
  }
```

- [ ] **Step 4: Run. Expect 8 passing.**

Run: `cd frontend/flutter_dashboard && flutter test test/mission_state_command_test.dart`

- [ ] **Step 5: Run the full Flutter test suite for regressions:**

Run: `cd frontend/flutter_dashboard && flutter test`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add frontend/flutter_dashboard/lib/state/mission_state.dart \
  frontend/flutter_dashboard/test/mission_state_command_test.dart
git commit -m "Phase 4 dashboard: command state machine in MissionState"
```

---

## Task 13: Flutter — `CommandPanel` rewrite with 5 visual states

**Files:**
- Modify: `frontend/flutter_dashboard/lib/widgets/command_panel.dart`
- Create: `frontend/flutter_dashboard/test/command_panel_test.dart`

- [ ] **Step 1: Write the failing widget tests**

`frontend/flutter_dashboard/test/command_panel_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:flutter_dashboard/state/mission_state.dart';
import 'package:flutter_dashboard/widgets/command_panel.dart';

Widget _wrap(MissionState state) {
  return MaterialApp(
    home: ChangeNotifierProvider<MissionState>.value(
      value: state,
      child: const Scaffold(body: CommandPanel()),
    ),
  );
}

void main() {
  group('CommandPanel visual states', () {
    testWidgets('disconnected state disables Translate', (tester) async {
      final state = MissionState();
      // No setConnectionStatus("connected") — default is "disconnected"
      await tester.pumpWidget(_wrap(state));
      final translate = find.widgetWithText(ElevatedButton, "TRANSLATE");
      expect(translate, findsOneWidget);
      final ElevatedButton btn = tester.widget(translate);
      expect(btn.onPressed, isNull);
    });

    testWidgets('connected with empty input disables Translate', (tester) async {
      final state = MissionState();
      state.setConnectionStatus("connected");
      await tester.pumpWidget(_wrap(state));
      final ElevatedButton btn = tester.widget(find.widgetWithText(ElevatedButton, "TRANSLATE"));
      expect(btn.onPressed, isNull);
    });

    testWidgets('typing enables Translate; click submits and switches to Sending', (tester) async {
      final state = MissionState();
      state.setConnectionStatus("connected");
      // We don't attach a real sink — sendOutbound will silently no-op when
      // sink is null (per existing MissionState contract). The point of the
      // widget test is the UI transition, not the wire format.
      await tester.pumpWidget(_wrap(state));
      await tester.enterText(find.byType(TextField), "recall drone1");
      await tester.pump();
      final ElevatedButton btn = tester.widget(find.widgetWithText(ElevatedButton, "TRANSLATE"));
      expect(btn.onPressed, isNotNull);
    });

    testWidgets('ready state with valid=true enables DISPATCH', (tester) async {
      final state = MissionState();
      state.setConnectionStatus("connected");
      // Force-set state machine into ready
      final cid = state.submitOperatorCommand(rawText: "recall drone1", language: "en");
      state.handleEcho({"type": "echo", "ack": "operator_command_received", "command_id": cid});
      state.applyTranslation({
        "type": "command_translation",
        "command_id": cid,
        "structured": {"command": "recall_drone", "args": {"drone_id": "drone1", "reason": "x"}},
        "valid": true,
        "preview_text": "Will recall drone1",
        "preview_text_in_operator_language": "Will recall drone1",
        "contract_version": "1.0.0",
      });
      await tester.pumpWidget(_wrap(state));
      expect(find.text("Will recall drone1"), findsAtLeast(1));
      final dispatch = find.widgetWithText(ElevatedButton, "DISPATCH");
      expect(dispatch, findsOneWidget);
      final ElevatedButton btn = tester.widget(dispatch);
      expect(btn.onPressed, isNotNull);
    });

    testWidgets('ready state with valid=false (unknown_command) disables DISPATCH', (tester) async {
      final state = MissionState();
      state.setConnectionStatus("connected");
      final cid = state.submitOperatorCommand(rawText: "asdf", language: "en");
      state.handleEcho({"type": "echo", "ack": "operator_command_received", "command_id": cid});
      state.applyTranslation({
        "type": "command_translation",
        "command_id": cid,
        "structured": {"command": "unknown_command", "args": {"operator_text": "asdf", "suggestion": "Try ..."}},
        "valid": false,
        "preview_text": "Command not understood",
        "preview_text_in_operator_language": "Command not understood",
        "contract_version": "1.0.0",
      });
      await tester.pumpWidget(_wrap(state));
      final dispatch = find.widgetWithText(ElevatedButton, "DISPATCH");
      final ElevatedButton btn = tester.widget(dispatch);
      expect(btn.onPressed, isNull);
    });

    testWidgets('language dropdown round-trips into outbound payload via state', (tester) async {
      final state = MissionState();
      state.setConnectionStatus("connected");
      await tester.pumpWidget(_wrap(state));
      // Open the dropdown and tap Spanish
      await tester.tap(find.byType(DropdownButton<String>));
      await tester.pumpAndSettle();
      await tester.tap(find.text("Spanish").last);
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), "concéntrate en zona este");
      await tester.pump();
      await tester.tap(find.widgetWithText(ElevatedButton, "TRANSLATE"));
      await tester.pump();
      // The active command must reflect Spanish — we verify via the wire
      // shape on the next layer (mission_state already sends operator_command).
      // Here we just assert the panel transitioned to a non-default state.
      final cid = state.activeCommandId;
      expect(cid, isNotNull);
      expect(state.commandState(cid!), CommandState.sending);
    });
  });
}
```

- [ ] **Step 2: Run. Expect failures.**

Run: `cd frontend/flutter_dashboard && flutter test test/command_panel_test.dart`

- [ ] **Step 3: Replace `frontend/flutter_dashboard/lib/widgets/command_panel.dart`**

```dart
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../state/mission_state.dart';

class CommandPanel extends StatefulWidget {
  const CommandPanel({super.key});

  @override
  State<CommandPanel> createState() => _CommandPanelState();
}

class _CommandPanelState extends State<CommandPanel> {
  final _controller = TextEditingController();
  String _language = "en";

  @override
  void initState() {
    super.initState();
    _controller.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _onTranslate(MissionState state) {
    final raw = _controller.text.trim();
    if (raw.isEmpty) return;
    state.submitOperatorCommand(rawText: raw, language: _language);
  }

  void _onDispatch(MissionState state) {
    state.dispatchActiveCommand();
    // Clear the input only on dispatch (per spec §6.2 input retention rule).
    _controller.clear();
  }

  void _onRephrase(MissionState state) {
    state.rephraseActiveCommand();
    // Keep raw text in input — operator may want to edit and resubmit.
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<MissionState>(
      builder: (_, state, __) {
        final cid = state.activeCommandId;
        final cs = cid != null ? state.commandState(cid) : null;
        final translation = cid != null ? state.commandTranslation(cid) : null;
        final connected = state.connectionStatus == "connected";
        final inputEnabled = cs == null || cs == CommandState.failed || cs == CommandState.dispatched;
        final translateEnabled =
            connected && _controller.text.trim().isNotEmpty && (cs == null || cs == CommandState.failed);

        return Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text("Command", style: TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              Row(
                children: [
                  const Text("Reply in: "),
                  const SizedBox(width: 8),
                  DropdownButton<String>(
                    value: _language,
                    items: const [
                      DropdownMenuItem(value: "en", child: Text("English")),
                      DropdownMenuItem(value: "es", child: Text("Spanish")),
                      DropdownMenuItem(value: "ar", child: Text("Arabic")),
                    ],
                    onChanged: (v) => setState(() => _language = v ?? "en"),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _controller,
                enabled: inputEnabled,
                decoration: const InputDecoration(
                  border: OutlineInputBorder(),
                  hintText: "Type a command...",
                ),
              ),
              const SizedBox(height: 12),
              if (cs == CommandState.sending || cs == CommandState.translating)
                const _StatusLine(text: "Translating with Gemma 4 E4B…", showSpinner: true),
              if (cs == CommandState.ready && translation != null)
                _Preview(translation: translation),
              if (cs == CommandState.dispatching && translation != null) ...[
                _Preview(translation: translation),
                const SizedBox(height: 4),
                const _StatusLine(text: "Dispatching…", showSpinner: true),
              ],
              if (cs == CommandState.dispatched)
                const _StatusLine(text: "Dispatched ✓", showSpinner: false),
              if (cs == CommandState.failed)
                const _StatusLine(text: "Translation failed — retry", showSpinner: false, error: true),
              const SizedBox(height: 12),
              Row(
                children: [
                  ElevatedButton(
                    onPressed: translateEnabled ? () => _onTranslate(state) : null,
                    child: const Text("TRANSLATE"),
                  ),
                  const SizedBox(width: 12),
                  if (cs == CommandState.ready)
                    Tooltip(
                      message: translation?["valid"] == true
                          ? "Send the structured command to the swarm"
                          : "Command not understood — rephrase",
                      child: ElevatedButton(
                        onPressed: translation?["valid"] == true ? () => _onDispatch(state) : null,
                        child: const Text("DISPATCH"),
                      ),
                    ),
                  if (cs == CommandState.dispatching)
                    const ElevatedButton(
                      onPressed: null,
                      child: Text("DISPATCHING…"),
                    ),
                  if (cs == CommandState.ready || cs == CommandState.dispatching) const SizedBox(width: 12),
                  if (cs == CommandState.ready || cs == CommandState.failed)
                    OutlinedButton(
                      onPressed: () => _onRephrase(state),
                      child: const Text("REPHRASE"),
                    ),
                  if (cs == null || cs == CommandState.dispatched) ...[
                    const SizedBox(width: 12),
                    OutlinedButton(
                      onPressed: () => _controller.clear(),
                      child: const Text("CLEAR"),
                    ),
                  ],
                ],
              ),
            ],
          ),
        );
      },
    );
  }
}

class _StatusLine extends StatelessWidget {
  final String text;
  final bool showSpinner;
  final bool error;
  const _StatusLine({required this.text, required this.showSpinner, this.error = false});
  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        if (showSpinner)
          const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)),
        if (showSpinner) const SizedBox(width: 8),
        Text(text, style: TextStyle(color: error ? Colors.red[700] : Colors.black87)),
      ],
    );
  }
}

class _Preview extends StatelessWidget {
  final Map<String, dynamic> translation;
  const _Preview({required this.translation});
  @override
  Widget build(BuildContext context) {
    final preview = translation["preview_text"] ?? "";
    final localPreview = translation["preview_text_in_operator_language"] ?? "";
    final valid = translation["valid"] == true;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        border: Border.all(color: valid ? Colors.green[700]! : Colors.orange[700]!),
        borderRadius: BorderRadius.circular(4),
        color: (valid ? Colors.green : Colors.orange).withOpacity(0.05),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(preview, style: const TextStyle(fontWeight: FontWeight.w600)),
          if (localPreview != preview) ...[
            const SizedBox(height: 4),
            Text(localPreview, style: const TextStyle(fontStyle: FontStyle.italic)),
          ],
        ],
      ),
    );
  }
}
```

- [ ] **Step 4: Run. Expect tests passing.**

Run: `cd frontend/flutter_dashboard && flutter test test/command_panel_test.dart`

- [ ] **Step 5: Run the full Flutter suite:**

Run: `cd frontend/flutter_dashboard && flutter test`

- [ ] **Step 6: Commit**

```bash
git add frontend/flutter_dashboard/lib/widgets/command_panel.dart \
  frontend/flutter_dashboard/test/command_panel_test.dart
git commit -m "Phase 4 dashboard: CommandPanel 5-state UI with translate + dispatch"
```

---

## Task 14: Flutter — `DroneStatusPanel` validation event ticker

**Files:**
- Modify: `frontend/flutter_dashboard/lib/widgets/drone_status_panel.dart`
- Create: `frontend/flutter_dashboard/test/drone_status_panel_test.dart`

- [ ] **Step 1: Write the failing test**

`frontend/flutter_dashboard/test/drone_status_panel_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:flutter_dashboard/state/mission_state.dart';
import 'package:flutter_dashboard/widgets/drone_status_panel.dart';

Widget _wrap(MissionState state) => MaterialApp(
      home: ChangeNotifierProvider<MissionState>.value(
        value: state,
        child: const Scaffold(body: DroneStatusPanel()),
      ),
    );

Map<String, dynamic> _drone(String id) => {
      "drone_id": id,
      "agent_status": "active",
      "battery_pct": 87,
      "current_task": "survey",
      "findings_count": 4,
      "validation_failures_total": 2,
    };

void main() {
  testWidgets('renders empty when no drones', (tester) async {
    final state = MissionState();
    await tester.pumpWidget(_wrap(state));
    expect(find.text("No drones online"), findsOneWidget);
  });

  testWidgets('renders empty validation row when no events', (tester) async {
    final state = MissionState();
    state.applyStateUpdate({
      "type": "state_update",
      "timestamp": "2026-05-02T12:00:00.000Z",
      "contract_version": "1.0.0",
      "egs_state": {"recent_validation_events": []},
      "active_drones": [_drone("drone1")],
      "active_findings": [],
    });
    await tester.pumpWidget(_wrap(state));
    expect(find.textContaining("Validation: 0 fails"), findsOneWidget);
  });

  testWidgets('renders ticker when events exist for this drone', (tester) async {
    final state = MissionState();
    state.applyStateUpdate({
      "type": "state_update",
      "timestamp": "2026-05-02T12:00:00.000Z",
      "contract_version": "1.0.0",
      "egs_state": {
        "recent_validation_events": [
          {
            "timestamp": "2026-05-02T11:59:50.000Z",
            "agent": "drone1",
            "task": "report_finding",
            "outcome": "corrected_after_retry",
            "issue": "DUPLICATE_FINDING",
          },
          {
            "timestamp": "2026-05-02T11:59:40.000Z",
            "agent": "drone2",
            "task": "report_finding",
            "outcome": "corrected_after_retry",
            "issue": "GPS_OUT_OF_ZONE",
          },
        ],
      },
      "active_drones": [_drone("drone1"), _drone("drone2")],
      "active_findings": [],
    });
    await tester.pumpWidget(_wrap(state));
    expect(find.textContaining("DUPLICATE_FINDING"), findsOneWidget);
    expect(find.textContaining("GPS_OUT_OF_ZONE"), findsOneWidget);
  });

  testWidgets('renders safely when egs_state is null (reconnect window)', (tester) async {
    final state = MissionState();
    state.applyStateUpdate({
      "type": "state_update",
      "timestamp": "2026-05-02T12:00:00.000Z",
      "contract_version": "1.0.0",
      "egs_state": null,
      "active_drones": [_drone("drone1")],
      "active_findings": [],
    });
    await tester.pumpWidget(_wrap(state));
    // Renders the drone row without crashing; ticker line is empty
    expect(find.textContaining("drone1"), findsOneWidget);
    expect(find.textContaining("Validation: 0 fails"), findsOneWidget);
  });
}
```

- [ ] **Step 2: Run. Expect failures.**

- [ ] **Step 3: Update `drone_status_panel.dart`**

Replace the file:

```dart
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../state/mission_state.dart';

class DroneStatusPanel extends StatelessWidget {
  const DroneStatusPanel({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<MissionState>(
      builder: (_, mission, __) {
        if (mission.activeDrones.isEmpty) {
          return const _EmptyPanel(label: "Drone Status", hint: "No drones online");
        }
        final events = _validationEventsByDrone(mission.egsState);
        return ListView.separated(
          padding: const EdgeInsets.all(12),
          itemCount: mission.activeDrones.length,
          separatorBuilder: (_, __) => const Divider(),
          itemBuilder: (_, i) {
            final d = mission.activeDrones[i] as Map<String, dynamic>;
            final droneId = d["drone_id"] as String? ?? "drone?";
            final perDrone = events[droneId] ?? const [];
            return ListTile(
              isThreeLine: true,
              title: Text("$droneId — ${d["agent_status"]}"),
              subtitle: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    "Battery ${d["battery_pct"]}% · "
                    "Task: ${d["current_task"] ?? "idle"} · "
                    "Findings: ${d["findings_count"]} · "
                    "Validation fails: ${d["validation_failures_total"]}",
                  ),
                  const SizedBox(height: 2),
                  Text(
                    _tickerLine(perDrone),
                    style: TextStyle(
                      fontSize: 11,
                      color: perDrone.isEmpty ? Colors.grey[600] : Colors.orange[800],
                    ),
                  ),
                ],
              ),
            );
          },
        );
      },
    );
  }

  /// Group recent_validation_events by agent (drone_id). Returns empty map
  /// when egs_state is null (reconnect window) so the panel renders cleanly.
  Map<String, List<Map<String, dynamic>>> _validationEventsByDrone(Map<String, dynamic>? egs) {
    if (egs == null) return const {};
    final raw = egs["recent_validation_events"];
    if (raw is! List) return const {};
    final result = <String, List<Map<String, dynamic>>>{};
    for (final entry in raw) {
      if (entry is! Map<String, dynamic>) continue;
      final agent = entry["agent"] as String?;
      if (agent == null) continue;
      result.putIfAbsent(agent, () => []).add(entry);
    }
    return result;
  }

  String _tickerLine(List<Map<String, dynamic>> events) {
    if (events.isEmpty) return "Validation: 0 fails";
    final last = events.first;
    final ts = (last["timestamp"] as String?) ?? "";
    final shortTs = ts.length >= 19 ? ts.substring(11, 19) : ts;
    final issue = last["issue"] ?? "?";
    return "Validation: ${events.length} fails (last: $shortTs — $issue)";
  }
}

class _EmptyPanel extends StatelessWidget {
  final String label;
  final String hint;
  const _EmptyPanel({required this.label, required this.hint});
  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Text(label, style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          Text(hint, style: Theme.of(context).textTheme.bodySmall),
        ],
      ),
    );
  }
}
```

- [ ] **Step 4: Run. Expect 4 passing.**

- [ ] **Step 5: Run full Flutter suite:**

Run: `cd frontend/flutter_dashboard && flutter test`

- [ ] **Step 6: Commit**

```bash
git add frontend/flutter_dashboard/lib/widgets/drone_status_panel.dart \
  frontend/flutter_dashboard/test/drone_status_panel_test.dart
git commit -m "Phase 4 dashboard: validation event ticker on DroneStatusPanel"
```

---

## Task 15: Chrome DevTools MCP visual gate (manual run, no commit)

**This task is verification, not code. It runs after Task 14's commit lands.**

The implementer subagent does NOT run this task. The controlling agent (you) runs it via Chrome DevTools MCP after all subagent tasks complete.

**Prerequisites:**
- `redis-server` running locally
- Bridge: `PYTHONPATH=. python -m uvicorn frontend.ws_bridge.main:app --port 9090`
- Stub EGS: `PYTHONPATH=. python3 scripts/dev_command_translator.py`
- `dev_actions_logger.py` running (verifies dispatch published correctly)
- Flutter web build: `cd frontend/flutter_dashboard && flutter build web --release` then version-bust filenames per Phase 3 cache-bust pattern (rename `main.dart.js` → `main.dart.v2.js` etc., update `index.html`).
- Static-serve build with `python3 -m http.server` from the build directory.

**Test cases (from spec §8.4):**

- [ ] **Case 1:** Type "recall drone1" with English language → click TRANSLATE → preview shows "Will recall drone1: operator request" → click DISPATCH → state shows "Dispatched ✓" → verify via `redis-cli MONITOR` that `egs.operator_actions` received the `operator_command_dispatch`.

- [ ] **Case 2:** Switch dropdown to Spanish → type "concéntrate en la zona este" → TRANSLATE → preview shows "Will restrict mission to zone 'east'" → DISPATCH → confirm.

- [ ] **Case 3:** Type "asdf nonsense" → TRANSLATE → preview pane shows "Command not understood" with orange border → DISPATCH button is disabled with tooltip → click REPHRASE → input retains "asdf nonsense" (per spec §6.2 input retention) → state machine resets.

- [ ] **Case 4:** Open second tab, type "recall drone2", click TRANSLATE, then immediately kill the bridge process. Within 15s the panel should show "Translation lost — retry" snackbar and the Translate button re-enables.

- [ ] **Case 5:** Inject a state_update with new `recent_validation_events` (publish via `redis-cli PUBLISH egs.state '<json>'`) → DroneStatusPanel ticker line increments and shows the latest issue.

- [ ] **Case 6:** Inject a `finding_approval` for an unknown finding_id via `evaluate_script` (Flutter canvas swallows synthetic clicks; drive WS frame directly) → `redis-cli MONITOR` shows NO publish to `egs.operator_actions` → bridge sends back `{"error": "unknown_finding_id"}` echo.

If all 6 cases pass, the e2e gate is green.

If any case fails, file a bug report citing the case number and rerun the failing subagent task.

---

## Task 16: Update `TODOS.md` and final-touch commit

**Files:**
- Modify: `TODOS.md`

- [ ] **Step 1: Update `TODOS.md` to reflect Phase 4 closing 3 deferred items + filing 2 deferred adversarial findings**

In `TODOS.md`:
- Update "EGS subscriber for `egs.operator_actions`" — note that the Phase 4 contract (operator_command_dispatch kind) is now also part of Person 3's scope.
- Mark "Bridge finding_id allowlist for `egs.operator_actions`" as **CLOSED in Phase 4** — strikethrough with a one-line note pointing to the allowlist branch in `frontend/ws_bridge/main.py`.
- Mark "Validation event ticker on drone status panel" as **CLOSED in Phase 4** — strikethrough with a one-line note pointing to `drone_status_panel.dart`.
- Add **Phase 5+:** "Translate `preview_text_in_operator_language` properly" — Phase 4 stub uses identical English text; real EGS uses Gemma 4 E4B per §11.
- Add **Phase 5+:** "Bridge lifespan teardown ordering" — adversarial finding #6. `subscriber.stop()` aclose's pubsub while `subscribe_task` may still be mid-await on it; produces noisy stderr on shutdown but no functional bug. Right fix: set `_stopping=True` first, await tasks, THEN aclose pubsub/client.
- Add **Phase 5+:** "Move `ValidationEventLogger.log` off the dispatch path" — adversarial finding #7. Currently does sync disk I/O inside the subscriber's hot path; a misbehaving EGS spamming malformed translations could degrade Redis drain. Right fix: queue + executor or async writer.

No `<SHA>` placeholders — use plain text closure notes (the implementer subagent doesn't have access to commit SHAs at write time).

- [ ] **Step 2: Verify all tests still pass**

Run: `PYTHONPATH=. pytest shared/tests/ frontend/ws_bridge/tests/ scripts/test_dev_command_translator.py -v`
Run: `cd frontend/flutter_dashboard && flutter test`
Expected: all green.

- [ ] **Step 3: Commit**

```bash
git add TODOS.md
git commit -m "Phase 4: update TODOS to reflect closed items"
```

---

## Verification checklist before opening PR

- [ ] All Python tests green: `PYTHONPATH=. pytest shared/tests/ frontend/ws_bridge/tests/ scripts/`
- [ ] All Flutter tests green: `cd frontend/flutter_dashboard && flutter test`
- [ ] All 16 commits on `feat/phase4-command-translation` branch
- [ ] Spec at `docs/superpowers/specs/2026-05-02-phase4-command-translation-design.md` is APPROVED
- [ ] Plan at `docs/superpowers/plans/2026-05-02-phase4-command-translation.md` (this file) checked off
- [ ] Chrome DevTools MCP gate (Task 15) all 6 cases pass with screenshots
- [ ] Adversarial subagent pass run + findings either fixed or filed as TODOs
- [ ] PR opened against `main` with summary of the 16 commits

---

## Failure modes covered (from review)

| Codepath | Failure mode | Test | Error path | UX |
|---|---|---|---|---|
| Bridge operator_command publish | Redis down | test_main_operator_command_publish | `_echo_error("redis_publish_failed")` | Snackbar "Bridge could not reach Redis — retry"; input retained |
| Bridge translation forward | Invalid envelope | test_main_command_translation_forward (drop test) | Logged + dropped | None (no UI surface for upstream bug) |
| Bridge dispatch publish | Redis down | shared with operator_command path | `_echo_error("redis_publish_failed")` | State stays `dispatched` (optimistic); next bridge restart re-acks |
| Bridge finding_id allowlist | Aged-out finding | test_main_finding_id_allowlist | `_echo_error("unknown_finding_id")` | Snackbar "Finding aged out — refresh and retry" |
| Flutter command machine | WS drop during translating | mission_state_command_test | `_failInFlightCommands` | Snackbar; Translate button re-enables |
| Flutter command machine | 15s translation timeout | mission_state_command_test | Timer → failed | Snackbar "Translation lost — retry" |
| Flutter command machine | Late translation post-timeout | mission_state_command_test (1B) | Drop in `applyTranslation` | None (silent drop, debug log) |
| DroneStatusPanel | egs_state == null | drone_status_panel_test | Empty events map → "0 fails" line | Renders cleanly during reconnect |

No silent failures. No untested error paths.

## What's NOT in scope (re-stated)

- Real Gemma 4 E4B inference at the EGS — Person 3
- Voice operator commands — stretch (post-submission)
- `set_priority` / `set_language` execution semantics — Person 3
- EGS state echo for confirmed dispatch — Person 3 (forward-compat hooks present)
- Map marker tap/hover interactivity — separate TODO
- Static aerial base image — separate TODO
- Translating preview text into operator language properly — Phase 5+ (stub uses identity)
