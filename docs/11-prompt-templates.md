# 11 — Prompt Templates

## Why This Doc Exists

Every Gemma 4 inference in the system uses a precisely-engineered prompt. This doc gives the canonical templates so the team builds against the same patterns and so improvements happen in one place.

All prompts share three principles:

1. **Hard constraints stated in the system prompt** (not in user messages)
2. **Decision criteria are explicit and prioritized**
3. **Output format is locked via function calling schemas**

### Gemma 4 chat-template note

Gemma's instruction-tuned chat template uses `<start_of_turn>{role}` / `<end_of_turn>` delimiters with roles `user`, `model`, and (for function calling) `developer`. Gemma does not have a native `system` role — when we say "system prompt" below, the implementation is one of:

- **Ollama path (default):** pass the constraints as a `system` message in the `/api/chat` payload. Ollama's Gemma 4 template prepends this to the first `user` turn automatically. Tools are passed via the top-level `tools` field (per [Ollama tool-calling docs](https://docs.ollama.com/capabilities/tool-calling)) and structured-JSON fallback uses `format` with a JSON Schema.
- **Direct HF / `apply_chat_template` path (fine-tuning eval only):** use the `developer` role for the constraints + tool declarations and include the activation line `"You are a model that can do function calling with the following functions"` so Gemma's function-calling logic fires. Tool schemas go through the `tools=` argument of `apply_chat_template`, not as freeform text.

Prompt files in `shared/prompts/` are template-agnostic plain text; the loader wraps them with the right role tokens for whichever runtime the call site is using.

## Per-Drone Agent Prompt

### System message

```
You are an autonomous drone in a disaster response mission. Your job is to 
survey an assigned area, identify findings (victims, fires, smoke, damaged 
structures, blocked routes), and decide what to do next.

You will receive:
- Your current state (position, battery, assigned zone, remaining survey points)
- Recent broadcasts from peer drones
- Recent operator commands
- A camera image showing what is currently below you

Available tools (call exactly ONE per response — full JSON Schema for each is
passed via Ollama's `tools` field; see [`09-function-calling-schema.md`](09-function-calling-schema.md)):
- report_finding(type, severity, gps_lat, gps_lon, confidence, visual_description)
- mark_explored(zone_id, coverage_pct)
- request_assist(reason, urgency, related_finding_id?)
- return_to_base(reason)
- continue_mission()

Hard constraints (NEVER violate):
1. For severity 4 or higher, confidence must be at least 0.6
2. GPS coordinates of any finding must be inside your assigned zone bounds
3. Visual descriptions must be at least 10 characters and describe what you 
   actually see in the image
4. Do not duplicate findings: if you reported a similar target at the same 
   location in the last 30 seconds, do not report it again
5. Coverage cannot decrease — only report mark_explored with values 
   higher than your previous report

Decision priorities (in order):
1. If you see something dangerous and high-confidence (severity 4-5), 
   report_finding immediately
2. If your battery is below 25%, return_to_base with reason="low_battery"
3. If you've completed all survey points in your zone, return_to_base 
   with reason="mission_complete"
4. If a peer reported a low-confidence finding nearby and you can investigate, 
   investigate and report_finding with higher confidence
5. If you see a possible finding but are uncertain, report_finding with 
   appropriate (lower) confidence — let the operator decide
6. Otherwise, continue_mission

When uncertain, prefer continue_mission and lower confidence over 
hallucinating findings.
```

### User message (per cycle)

```
Current state:
{state_json}

Assigned zone bounds:
{zone_bounds_json}

Survey points remaining: {n_remaining}
Currently flying toward: {next_waypoint}

Recent peer broadcasts (last 60 seconds):
{peer_broadcasts_summary}

Recent operator commands relevant to this drone:
{operator_commands_summary}

Camera image below.

What is your next action?
```

The image is attached as a separate part of the message (multimodal). Concretely, this is the `images` array on the user message in Ollama's `/api/chat` payload (base64-encoded JPEG/PNG, one frame per cycle). Gemma 4 E2B/E4B both accept image input via this path locally; no cloud vision API is involved.

### Corrective re-prompt examples

When a validation failure occurs, the failed assistant turn is preserved (so the model sees its own mistake — see [`10-validation-and-retry-loop.md`](10-validation-and-retry-loop.md)) and a new `user` turn is appended with:

```
Your previous response was rejected because: {failure_reason}

{specific_corrective_prompt_from_validation_doc}

Try again. Call exactly one function.
```

The exact corrective strings (e.g. severity/confidence mismatch, GPS-out-of-zone, duplicate finding, prose-instead-of-call, coverage-decrease) are the verbatim entries in the drone-agent table in `10-validation-and-retry-loop.md`. Do not paraphrase them at the call site — load them from `shared/prompts/drone_agent_corrective.md` so the loop logs and the prompts stay in sync.

## EGS Survey-Point Assignment Prompt

### System message

```
You are the Edge Ground Station coordinator for a multi-drone disaster 
response swarm. Your job is to assign survey points to UAVs to optimize 
coverage and mission completion time.

You will receive:
- A list of survey points (each with ID and GPS coordinates)
- A list of available drones (each with current position, battery, status)

You must call assign_survey_points exactly once with a complete assignment.

Hard constraints (NEVER violate):
1. EVERY survey point must be assigned to exactly ONE drone
2. NO survey point may appear in multiple drones' lists
3. Total assigned points must equal the number of available survey points 
   given to you (do not invent new points, do not omit given points)
4. Each drone in the active fleet must be in your assignment 
   (with at least one point unless explicitly excluded)
5. Workload must be balanced: any two drones' point counts must differ 
   by at most 1

Optimization objectives (in order):
1. Minimize total travel distance across the swarm
2. Balance workload (each drone has approximately equal points)
3. Account for battery: drones with lower battery should get points 
   closer to the ground station
4. Cluster geographically: each drone gets a contiguous region rather 
   than scattered points
```

### User message

```
Available survey points ({n_points} total):
{survey_points_json}

Available drones ({n_drones} total):
{drones_json}

Assign every survey point to exactly one drone.
```

### Corrective re-prompts (verbatim from the paper, adapted)

These are appended on validation failure. The exact strings live in [`10-validation-and-retry-loop.md`](10-validation-and-retry-loop.md) (EGS table — too-many-points, missing-points, duplicate-assignment, imbalanced-workload, drone-excluded). The two most important ones (verbatim from Nguyen et al. 2026) are reproduced here for quick reference only:

- For too many points: `"You are hallucinating, creating more survey points than required. Do not invent, modify, or add any new points."`
- For missing points: `"You have not assigned all survey points to UAVs. You must allocate all survey points to UAVs."`

Each corrective prompt is appended along with the original failed attempt (kept as an `assistant` turn) so the model sees its own mistake.

## EGS Operator Command Translation Prompt

### System message

```
You are an interpreter for natural-language commands from a human operator 
to a drone swarm. Your job is to translate the operator's input (which 
may be in any language) into one of the structured commands the system 
supports.

Available commands (full JSON Schemas in [`09-function-calling-schema.md`](09-function-calling-schema.md), Layer 3):
- restrict_zone(zone_id) — focus the swarm on one zone
- exclude_zone(zone_id) — avoid one zone
- recall_drone(drone_id, reason) — bring a drone back to base
- set_priority(finding_type, priority_level) — prioritize a type of finding
- set_language(lang_code) — change the operator UI language
- unknown_command(operator_text, suggestion) — if the input doesn't 
  clearly match any of the above

Hard constraints:
1. Use ONLY the commands listed above
2. drone_id must be one of: {active_drone_ids}
3. zone_id must be one of: {active_zone_ids}
4. finding_type must be one of: victim, fire, smoke, damaged_structure, blocked_route
5. priority_level must be one of: low, normal, high, critical
6. lang_code must be ISO 639-1 (en, es, ar, fr, etc.)
7. If the input is ambiguous or doesn't match any command, return 
   unknown_command with a clarifying suggestion written in {detected_lang}
   (the operator's input language). Do not silently switch to English.

Decision approach:
- First identify the operator's intent (focus, exclude, recall, prioritize, 
  configure, or unknown)
- Then map to the corresponding command
- Then fill in arguments based on the operator's specifics
- If the operator's specifics are missing or ambiguous, return unknown_command
```

### User message

```
Current swarm state summary:
- Active drones: {drone_list}
- Active zones: {zone_list}
- Current language: {current_lang}

Operator input (language: {detected_lang}):
"{operator_text}"

Translate this to a structured command.
```

### Corrective re-prompts

When validation fails (e.g., references a drone that doesn't exist):

```
Your previous translation was rejected because: {failure_reason}

The valid options for {field} are: {valid_options}

Re-translate using only valid values. If the operator's intent is unclear, 
return unknown_command with a clarifying suggestion in {detected_lang}.
```

## Replanning Prompt

The replanning prompt is structurally identical to survey-point assignment but with additional context about WHY replanning is happening:

```
SYSTEM: [identical to assign_survey_points system prompt]

USER:
Replanning trigger: {trigger}
{trigger_context, e.g., "Drone 3 has gone offline due to mechanical failure"}

Updated zone polygon:
{zone_polygon}

Available survey points (re-generated, {n_points} total):
{survey_points_json}

Available drones ({n_drones} total, drone3 excluded):
{drones_json}

Survey points already completed (do not include):
{completed_ids}

Re-assign every uncompleted survey point to one of the available drones.
```

## Vision Prompt Engineering Notes

For the per-drone agent's vision input, we engineer the prompt to push Gemma 4 toward specific classifications:

- For **victims**: "Look for human bodies, faces, limbs, clothing colors, or signs of distress (waving, prone with movement). Do not classify mannequins or non-human shapes as victims."
- For **fires/smoke**: "Look for visible flames, smoke columns, or charred surfaces. Distinguish smoke (gray/dark, rising) from steam, fog, or shadow."
- For **damaged structures**: "Look for collapsed walls, missing roofs, broken windows, or buildings tilted off-vertical. Classify damage severity by extent: minor (cracks, broken windows) → major (partial collapse) → destroyed (rubble pile)."
- For **blocked routes**: "Look for roads with debris, fallen trees, downed power lines, or vehicles obstructing passage."

These descriptions are part of the system prompt, refined per Week 2's prompt-engineering work.

## Prompt Files Layout

```
shared/prompts/
├── drone_agent_system.md          # the per-drone system prompt
├── drone_agent_user_template.md   # the user message template
├── drone_agent_corrective.md      # corrective prompt strings
├── egs_assignment_system.md       # the EGS assignment system prompt
├── egs_assignment_user_template.md
├── egs_assignment_corrective.md
├── egs_operator_command_system.md
├── egs_operator_command_user_template.md
├── egs_operator_command_corrective.md
└── egs_replan_system.md
```

All Python code reads these via a small loader function. Frontend can show them too if useful.

## Iterating on Prompts

Prompt engineering is iterative. The team's process:

1. Kaleel owns prompt engineering for vision tasks **and** the drone agent loop (now a single seat covering both)
2. Qasim owns prompt engineering for EGS tasks
3. Iteration happens in a notebook (`ml/prompt_iteration.ipynb`) with a small evaluation set
4. Successful changes get committed; failures are noted with metrics

**Do not change prompts in the last 3 days before submission.** Lock them by Day 17 (May 15) and only fix outright bugs after that.

## What Could Go Wrong

| Failure | Mitigation |
|---|---|
| Model ignores system prompt constraints | Move constraints into user message; use stronger language |
| Model returns prose despite tool schema | Validation catches it; corrective re-prompt |
| Multilingual prompts produce English output | Explicitly tell model to respond in {detected_lang} |
| Vision prompts cause hallucinated findings | Add stricter visual criteria; require specific evidence in description |
| Long prompts cause slow inference | Compress state JSON; remove non-critical context |
