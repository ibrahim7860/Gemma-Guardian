# 10 — Validation and Retry Loop

## Why This Doc Exists

The validation-and-retry loop is the most important pattern in the entire project. It is the technical innovation we showcase, the wow moment in the demo, and the answer to the central failure mode of LLM-driven systems: hallucination.

This pattern is taken directly from Nguyen, Truong, Le (2026) Algorithm 1 — *"Hallucination Mitigation via Constraint-Conditioned Re-prompting"* (arXiv 2601.14437). We implement it identically and adapt it to our function-calling schema. The four invariants of Algorithm 1 — (a) explicit hard constraints in the prompt, (b) deterministic post-hoc validation, (c) corrective re-prompt that includes the model's own failed output, (d) bounded retries with a safe fallback — all map 1:1 onto the loop below.

## The Pattern

```
1. Build a prompt with hard constraints stated explicitly
2. Call the LLM (Gemma 4)
3. Receive structured output (a function call)
4. DETERMINISTIC code validates the output against hard constraints
5. If valid → execute
6. If invalid → append a CORRECTIVE PROMPT and retry
7. Cap retries at N (we use 3)
8. If all retries fail → fall back to a safe default + log to telemetry
```

The deterministic validation is critical. We are NOT using another LLM to check the first LLM's work — that compounds the hallucination problem. We use plain Python checks against schema and constraints.

Concretely, the validator stack is:

1. **Shape/type validation** — `jsonschema.Draft202012Validator` (per JSON Schema 2020-12) for the function-call envelope. We instantiate once per schema, call `Draft202012Validator.check_schema(schema)` at startup, and use `iter_errors(instance)` to collect every shape error in one pass rather than failing on the first.
2. **Semantic validation** — Pydantic v2 models for typed argument coercion. We catch `pydantic.ValidationError` and read `e.errors()` (list of `ErrorDetails` dicts with `type`, `loc`, `msg`, `input`) to produce the corrective prompt fields below.
3. **Cross-cutting constraints** — plain Python: zone-bounds checks, duplicate detection, monotonic coverage, severity↔confidence rule, etc. These cannot be expressed in JSON Schema or Pydantic alone.

The retry loop itself is hand-written (see pseudocode below). We deliberately do **not** use `tenacity` for the outer retry: tenacity retries an idempotent callable, but our retry mutates the conversation (appends the failed attempt + corrective prompt) between attempts, so a manual loop is clearer and easier to log.

## The Three Validation Layers

The system has three places where this loop applies:

### Layer 1: Per-Drone Function Calls

Validates the drone agent's output (see [`09-function-calling-schema.md`](09-function-calling-schema.md) for the rules).

### Layer 2: EGS Coordinator Function Calls

Validates `assign_survey_points` and `replan_mission` outputs.

### Layer 3: Operator Command Translation

Validates that the EGS correctly parsed the operator's natural language into a known command structure.

## Corrective Prompts (Verbatim)

These are the strings appended to the prompt context when validation fails. They follow the paper's pattern of being terse, specific, and directive.

Each corrective string below is the **inner** message. At call-site it is wrapped with the standard envelope defined in [`11-prompt-templates.md`](11-prompt-templates.md):

```
Your previous response was rejected because: {failure_reason}

{corrective_prompt_from_table_below}

Try again. Call exactly one function.
```

The wrapper is identical for the drone agent, EGS, and operator-command paths. Only the inner string differs.

### Drone agent corrective prompts

| Failure | Corrective Prompt |
|---|---|
| Reported severity 4+ with confidence < 0.6 | `"You reported a severity {severity} finding with confidence {conf}. For severity 4 or higher, confidence must be at least 0.6. Either lower the severity or increase confidence with stronger visual evidence, or use continue_mission() if you are uncertain."` |
| GPS outside assigned zone | `"You reported a finding at GPS ({lat}, {lon}) but your assigned zone bounds are {bounds}. The finding must be within your zone. Either correct the coordinates if you mistyped, or use continue_mission() if the target is outside your zone."` |
| Duplicate finding | `"You reported a {type} at this location 23 seconds ago. Do not duplicate findings. If this is a different target, describe the difference. Otherwise call continue_mission()."` |
| Visual description too short | `"Your visual description was too short or empty. Provide at least 10 characters describing what you see in the image that supports this classification."` |
| Invalid function name | `"You called a function that does not exist. The available functions are: report_finding, mark_explored, request_assist, return_to_base, continue_mission. Call exactly one of these."` |
| Returned prose instead of function call | `"You returned prose instead of a function call. You must call exactly one function. The available functions are: report_finding, mark_explored, request_assist, return_to_base, continue_mission."` |
| Mark_explored coverage decreased | `"You reported coverage of {new}% but previously reported {old}%. Coverage cannot decrease. Provide a coverage value greater than or equal to {old}%."` |

### EGS corrective prompts (from the paper, adapted)

| Failure | Corrective Prompt |
|---|---|
| Too many survey points assigned | `"You are hallucinating, creating more survey points than required. Do not invent, modify, or add any new points. There are exactly {n} survey points. Reassign so that exactly these {n} points are distributed across drones."` |
| Missing survey points | `"You have not assigned all survey points to UAVs. You must allocate all survey points to UAVs. The unassigned points are: {missing_ids}. Add them to the assignment."` |
| Duplicate assignment | `"You assigned the same survey point to multiple UAVs. Each survey point must be assigned to exactly one UAV. The duplicates are: {dup_ids}. Remove duplicates."` |
| Imbalanced workload | `"Your assignment is unbalanced. Drone {max_drone} has {max_count} points and drone {min_drone} has {min_count} points. Redistribute so each UAV has approximately the same number of points (within ±1)."` |
| Drone excluded that should be included | `"You did not assign any survey points to drone {drone_id}, but it is in the active fleet. Either explicitly exclude it (with a reason) or assign it survey points."` |

### Operator command corrective prompts

| Failure | Corrective Prompt |
|---|---|
| Unknown command structure | `"The command you produced is not in the available command set. Available commands: {command_list}. Either pick one of these or return unknown_command with a clarifying question."` |
| Invalid arguments | `"The arguments for command {command} are invalid. Required schema: {schema}. Fix the arguments and retry."` |
| Drone ID doesn't exist | `"You referenced drone {id} which is not in the active fleet. Active drones: {active_list}. Use one of these or return unknown_command."` |

## Implementation: The Core Loop

Pseudocode for the per-drone agent (the EGS and operator command paths follow the same pattern):

```python
from jsonschema import Draft202012Validator
from pydantic import ValidationError

# Validate schemas once at import time, not per-call.
for schema in DRONE_FUNCTION_SCHEMAS:
    Draft202012Validator.check_schema(schema)

DRONE_VALIDATORS = {s["name"]: Draft202012Validator(s) for s in DRONE_FUNCTION_SCHEMAS}

MAX_RETRIES = 3  # bounded; do not raise without updating docs/17 gates

async def reasoning_with_validation(perception_bundle, max_retries=MAX_RETRIES):
    """Returns a validated function call, or continue_mission() on total failure.

    Termination: the loop runs at most `max_retries` times. There is no
    unbounded recursion and no exception path that re-enters the loop.
    """
    conversation = build_initial_messages(perception_bundle)

    for attempt in range(max_retries):
        response = await ollama_call(
            model="gemma-4-e2b",
            messages=conversation,
            tools=DRONE_FUNCTION_SCHEMAS,
        )

        function_call = parse_function_call(response)  # may return ParseError sentinel

        # Layered validation: shape -> typed args -> semantic constraints.
        validation_result = validate_function_call(
            function_call,
            perception_bundle,
            schema_validators=DRONE_VALIDATORS,
        )

        if validation_result.valid:
            log_validation_success(attempt)
            return function_call

        log_validation_failure(attempt, validation_result.failure_reason)

        # Append the model's own failed attempt and the corrective prompt
        # (Algorithm 1: the model must see its mistake to correct it).
        conversation.append({"role": "assistant", "content": str(function_call)})
        conversation.append({
            "role": "user",
            "content": validation_result.corrective_prompt,
        })

    # All retries exhausted — emit safe fallback and telemetry event.
    log_validation_total_failure(
        agent_id=perception_bundle.agent_id,
        last_failure=validation_result.failure_reason,
    )
    emit_telemetry_event("validation_fallback_triggered")
    return continue_mission_call(reason="validation_exhausted")
```

`validate_function_call` internally:

```python
def validate_function_call(call, ctx, schema_validators):
    # 1. Shape via jsonschema (collect all errors in one pass).
    validator = schema_validators.get(call.name)
    if validator is None:
        return Invalid(reason="unknown_function", prompt=CORRECTIVE["unknown_function"])
    shape_errors = sorted(validator.iter_errors(call.arguments), key=lambda e: list(e.path))
    if shape_errors:
        return Invalid(reason="schema", prompt=format_schema_errors(shape_errors))

    # 2. Typed coercion via Pydantic v2.
    try:
        args = ARG_MODELS[call.name].model_validate(call.arguments)
    except ValidationError as e:
        return Invalid(reason="types", prompt=format_pydantic_errors(e.errors()))

    # 3. Semantic constraints (zone bounds, duplicates, severity↔confidence, ...).
    return check_semantic_constraints(call.name, args, ctx)
```

## Failure Fallback (Per Layer)

When all `MAX_RETRIES` attempts fail, each layer has a documented safe default. The fallback is never another LLM call — it is a deterministic action chosen so that a misbehaving Gemma 4 cannot drive the system into an unsafe state.

| Layer | Fallback action | Rationale |
|---|---|---|
| Per-drone agent | `continue_mission(reason="validation_exhausted")` | Drone keeps flying its current waypoint plan; no false report is emitted, no premature RTB. |
| EGS coordinator (`assign_survey_points` / `replan_mission`) | Deterministic round-robin assignment of survey points to active drones, balanced ±1 | Guarantees every point is assigned exactly once even if Gemma 4 cannot. Logged as `egs_fallback_used`. |
| Operator command translation | Return `unknown_command(operator_text, suggestion="Could not parse — please restate.")` rendered in `detected_lang` | Operator gets a clarifying request instead of a wrong action. |

Every fallback emits a `validation_fallback_triggered` telemetry event with `layer`, `agent_id`, `attempts`, and `last_failure_reason`. The frontend surfaces these in the demo UI (see `docs/07-operator-interface.md`).

## Logging Validation Events

Every validation event (success or failure) is logged for two purposes:

1. **Demo storytelling** — the operator UI shows a counter of validation failures per drone, and a feed of validation events. This is what makes the loop visible to the audience.
2. **Performance evaluation** — the writeup reports hallucination catch rate and average retries per task.

Log structure:

```json
{
  "event_type": "validation_event",
  "timestamp": "2026-05-15T14:23:11.342Z",
  "agent_id": "drone1",
  "task": "report_finding",
  "attempt": 1,
  "outcome": "failed",
  "failure_reason": "duplicate_finding",
  "corrective_prompt_used": "You reported a victim at...",
  "final_attempt": false
}
```

## Demo: Engineering a Reliable Catch-and-Correct Moment

The video needs at least one clear hallucination-correction moment on screen. We do NOT rely on Gemma 4 spontaneously hallucinating during the demo run. We **engineer the scenario**.

**Approach 1 (preferred): Constrain so the model often hallucinates.**

The EGS task with many survey points (e.g., 25 points across 3 drones) sometimes causes Gemma 4 E4B to over- or under-assign. The validation loop catches this. We script the demo to use a problem size that triggers this often (find via experimentation in Week 2-3).

**Approach 2 (backup): Inject an adversarial constraint.**

Pre-script a moment where the operator changes the zone, forcing replanning. We adversarially structure the new zone to confuse the model (e.g., very narrow, irregular shape). The model then over-assigns; the validation loop catches it; the corrective prompt fires; the second attempt succeeds.

**Approach 3 (fallback): Stub a hallucination.**

If Gemma 4 reliably succeeds during the demo, we can deterministically inject a mock failure on the FIRST attempt of one specific call (and Gemma 4 self-corrects on the second). We frame this in the writeup as "demonstrating the catch mechanism." This is acceptable as a last resort and we document it in the writeup as transparent.

The ideal demo shows a real hallucination caught in real-time. Approach 1 should produce this. Test extensively in Week 3.

## What Makes This Pattern Powerful

Three things:

1. **It's robust to model improvements.** As Gemma 4 gets better, validation failures decrease but the loop still catches edge cases.
2. **It composes.** Each function call validation is independent; we can add new constraints without changing the agent loop.
3. **It's transparent.** Every failure is visible. Judges and operators can see exactly what was caught and how.

## What Could Go Wrong

| Failure | Mitigation |
|---|---|
| Model gets stuck in a loop (same wrong output every retry) | Cap at 3 retries, fall back to safe default |
| Corrective prompts confuse rather than help | Keep them terse, directive, specific. Test each on its own. |
| Validation rule is wrong (rejects correct outputs) | Unit-test validation rules separately from LLM calls |
| Demo doesn't trigger a real catch | Scripted scenario as backup (Approach 2 or 3 above) |

## Cross-References

- Function call schemas: [`09-function-calling-schema.md`](09-function-calling-schema.md)
- Prompt templates: [`11-prompt-templates.md`](11-prompt-templates.md)
- Why this pattern is critical to the demo: [`21-demo-storyboard.md`](21-demo-storyboard.md)
