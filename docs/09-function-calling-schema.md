# 09 — Function Calling Schema

## Why This Document Exists

Function calling is the agentic backbone of FieldAgent. Every Gemma 4 output that drives action is a structured function call validated against hard constraints. **Lock these schemas on Day 1 and do not change them.** All five team members build against these contracts.

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
- If `related_finding_id` provided, must reference an existing finding from this drone

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
- Each drone has at least one point (unless excluded)
- Counts are within ±1 of average across drones (balanced workload)
- Every drone in the active fleet appears in assignments

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
- `command` must be one of the seven defined types
- For each command, args must match the schema (e.g., `recall_drone` requires `drone_id` to reference an active drone)
- For `set_language`, `lang_code` must be ISO 639-1 (en, es, ar, etc.)

## How Gemma 4 Calls These

Gemma 4 supports native function calling. We provide the tool schemas in the system prompt; the model emits a function call as part of its response.

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
