# 09 — Function Calling Schema

## Why This Document Exists

Function calling is the agentic backbone of FieldAgent. Every Gemma 4 output that drives action is a structured function call validated against hard constraints. **Lock these schemas on Day 1 and do not change them.** All five team members build against these contracts.

> **Note on shape.** The JSON blocks below are *illustrative examples of the structured output we expect Gemma 4 to emit* (with angle-bracket placeholders like `<float>` standing in for real values). The authoritative machine-readable JSON Schemas (Draft 2020-12) live in `shared/schemas/*.json` and are what the validation node in [`10-validation-and-retry-loop.md`](10-validation-and-retry-loop.md) checks against. All `gps_lat`, `gps_lon`, `severity`, `confidence`, and `coverage_pct` fields are JSON numbers (not strings); all timestamps elsewhere in the system are ISO 8601 UTC (`YYYY-MM-DDTHH:MM:SS.sssZ`), matching [`20-integration-contracts.md`](20-integration-contracts.md).

There are three layers of function calls:

1. **Per-drone agent function calls** — what an individual drone agent decides to do
2. **EGS coordinator function calls** — what the swarm-level coordinator outputs
3. **Operator command function calls** — what the EGS understands the operator's natural language to mean

## Layer 1: Per-Drone Function Calls

The drone agent must call exactly ONE of these per inference cycle.

### `report_finding`

```json
{
  "function": "report_finding",
  "arguments": {
    "type": "victim | fire | smoke | damaged_structure | blocked_route",
    "severity": "<int 1-5>",
    "gps_lat": "<float>",
    "gps_lon": "<float>",
    "confidence": "<float 0.0-1.0>",
    "visual_description": "<string, min 10 chars>"
  }
}
```

**Validation rules:**
- `type` ∈ {victim, fire, smoke, damaged_structure, blocked_route}
- `severity` ∈ [1, 5] (1 = minor, 5 = critical)
- `gps_lat`, `gps_lon` must be inside the drone's currently assigned survey zone (with 50m tolerance for edge cases)
- `confidence` ∈ [0.0, 1.0]
- `visual_description` length ≥ 10 chars and not just whitespace
- Not a duplicate: same `type` + GPS within 10m + within last 30 seconds → reject as duplicate
- For `severity ≥ 4`, `confidence` must be ≥ 0.6 (don't broadcast high-severity findings with low confidence)

### `mark_explored`

```json
{
  "function": "mark_explored",
  "arguments": {
    "zone_id": "<string>",
    "coverage_pct": "<float 0.0-100.0>"
  }
}
```

**Validation rules:**
- `zone_id` must be one currently assigned to this drone
- `coverage_pct` ∈ [0.0, 100.0]
- Cannot decrease coverage (must be > previous reported value)

### `request_assist`

```json
{
  "function": "request_assist",
  "arguments": {
    "reason": "<string>",
    "urgency": "low | medium | high",
    "related_finding_id": "<string, optional>"
  }
}
```

**Validation rules:**
- `reason` length ≥ 10 chars
- `urgency` ∈ {low, medium, high}
- If `related_finding_id` provided, must match the `f_<drone_id>_NNN` pattern from Contract 4 in [`20-integration-contracts.md`](20-integration-contracts.md) and reference an existing finding from this drone

### `return_to_base`

```json
{
  "function": "return_to_base",
  "arguments": {
    "reason": "low_battery | mission_complete | ordered | mechanical | weather"
  }
}
```

**Validation rules:**
- `reason` ∈ enumerated values
- For `low_battery`: drone's battery must actually be below 25%
- For `mission_complete`: drone must have finished all assigned survey points

### `continue_mission`

```json
{
  "function": "continue_mission",
  "arguments": {}
}
```

**Validation rules:** always valid. This is the safe fallback when the drone has nothing actionable to report.

## Layer 2: EGS Coordinator Function Calls

The EGS uses these for swarm-level decisions.

### `assign_survey_points`

```json
{
  "function": "assign_survey_points",
  "arguments": {
    "assignments": [
      {
        "drone_id": "drone1",
        "survey_point_ids": ["sp_001", "sp_002", ...]
      },
      {
        "drone_id": "drone2",
        "survey_point_ids": [...]
      }
    ]
  }
}
```

**Validation rules:**
- Total survey points across all assignments = total available survey points
- No survey point appears in two drones' lists
- Every drone in the active fleet appears in `assignments` (drones explicitly excluded via `replan_mission.excluded_drones` may appear with `survey_point_ids: []`; all other drones must have at least one point)
- Counts are within ±1 of average across non-excluded drones (balanced workload)

**Corrective prompts on failure:** see [`10-validation-and-retry-loop.md`](10-validation-and-retry-loop.md).

### `replan_mission`

```json
{
  "function": "replan_mission",
  "arguments": {
    "trigger": "drone_failure | zone_change | operator_command | fire_spread",
    "new_zone_polygon": [[<lat>, <lon>], ...],
    "excluded_drones": ["drone3"],
    "excluded_survey_points": ["sp_023"]
  }
}
```

**Validation rules:**
- `trigger` ∈ enumerated values
- `new_zone_polygon` is a valid polygon (≥ 3 points, no self-intersection)
- `excluded_drones` is a subset of the active fleet
- `excluded_survey_points` exists in the previous assignment

After validation, this triggers a fresh `assign_survey_points` call internally.

## Layer 3: Operator Command Function Calls

The EGS translates operator natural language into these structured commands. **Each command also goes through validation** because the LLM can hallucinate command structures too.

### `restrict_zone`

```json
{
  "command": "restrict_zone",
  "args": {
    "zone_id": "<string>"
  }
}
```

### `exclude_zone`

```json
{
  "command": "exclude_zone",
  "args": {
    "zone_id": "<string>"
  }
}
```

### `recall_drone`

```json
{
  "command": "recall_drone",
  "args": {
    "drone_id": "<string>",
    "reason": "<string>"
  }
}
```

### `set_priority`

```json
{
  "command": "set_priority",
  "args": {
    "finding_type": "victim | fire | smoke | damaged_structure | blocked_route",
    "priority_level": "low | normal | high | critical"
  }
}
```

### `set_language`

```json
{
  "command": "set_language",
  "args": {
    "lang_code": "<ISO 639-1 code>"
  }
}
```

### `unknown_command`

```json
{
  "command": "unknown_command",
  "args": {
    "operator_text": "<echo of original input>",
    "suggestion": "<a clarifying question for the operator>"
  }
}
```

**Validation rules:**
- `command` must be one of the six defined types: `restrict_zone`, `exclude_zone`, `recall_drone`, `set_priority`, `set_language`, `unknown_command`
- For each command, args must match the schema (e.g., `recall_drone` requires `drone_id` to reference an active drone)
- For `set_language`, `lang_code` must be ISO 639-1 (en, es, ar, etc.)
- `unknown_command` is the safe fallback when the EGS cannot map operator text to one of the other five — it never executes, only prompts the operator for clarification

## How Gemma 4 Calls These

We invoke Gemma 4 through Ollama's `/api/chat` endpoint. Two paths are available and we use both depending on the call site:

1. **Native tools path** (`tools` array on the request body, per Ollama's tool-calling spec). Each tool is `{"type": "function", "function": {"name": ..., "description": ..., "parameters": <JSON Schema>}}`. Successful calls come back on `response.message.tool_calls[]` as `{"function": {"name": ..., "arguments": {...}}}`. We use this path on the EGS (E4B) where it is best supported.
2. **Structured-output path** (`format: <JSON Schema>` on the request body). The model is constrained to emit JSON matching the schema directly into `message.content`. We use this path as a fallback on the per-drone agent (E2B), and as belt-and-suspenders for any Gemma 4 variant whose tool-calling fidelity we don't trust on Day 7.

Either path produces output we then validate against `shared/schemas/*.json` in the validation node ([`10-validation-and-retry-loop.md`](10-validation-and-retry-loop.md)). The wire shape `{"function": "<name>", "arguments": {...}}` shown throughout this doc is our **internal canonical form** — adapters in `agents/*/reasoning.py` normalize Ollama's `tool_calls[]` shape and the structured-output JSON into this form before validation.

> **Compatibility flag.** Gemma 4 had not shipped at the time this contract was locked. If Gemma 4's Ollama integration does not expose reliable native tool calling on Day 1, we fall back exclusively to the structured-output (`format`) path — the canonical form is identical, so no schema or downstream change is required. See [`16-mocks-and-cuts.md`](16-mocks-and-cuts.md) for the fallback decision tree.

### Per-drone agent prompt structure (sketch)

```
SYSTEM: You are an autonomous drone in a disaster response mission.

Available tools:
- report_finding(type, severity, gps_lat, gps_lon, confidence, visual_description)
- mark_explored(zone_id, coverage_pct)
- request_assist(reason, urgency, related_finding_id?)
- return_to_base(reason)
- continue_mission()

Hard constraints:
- For severity >= 4, confidence must be >= 0.6
- GPS coordinates must be in your assigned zone {zone_bounds}
- Visual description must be at least 10 chars

Current state: {state_json}
Recent peer broadcasts: {peer_broadcasts}
Camera image: <image>

Decide your next action by calling exactly ONE function.
```

See [`11-prompt-templates.md`](11-prompt-templates.md) for full templates.

## Schema Files

These schemas live in `shared/schemas/` as JSON Schema files:

- `shared/schemas/drone_function_calls.json`
- `shared/schemas/egs_function_calls.json`
- `shared/schemas/operator_commands.json`

All Python validation code imports from these files. Flutter dashboard reads them too for displaying expected vs actual structures during the demo.

## Versioning

These schemas are **v1 (locked)**. If we discover a real bug after Day 7, we version-bump to v1.1 and update everywhere. Casual additions are NOT allowed — they break parallel work.

## What Could Go Wrong

| Failure | Mitigation |
|---|---|
| Gemma 4 doesn't call a function (returns prose) | Validation node treats this as failure, retries with corrective prompt |
| Function name typo from Gemma 4 | Strict enum validation; retry |
| Argument types wrong | Strict type validation; retry with explicit type hint in corrective prompt |
| Two valid options exist (model picks wrong one) | Tighten the system prompt's decision criteria |
