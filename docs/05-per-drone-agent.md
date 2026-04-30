# 05 — Per-Drone Agent

## Overview

Each simulated drone runs an autonomous agent built with LangGraph. The agent has five nodes that map directly to the modules described in Nguyen et al. 2026 Section II. The agent is fed camera frames, drone state, and peer broadcasts; it outputs structured function calls that drive flight behavior.

## The Five Nodes

```
                ┌──────────────┐
                │ Perception   │ ← camera frame, GPS, battery, peer broadcasts
                └──────┬───────┘
                       ▼
                ┌──────────────┐
                │ Reasoning    │ ← Gemma 4 E2B inference
                └──────┬───────┘
                       ▼
                ┌──────────────┐
                │ Validation   │ ← deterministic constraint checks
                └──────┬───────┘
                       │ (retry on failure, max 3)
                       ▼
                ┌──────────────┐
                │ Action       │ → flight commands, broadcasts, telemetry
                └──────┬───────┘
                       ▼
                ┌──────────────┐
                │ Memory       │ ← write findings, peer broadcasts, decisions
                └──────────────┘
```

The Coordination module from the paper is partly inside Reasoning (deciding how to react to peers) and partly inside Action (publishing broadcasts). We don't make it a separate node because LangGraph cycles handle it.

## Node 1: Perception

**Inputs:**
- Camera frame from `drones.<id>.camera` Redis channel (JPEG bytes published by `sim/frame_server.py`; sampled at 1 Hz, downsampled to 512×512)
- Drone state: GPS, altitude, heading, battery percentage (from `drones.<id>.state` Redis channel, published by `sim/waypoint_runner.py`)
- Currently assigned task and survey points
- Recent peer broadcasts (from Memory; arrived on `swarm.<id>.visible_to.<id>`)
- Recent operator commands relevant to this drone

**Outputs:**
- A structured perception bundle for the Reasoning node

**Implementation notes:**
- Use `redis-py` async client to subscribe to `drones.<id>.camera` and `drones.<id>.state`
- Use OpenCV for frame downsampling after decoding JPEG bytes
- Don't do object detection here — Gemma 4 handles that. Perception just structures the inputs.
- Channel names are generated constants from `shared/contracts/topics.py`; see [`20-integration-contracts.md`](20-integration-contracts.md).

## Node 2: Reasoning

**Inputs:** the perception bundle.

**Process:**
1. Build a system prompt that includes hard constraints, current state, and the function-calling schema (see [`11-prompt-templates.md`](11-prompt-templates.md))
2. Build a user message that includes the image plus the structured state context
3. Call Gemma 4 E2B via Ollama
4. Parse the function call from the response

**Outputs:** a tentative function call (see [`09-function-calling-schema.md`](09-function-calling-schema.md))

**Implementation notes:**
- Use `ChatOllama` from `langchain-ollama` (or call the Ollama Python client `ollama.chat(...)` directly with `format=<json-schema>` for structured output, and `images=[...]` for the camera frame on a vision-capable Gemma 4 tag).
- Confirm the exact Ollama tag for the Gemma 4 E2B (effective-2B) variant once Gemma 4 ships on Ollama; pin the tag in `shared/prompts/` config and the `docker-compose`/launch script. Until then, treat the model name as a config string, not a hardcoded literal.
- The reasoning prompt is the most performance-sensitive part of the system. Iterate on it heavily during Week 2.
- If Gemma 4 returns invalid JSON or doesn't call a function, treat as a validation failure (will retry).

## Node 3: Validation

This is the Algorithm 1 pattern from Nguyen et al. Deterministic Python code that checks the function call against hard constraints. **No LLM call here** — the whole point is to catch LLM mistakes.

**Hard constraints checked (per function):**

For `report_finding`:
- GPS coordinates fall within the drone's assigned zone (or within sensor range of current position)
- Confidence is in [0, 1]
- Severity is in [1, 5]
- Type is one of the allowed enum values
- Visual description is non-empty and at least 10 characters
- Not a duplicate of a finding reported in the last 30 seconds

For `mark_explored`:
- Zone ID is one currently assigned to this drone
- Coverage percentage is in [0, 100]

For `request_assist`:
- Reason is non-empty
- Urgency is one of the allowed enum values

For `return_to_base`:
- Reason is one of the allowed enum values

For `continue_mission`:
- Always valid (no-op)

**On validation failure:**
1. Construct a corrective prompt (see [`10-validation-and-retry-loop.md`](10-validation-and-retry-loop.md) and [`11-prompt-templates.md`](11-prompt-templates.md))
2. Append it to the conversation
3. Re-call Gemma 4
4. Re-validate

Cap at 3 retries. If still failing, fall back to `continue_mission()` and log the failure to telemetry. The operator UI surfaces these failures.

## Node 4: Action

Translates the validated function call into Redis publishes. All channel names are sourced from `shared/contracts/topics.py` (see [`20-integration-contracts.md`](20-integration-contracts.md)).

**For `report_finding`:**
- Publish on `swarm.broadcasts.<id>` (mesh simulator redistributes to in-range peers)
- Publish on `drones.<id>.findings` (EGS receives)
- Continue current flight task

**For `mark_explored`:**
- Update local task state
- Publish updated state on `drones.<id>.state` (EGS will assign next survey point)

**For `request_assist`:**
- Publish on `swarm.broadcasts.<id>` with a special priority flag
- Continue current flight task while waiting for response

**For `return_to_base`:**
- Update task state to "returning"; `sim/waypoint_runner.py` observes state and navigates back to launch coordinate
- Publish updated state on `drones.<id>.state`

**For `continue_mission`:**
- No action; next loop iteration

## Node 5: Memory

Two stores:

**Short-term (last 30 seconds):**
- Recent perceptions
- Recent function calls (own and peers')
- Recent operator commands
- Used directly in the Reasoning prompt

**Long-term (mission lifetime):**
- All findings (own and peers')
- All explored zones
- All decisions made and their outcomes
- Used for queries like "have I already reported this victim?" (deduplication) and for the EGS to access via telemetry

Implementation: in-process Python dicts/lists, persisted to disk every 10 seconds for crash recovery.

## The Loop

The agent runs as an asyncio loop:

```python
async def agent_loop(drone_id):
    while mission_active:
        perception = await perception_node()
        for retry in range(3):
            tentative_call = await reasoning_node(perception)
            if validation_node(tentative_call):
                break
            perception = add_corrective_context(perception, tentative_call)
        else:
            tentative_call = continue_mission()
        
        await action_node(tentative_call)
        memory_node.write(perception, tentative_call)
        
        await asyncio.sleep(1.0)  # 1 Hz sampling
```

In production this loop has more structure (LangGraph manages the state machine via `StateGraph` with `add_node` / `add_edge` / `add_conditional_edges`, with the Validation→Reasoning retry expressed as a conditional edge gated by retry count in state), but conceptually that's it.

## Inference Sharing Across Drones

Real deployment has one Jetson per drone. Our simulation has one machine. With 2-3 drones each calling Gemma 4 E2B at 1 Hz, we have a single Ollama E2B instance serving all drones via a request queue.

**Implementation:**
- One Ollama instance running Gemma 4 E2B (HTTP API at `http://localhost:11434/api/chat`)
- All drone agents make HTTP calls to that instance
- Calls are serialized by Ollama per-model (concurrent requests queue against the loaded model)
- Effective throughput: ~1-3 inferences/second on an RTX 4090 — confirm with a smoke test once the actual Gemma 4 E2B tag is published; treat the number as a planning estimate, not a measured guarantee.

If 1 Hz × 3 drones (= 3 inferences/sec) saturates the GPU, drop to 0.5 Hz per drone (= 1.5/sec) and frame as "tactical sampling cadence" in the writeup.

## State Schema

Each drone's state is published on `drones.<id>.state` (Redis) at 2 Hz by `sim/waypoint_runner.py` and kept current by the agent:

```json
{
  "drone_id": "drone1",
  "timestamp": "2026-05-15T14:23:11.342Z",
  "position": {"lat": 34.1234, "lon": -118.5678, "alt": 25.0},
  "battery_pct": 87,
  "heading_deg": 135,
  "current_task": "survey_zone_a",
  "assigned_survey_points_remaining": 12,
  "last_action": "report_finding",
  "last_action_timestamp": "2026-05-15T14:23:08.119Z",
  "validation_failures_total": 2,
  "findings_count": 4,
  "in_mesh_range_of": ["drone2", "egs"]
}
```

## What Could Go Wrong

| Failure | Mitigation |
|---|---|
| Ollama hangs / OOM | Restart script. Single Ollama instance is the single point of failure; document this. |
| Gemma 4 outputs malformed JSON | Validation catches it, retry with corrective prompt |
| Gemma 4 hallucinates GPS outside zone | Validation catches via geofence check |
| Redis channel unavailable / frame_server not running | Perception node uses last known frame and lowers confidence |
| Redis pub/sub lag | Set 0.5 Hz sampling, document |
| Network drop in simulation | Mesh dropout simulation via mesh_simulator; expected and demonstrable feature |
