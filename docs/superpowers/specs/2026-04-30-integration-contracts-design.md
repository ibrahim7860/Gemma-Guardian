# Integration Contracts — Design Spec (v1.0.0)

**Date:** 2026-04-30
**Owner:** Project lead (Ibrahim) — Person 4 also consumes; Persons 1/2/3 produce.
**Source docs:** [`docs/20-integration-contracts.md`](../../20-integration-contracts.md), [`docs/09-function-calling-schema.md`](../../09-function-calling-schema.md), [`docs/10-validation-and-retry-loop.md`](../../10-validation-and-retry-loop.md)

## Goal

Lock every cross-component contract on Day 1 so five people can build in parallel without integration thrash. Produce machine-checkable artifacts (JSON Schemas, Python validators, generated topic constants, fixture round-trip tests) that fail CI when any contract drifts.

## Non-goals

- Schema evolution beyond v1 (policy is "don't change; bump and update everywhere same day").
- Flutter unit tests beyond import-compile of generated constants.
- ROS 2 custom-message generation. Wire format is `std_msgs/String` carrying validated JSON, per Contract 9.

## Decisions (locked)

1. **Scope:** Full lock-in — JSON Schemas + shared Python contracts package + Dart-side generated constants + fixture round-trip tests + version-stamping checks.
2. **Source of truth for Python types:** JSON Schema is authoritative for the wire shape; hand-written Pydantic v2 models mirror them for ergonomics; tests assert parity over fixtures.
3. **Schema strictness:** Structural-only in JSON Schema (`additionalProperties: false`, types/enums/ranges, `$ref` into `_common.json`). Semantic and stateful rules stay in Python validators, every failure tagged with a stable `RuleID` enum value (rule IDs become the failure_reason field across the system).
4. **ROS 2 topic registry:** `shared/contracts/topics.yaml` is the single source of truth; `scripts/gen_topic_constants.py` generates `shared/contracts/topics.py` and `frontend/flutter_dashboard/lib/generated/topics.dart`. CI fails on stale generated files.
5. **Versioning:** `shared/VERSION = "1.0.0"`; every JSON Schema `$id` contains `/v1/`; `shared/config.yaml` and every WebSocket envelope carry `contract_version`. CI asserts all three agree.
6. **Schema modularity:** One file per contract category mirroring doc 20. Common shapes live in `shared/schemas/_common.json` and are `$ref`-d.
7. **Finding ID format:** `^f_drone\d+_\d+$`. Per-drone monotonic counter persisted via `agents/drone_agent/memory.py`.
8. **Timestamps:** ISO 8601 UTC, millisecond precision, `Z` suffix.
9. **`drone_id` format:** `^drone\d+$`.
10. **WebSocket envelope:** Discriminated union on `type` over five message kinds; every envelope carries `contract_version`.
11. **Fixtures:** Every JSON example from doc 20 / doc 09 lives under `shared/schemas/fixtures/{valid,invalid}/<contract>/`. Round-trip test loads each, validates, asserts pass/fail. Invalid fixture filenames encode the expected first-failing rule ID.

## Architecture

### Source-of-truth assignments

| Concern | Source of truth |
|---|---|
| Wire shape (structural) | `shared/schemas/*.json` (JSON Schema Draft 2020-12) |
| Semantic + stateful rules | `agents/drone_agent/validation.py` and `agents/egs_agent/*` validators, tagged with `RuleID` |
| Rule ID enum + descriptions | `shared/contracts/rules.py` |
| Topic names | `shared/contracts/topics.yaml` (codegen target for Python and Dart) |
| Mission config | `shared/config.yaml` |
| Contract version | `shared/VERSION` |

### Directory layout (target)

```
shared/
├── VERSION                              # "1.0.0"
├── config.yaml                          # Contract 12, stamped with contract_version
├── schemas/
│   ├── _common.json                     # gps, iso_timestamp, drone_id, finding_id, severity, finding_type, etc.
│   ├── drone_function_calls.json        # exists; refine to use _common refs
│   ├── egs_function_calls.json          # NEW — Layer 2 (assign_survey_points, replan_mission)
│   ├── operator_commands.json           # NEW — Layer 3 (six commands)
│   ├── drone_state.json                 # NEW — Contract 2
│   ├── egs_state.json                   # NEW — Contract 3
│   ├── finding.json                     # NEW — Contract 4
│   ├── task_assignment.json             # NEW — Contract 5
│   ├── peer_broadcast.json              # NEW — Contract 6 (discriminated union)
│   ├── websocket_messages.json          # NEW — Contracts 7+8 (discriminated union)
│   ├── validation_event.json            # NEW — one record in /tmp/.../validation_events.jsonl
│   └── fixtures/
│       ├── valid/<contract>/*.json
│       └── invalid/<contract>/*.json    # filename encodes expected rule_id
├── contracts/                           # Python package
│   ├── __init__.py                      # public re-exports
│   ├── schemas.py                       # jsonschema validators, validate(name, payload)
│   ├── models.py                        # Pydantic v2 mirrors of every schema
│   ├── rules.py                         # RuleID enum + RULE_REGISTRY
│   ├── topics.py                        # GENERATED — do not hand-edit
│   ├── topics.yaml                      # source of truth for topic registry
│   ├── config.py                        # typed loader for shared/config.yaml
│   └── logging.py                       # /tmp/fieldagent_logs/ setup + ValidationEventLogger
├── prompts/                             # already exists, no change
└── tests/
    ├── test_fixtures_roundtrip.py
    ├── test_models_match_schemas.py
    ├── test_rules_coverage.py
    ├── test_topics_codegen_fresh.py
    ├── test_version_consistency.py
    ├── test_examples_in_docs.py
    └── test_validation_node_rule_ids.py

scripts/
└── gen_topic_constants.py               # reads topics.yaml, writes Python + Dart

frontend/flutter_dashboard/
└── lib/generated/
    ├── topics.dart                      # GENERATED
    └── contract_version.dart            # GENERATED
```

## Discriminated-union convention

Every `oneOf` discriminated union in this spec puts a `const` on the discriminator field inside each branch (`{"function": {"const": "report_finding"}}`, `{"command": {"const": "restrict_zone"}}`, `{"type": {"const": "state_update"}}`, `{"broadcast_type": {"const": "finding"}}`). This is the pattern `jsonschema` heuristically uses to produce branch-specific error messages instead of the generic "must match exactly one schema" — without it, validation failures on these unions are useless to debug.

## Adapter contract (Ollama → canonical form)

Doc 09 supports two paths into Gemma 4: the native `tools[]` path (Ollama emits `response.message.tool_calls[]`) and the structured-output `format` path (Ollama emits a JSON-string-shaped `message.content`). Both must normalize to the canonical wire shape:

```json
{ "function": "<name>", "arguments": { ... } }
```

The adapter contract:

| Input path | Input shape | Adapter responsibility |
|---|---|---|
| `tools[]` | `[{"function": {"name": str, "arguments": dict}}, …]` | Take `tool_calls[0]`, hoist `name` to `function`, pass `arguments` through. Reject (`STRUCTURAL_VALIDATION_FAILED`) if `len(tool_calls) != 1`. |
| `format=<schema>` | `message.content: str` containing JSON | Parse JSON. If parse fails → `STRUCTURAL_VALIDATION_FAILED`. If parsed object already matches canonical form, pass through. If it matches Ollama's `tool_calls[0]` shape, hoist as above. |

For Layer 3 operator commands, the canonical shape is `{ "command": "<name>", "args": { ... } }` instead, but the adapter logic is identical.

The adapter lives in `agents/drone_agent/reasoning.py` (Layer 1) and `agents/egs_agent/validation.py` (Layers 2 + 3). Both implementations import a shared helper from `shared.contracts.adapters` so the normalization logic exists in exactly one place. A test (`test_adapter_canonical.py`) round-trips every valid fixture through both input shapes and asserts the canonical output is byte-identical.

## Schemas (file by file)

### `_common.json`

`$defs` only — no top-level type. Defines:

- `iso_timestamp_utc_ms` — string, pattern `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$`
- `drone_id` — string, pattern `^drone\d+$`
- `finding_id` — string, pattern `^f_drone\d+_\d+$`
- `lat` — number, -90..90
- `lon` — number, -180..180
- `altitude_m` — number, ≥ 0
- `gps_point` — `{ lat, lon }`, `additionalProperties: false`
- `position3d` — `{ lat, lon, alt }`
- `velocity3d` — `{ vx, vy, vz }`, all numbers
- `polygon` — array of `[lat, lon]` tuples, `minItems: 3`
- `severity` — integer 1..5
- `confidence` — number 0.0..1.0
- `coverage_pct` — number 0.0..100.0
- `finding_type` — enum `victim | fire | smoke | damaged_structure | blocked_route`
- `urgency` — enum `low | medium | high`
- `priority_level` — enum `low | normal | high | critical`
- `iso_lang_code` — string, pattern `^[a-z]{2}$`
- `agent_status` — enum `active | standalone | returning | offline | error`
- `mission_status` — enum `idle | active | paused | aborted | complete` (doc 20 example shows `"active"` only; this spec locks the full set)
- `task_type` — enum `survey | investigate_finding | return_to_base | hold_position`
- `broadcast_type` — enum `finding | assist_request | task_complete | entering_standalone_mode | rejoining_swarm`
- `operator_status` — enum `pending | approved | dismissed`
- `survey_point_status` — enum `unassigned | assigned | completed | failed`
- `survey_point` — `{ id, lat, lon, assigned_to: drone_id|null, status: survey_point_status, priority?: priority_level }`
- `rtb_reason` — enum `low_battery | mission_complete | ordered | mechanical | weather`
- `rule_id` — string, pattern `^[A-Z][A-Z0-9_]{2,}$`

### `drone_function_calls.json` (refine existing)

Already correct in shape. Refinements:

- Replace inline `severity` / `confidence` / `coverage_pct` with `$ref` into `_common.json`.
- Add `pattern` for `related_finding_id` matching the `finding_id` def.
- Add `$id`: `https://github.com/ibrahim7860/Gemma-Guardian/shared/schemas/v1/drone_function_calls.json`.
- Keep `additionalProperties: false` at every object level.

### `egs_function_calls.json` (NEW)

> **Lifecycle note:** Layer-2 schemas validate Gemma 4 output *only*. The EGS coordinator never publishes `assign_survey_points` or `replan_mission` directly on a ROS topic — it parses them, runs them through `agents/egs_agent/validation.py`, then *translates* them into `task_assignment.json` payloads on `/drones/<id>/tasks`. This is internal to the EGS process.

`oneOf` over:

- `assign_survey_points` — `arguments.assignments`: array of `{ drone_id, survey_point_ids: array<string> }`, `minItems: 1`.
- `replan_mission` — `arguments`: `{ trigger, new_zone_polygon: polygon, excluded_drones: array<drone_id>, excluded_survey_points: array<string> }`. `trigger` enum: `drone_failure | zone_change | operator_command | fire_spread`.

### `operator_commands.json` (NEW)

Discriminated union on `command`. Six entries: `restrict_zone`, `exclude_zone`, `recall_drone`, `set_priority`, `set_language`, `unknown_command`. Each entry shape: `{ command: "<name>", args: { ... } }`. `unknown_command.args = { operator_text, suggestion }` is the safe fallback.

### `drone_state.json` (Contract 2)

Mirrors doc 20 exactly. Notable fields:

- `position` — `position3d`
- `velocity` — `velocity3d`
- `battery_pct` — integer 0..100
- `heading_deg` — number 0..360
- `current_task` — `task_type | null`
- `current_waypoint_id` — `string | null`
- `assigned_survey_points_remaining` — integer ≥ 0
- `last_action` — enum of Layer-1 function names (`report_finding | mark_explored | request_assist | return_to_base | continue_mission`) + `"none"`
- `last_action_timestamp` — `iso_timestamp_utc_ms | null`
- `validation_failures_total` — integer ≥ 0
- `findings_count` — integer ≥ 0
- `in_mesh_range_of` — array of `drone_id | "egs"`
- `agent_status` — shared enum

### `egs_state.json` (Contract 3)

Mirrors doc 20. `survey_points` items use the shared `survey_point` def. `drones_summary` is an object map `<drone_id> → { status: agent_status, battery: integer|null }`. `findings_count_by_type` is an object map keyed by `finding_type` → integer. `recent_validation_events` items reference the `validation_event` shape (truncated form: `timestamp, agent, task, outcome, issue=rule_id`). `active_zone_ids` is array of strings.

### `finding.json` (Contract 4)

Mirrors doc 20. `image_path` required, non-empty string. `validated` boolean. `validation_retries` integer 0..3. `operator_status` shared enum. Top-level `finding_id` matches `finding_id` def.

### `task_assignment.json` (Contract 5)

Mirrors doc 20. `task_type` shared enum. `assigned_survey_points` items inline `{ id, lat, lon, priority? }`. `priority_override` `priority_level | null`. `valid_until` ISO timestamp.

### `peer_broadcast.json` (Contract 6)

Discriminated union on `broadcast_type`. Doc 20 only fully specifies the `finding` case; the other four payloads are **inferences from doc 08** that this spec is locking in:

- `finding`: payload mirrors `finding.json` minus operator-only fields (no `operator_status`, no `validated`, no `validation_retries`).
- `assist_request`: payload `{ reason, urgency, related_finding_id? }`.
- `task_complete`: payload `{ task_id, result: "success" | "partial" | "failed" }`.
- `entering_standalone_mode`: payload `{ trigger: "lost_egs_link" | "lost_peers" | "ordered" }`.
- `rejoining_swarm`: payload `{ findings_to_share_count: integer ≥ 0 }`.

Top-level fields per doc 20 (`broadcast_id`, `sender_id`, `sender_position`, `timestamp`). If doc 08 disagrees on any of these payloads, the implementation plan task that creates this schema must reconcile and update doc 20.

### `websocket_messages.json` (Contracts 7 + 8)

Discriminated union on `type`. Five cases:

- `state_update` (EGS → Flutter): `{ type, timestamp, contract_version, egs_state, active_findings: [finding…], active_drones: [drone_state…] }`.
- `operator_command` (Flutter → EGS): `{ type, command_id, language: iso_lang_code, raw_text, contract_version }`.
- `command_translation` (EGS → Flutter): `{ type, command_id, structured: operator_command_payload, valid: bool, preview_text, preview_text_in_operator_language, contract_version }`.
- `operator_command_dispatch` (Flutter → EGS): `{ type, command_id, contract_version }`.
- `finding_approval` (Flutter → EGS): `{ type, command_id, finding_id, action: "approve" | "dismiss", contract_version }`.

**`contract_version` ownership:** rosbridge_suite does not natively wrap messages with a version tag. The EGS-side bridge stamps `contract_version` from `shared.VERSION` on every outbound message before publish. The Flutter client compares against `frontend/.../generated/contract_version.dart`; on mismatch, it logs a console warning, drops the message, and surfaces a banner ("Server contract X.Y.Z, client X.Y'.Z' — refresh required"). Inbound messages from Flutter are stamped on the Flutter side and validated by EGS the same way.

### `validation_event.json` (Contract 11)

Schema for one line of `/tmp/fieldagent_logs/validation_events.jsonl`:

```
{
  "timestamp": iso_timestamp_utc_ms,
  "agent_id": drone_id | "egs",
  "layer": "drone" | "egs" | "operator",
  "function_or_command": string,
  "attempt": integer 1..N,
  "valid": boolean,
  "rule_id": rule_id | null,         // null iff valid=true
  "outcome": "success_first_try" | "corrected_after_retry" | "failed_after_retries" | "in_progress",
  "raw_call": object | null,         // truncated LLM output that triggered the event
  "contract_version": string
}
```

This is the writeup's quantitative substrate.

## Python package `shared/contracts/`

### `__init__.py`

Public API only. Re-exports `validate`, `validate_or_raise`, `schema`, `all_schemas`, every Pydantic model, `RuleID`, `RULE_REGISTRY`, `RuleSpec`, every topic constant, every topic helper, and `VERSION` (read from `shared/VERSION`).

### `schemas.py`

Loads each `shared/schemas/*.json` once at import time. Cross-file `$ref`s into `_common.json` are resolved via the `referencing` library (`referencing.Registry().with_resource(...)`), which is the post-`jsonschema-4.18` API for non-bundled refs. Builds one `jsonschema.Draft202012Validator` per contract, sharing the registry. Public API:

- `validate(name: str, payload: dict) -> ValidationOutcome` — `ValidationOutcome(valid: bool, errors: list[StructuralError])`. Each `StructuralError` carries the failing field path and `rule_id="STRUCTURAL_VALIDATION_FAILED"`.
- `validate_or_raise(name, payload)` — convenience for tests/dev; raises `ContractError`.
- `schema(name)` — returns parsed JSON for the named contract (used by EGS to pass `oneOf` to Ollama's `format` parameter).
- `all_schemas() -> dict[str, dict]` — for the test harness.

### `models.py`

One Pydantic v2 model per contract, mirroring the JSON Schema. Hand-written. `model_config = ConfigDict(extra="forbid")` everywhere. Used only on Python construction sites; the wire boundary still goes through `jsonschema` validation. Models include `model_validator(mode="after")` only for cheap structural pieces JSON Schema also enforces — never for stateful rules. `to_payload()` emits the canonical wire form.

### `rules.py`

```python
class RuleID(StrEnum):
    # Layer 1 — drone function calls
    PROSE_INSTEAD_OF_FUNCTION = "PROSE_INSTEAD_OF_FUNCTION"
    INVALID_FUNCTION_NAME = "INVALID_FUNCTION_NAME"
    STRUCTURAL_VALIDATION_FAILED = "STRUCTURAL_VALIDATION_FAILED"
    GPS_OUTSIDE_ZONE = "GPS_OUTSIDE_ZONE"
    DUPLICATE_FINDING = "DUPLICATE_FINDING"
    SEVERITY_CONFIDENCE_MISMATCH = "SEVERITY_CONFIDENCE_MISMATCH"
    ZONE_ID_NOT_ASSIGNED = "ZONE_ID_NOT_ASSIGNED"
    COVERAGE_DECREASED = "COVERAGE_DECREASED"
    RTB_LOW_BATTERY_INVALID = "RTB_LOW_BATTERY_INVALID"
    RTB_MISSION_COMPLETE_INVALID = "RTB_MISSION_COMPLETE_INVALID"
    RELATED_FINDING_ID_INVALID = "RELATED_FINDING_ID_INVALID"
    FINDING_ID_FORMAT = "FINDING_ID_FORMAT"
    # Layer 2 — EGS coordinator
    ASSIGNMENT_TOTAL_MISMATCH = "ASSIGNMENT_TOTAL_MISMATCH"
    ASSIGNMENT_DUPLICATE_POINT = "ASSIGNMENT_DUPLICATE_POINT"
    ASSIGNMENT_DRONE_MISSING = "ASSIGNMENT_DRONE_MISSING"
    ASSIGNMENT_UNBALANCED = "ASSIGNMENT_UNBALANCED"
    REPLAN_POLYGON_INVALID = "REPLAN_POLYGON_INVALID"
    REPLAN_EXCLUDED_DRONE_NOT_IN_FLEET = "REPLAN_EXCLUDED_DRONE_NOT_IN_FLEET"
    REPLAN_EXCLUDED_POINT_NOT_IN_PREVIOUS = "REPLAN_EXCLUDED_POINT_NOT_IN_PREVIOUS"
    EGS_DUPLICATE_FINDING = "EGS_DUPLICATE_FINDING"
    # Layer 3 — operator commands
    OPERATOR_COMMAND_UNKNOWN = "OPERATOR_COMMAND_UNKNOWN"
    RECALL_DRONE_NOT_ACTIVE = "RECALL_DRONE_NOT_ACTIVE"
    SET_LANGUAGE_INVALID_CODE = "SET_LANGUAGE_INVALID_CODE"

@dataclass(frozen=True)
class RuleSpec:
    id: RuleID
    layer: Literal["drone", "egs", "operator"]
    description: str
    corrective_template: str   # used to build retry prompts; references doc 10

RULE_REGISTRY: dict[RuleID, RuleSpec] = { ... }
```

`STRUCTURAL_VALIDATION_FAILED` is the umbrella code for any plain JSON-Schema failure; the `validation_event` records the field path so we still see exactly which field was wrong.

**`corrective_template` usage convention.** For v1, validators construct corrective prompts inline using local context (battery percentage, prior coverage value, etc.) rather than reading from `RULE_REGISTRY[id].corrective_template`. The templates in `rules.py` are the canonical reference for the writeup and serve as docs for future template-driven prompt assembly; they intentionally duplicate (and can drift from) the inline strings. Tests assert templates are present and well-formed, not that they match the inline prompts. If we ever need centralized template assembly (e.g., per-language operator prompts), the registry is already there.

### `topics.yaml` (registry source of truth)

```yaml
contract_version_floor: "1.0"
ros2:
  per_drone:
    state:    { topic: "/drones/{drone_id}/state",    type: "std_msgs/String", json_schema: "drone_state" }
    tasks:    { topic: "/drones/{drone_id}/tasks",    type: "std_msgs/String", json_schema: "task_assignment" }
    findings: { topic: "/drones/{drone_id}/findings", type: "std_msgs/String", json_schema: "finding" }
    camera:   { topic: "/drones/{drone_id}/camera",   type: "sensor_msgs/Image" }
    cmd:      { topic: "/drones/{drone_id}/cmd",      type: "std_msgs/String", json_schema: null }   # PX4-internal flight commands; not a Gemma-driven contract
  swarm:
    broadcast:        { topic: "/swarm/broadcasts/{drone_id}",            type: "std_msgs/String", json_schema: "peer_broadcast" }
    visible_to:       { topic: "/swarm/{drone_id}/visible_to_{drone_id}", type: "std_msgs/String", json_schema: "peer_broadcast" }
    operator_alerts:  { topic: "/swarm/operator_alerts",                  type: "std_msgs/String", json_schema: null }
  egs:
    state:          { topic: "/egs/state",          type: "std_msgs/String", json_schema: "egs_state" }
    replan_events:  { topic: "/egs/replan_events",  type: "std_msgs/String", json_schema: null }
  mesh:
    adjacency:      { topic: "/mesh/adjacency_matrix", type: "std_msgs/String", json_schema: null }
websocket:
  endpoint: "ws://localhost:9090"
  schema:   "websocket_messages"
```

### `topics.py` (generated)

Constants for every fixed topic; helpers `drone_state_topic("drone1")` etc. Header line: `# GENERATED by scripts/gen_topic_constants.py — do not edit. Source: shared/contracts/topics.yaml`.

### `config.py`

Pydantic-validated loader for `shared/config.yaml`. Fails loudly on missing keys. Exports a `CONFIG` singleton. Mismatched `contract_version` aborts startup with a clear error.

### `logging.py`

- `setup_logging(component_name)` — creates `/tmp/fieldagent_logs/<component>.log`, configures a Python logger, returns it.
- `ValidationEventLogger` — writes one `validation_event.json`-shaped line per call into `/tmp/fieldagent_logs/validation_events.jsonl`. All five agents share this logger; the file is append-only. No rotation (a 20-day hackathon doesn't generate enough events to matter).

## Generated Dart constants

`scripts/gen_topic_constants.py` reads `topics.yaml` and writes:

`frontend/flutter_dashboard/lib/generated/topics.dart`:

```dart
// GENERATED by scripts/gen_topic_constants.py — do not edit.
class Topics {
  static const wsEndpoint = "ws://localhost:9090";
  static const wsSchema = "websocket_messages";
  static const egsState = "/egs/state";
  static String droneState(String droneId) => "/drones/$droneId/state";
  static String droneFindings(String droneId) => "/drones/$droneId/findings";
  // ...
}
```

`frontend/flutter_dashboard/lib/generated/contract_version.dart`:

```dart
const contractVersion = "1.0.0";
```

CI guard: `scripts/gen_topic_constants.py --check` regenerates into a tempdir and `diff`s against checked-in files; failure means someone edited generated code or forgot to regenerate.

## Configuration

`shared/config.yaml` filled out per Contract 12 plus `contract_version` stamping (full content listed in design Section 5).

## Wire-up changes to existing code

- **`agents/drone_agent/validation.py`** — every `ValidationResult.failure_reason` becomes a `RuleID` value. Structural pieces (`severity_out_of_range`, `confidence_out_of_range`, `visual_description_too_short`, `invalid_argument_type`) are removed from Python and delegated to `shared.contracts.schemas.validate("drone_function_calls", call)` at the top of `validate()`; structural failure returns `RuleID.STRUCTURAL_VALIDATION_FAILED` with the field path so the corrective prompt can still cite the bad field. Stateful checks (duplicates, coverage, GPS-in-zone, RTB battery/mission gates) stay in Python.
- **`agents/drone_agent/reasoning.py`** — after Ollama returns, normalize tool-call shape and `format`-output shape into the canonical `{"function": ..., "arguments": ...}` form, then construct the matching Pydantic model. Construction failure = `RuleID.STRUCTURAL_VALIDATION_FAILED`.
- **`agents/egs_agent/`** — this plan only creates `__init__.py` plus a thin `validation.py` that imports from `shared.contracts` and exposes `validate(call, state) -> ValidationResult` for both Layer-2 and Layer-3 calls (structural via jsonschema, semantic/stateful in Python, every failure tagged with a `RuleID`). `coordinator.py`, `command_translator.py`, and `replanning.py` are Person 3's territory per `docs/18-team-roles.md` and are explicitly out of scope for the contracts plan; Person 3 builds them on top of the locked `shared.contracts` API.

  `agents/egs_agent/validation.py` owns the cross-drone dedup rule `EGS_DUPLICATE_FINDING`: when an incoming finding from one drone has the same `type` within 10m and 30s of an already-validated finding from a *different* drone, mark it as a duplicate (same thresholds as the per-drone rule). Findings are accepted on first-seen-wins; duplicates are dropped and a validation event is logged.
- **`agents/drone_agent/memory.py`** — owns the per-drone `finding_id` counter. `next_finding_id() -> str` returns `f_{drone_id}_{count}` where `count` is monotonic.
- **`agents/drone_agent/perception.py`** — no contract change.

## Testing

A new `shared/tests/` package, runnable via `pytest`:

1. **`test_fixtures_roundtrip.py`** — every file under `shared/schemas/fixtures/valid/<contract>/*.json` validates as `valid=True`; every file under `invalid/<contract>/*.json` validates as `valid=False` with the rule ID encoded in the filename.
2. **`test_models_match_schemas.py`** — for every Pydantic model and matching JSON Schema, run all valid fixtures through both. Both must accept. Then mutate one field per fixture in pytest parametrize: both must reject.
3. **`test_rules_coverage.py`** — every `RuleID` member appears at least once as either an explicit `RuleID.X` reference in a Python validator or an encoded rule name in an `invalid/*.json` fixture.
4. **`test_topics_codegen_fresh.py`** — runs `scripts/gen_topic_constants.py --check`; pass = no diff.
5. **`test_version_consistency.py`** — every schema's `$id` contains `/v<major>/` matching `shared/VERSION`'s major; `shared/VERSION` matches `shared/config.yaml.contract_version` matches the constant in `frontend/.../contract_version.dart`.
6. **`test_examples_in_docs.py`** — extracts every fenced JSON block from `docs/09` and `docs/20` (skipping blocks with `<placeholder>` markers) and validates them against the matching schema.
7. **`test_validation_node_rule_ids.py`** — drives the existing `agents/drone_agent/validation.py` and the new EGS validator through synthetic inputs; asserts the emitted `failure_reason` is a real `RuleID` value.
8. **`test_adapter_canonical.py`** — for every valid Layer-1, Layer-2, and Layer-3 fixture, build both the Ollama `tool_calls[]` shape and the structured-output content-string shape, run both through `shared.contracts.adapters.normalize`, assert the output equals the canonical fixture byte-for-byte. Then test rejection paths: `len(tool_calls) != 1`, malformed JSON in content, and a non-canonical-non-ollama dict.
9. **Small-test backfills** —
   - `validate("nonexistent_schema_name", {})` raises a clear `KeyError`.
   - `Model(**fixture).to_payload()` round-trips on every valid fixture.
   - Every `topic_helper(drone_id)` returns the expected concrete topic string.
   - Every `RuleSpec.description` is non-empty and ≤ 200 chars; every `RuleSpec.corrective_template` is non-empty.
   - `ValidationEventLogger.log(event)` appends a `validation_event.json`-valid line.
   - When `schemas.validate` rejects a Layer-1 call, the corrective prompt cites the failing field path.
   - `EGS_DUPLICATE_FINDING` triggers when two distinct drones report same-`type` within 10m and 30s; first-seen-wins; second is dropped with a logged validation event.

**Acceptance criterion for "contracts locked":** `pytest shared/ agents/ -q` returns 0 with all seven test files green.

## Doc updates

- `docs/20-integration-contracts.md` — add a final "Authoritative artifacts" subsection linking to each `shared/schemas/*.json`, the topic registry, and the rule-ID list. Update the dated locked notice.
- `docs/10-validation-and-retry-loop.md` — replace any free-form failure-reason strings in corrective-prompt examples with the matching `RuleID` enum value.
- `docs/11-prompt-templates.md` — no change.
- `docs/09-function-calling-schema.md` — append "Layer 3 validation rules" subsection citing `shared/contracts/rules.py`.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Pydantic and JSON Schema drift | `test_models_match_schemas.py` runs every valid fixture through both layers, plus a parametrized mutation test. |
| Generated topic files edited by hand | `test_topics_codegen_fresh.py` runs `--check` mode and fails CI on diff. |
| Ollama `format` parameter rejecting `oneOf` | Each schema's top-level `oneOf` has a sibling `discriminator`-equivalent (`function`/`type`/`command`) that lets us, if needed, hand Ollama a single-branch schema chosen at runtime; the canonical form is unchanged. Validated at integration time. |
| Doc 20 examples drift from schemas | `test_examples_in_docs.py` makes the docs themselves part of the test surface. |
| Cross-team forgetting to bump version | `test_version_consistency.py` fails CI when any of `VERSION`, `config.yaml.contract_version`, `contract_version.dart` disagree. |

## Out of scope

- Real Ollama connectivity test (lives in agent integration tests, not contract tests).
- Flutter unit tests beyond the generated `topics.dart` and `contract_version.dart` import-compiles check.
- Schema-evolution policy beyond v1.
- ROS 2 message generation (we ride on `std_msgs/String` per Contract 9).
