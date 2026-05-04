# 06 — Edge Ground Station (EGS)

## Overview

The EGS is a single coordinator process running Gemma 4 E4B locally. It plays the role that the reference paper assigns to GPT-4.1 — but without the cloud dependency.

In real deployment, the EGS would be a portable workstation (e.g., a ruggedized laptop or a Jetson AGX Orin in a Pelican case) deployed near the disaster zone. For our hackathon, it's a separate process on the same dev machine.

## Responsibilities

The paper's EGS performs four tasks. We implement all four, mocking what's not feasible in the timeline:

1. **Wildfire boundary segmentation** — Paper uses U-Net on satellite imagery. **We mock with predefined zones.** See [`16-mocks-and-cuts.md`](16-mocks-and-cuts.md).
2. **Survey-point generation** — Deterministic: place points at uniform grid centroids inside the zone polygon. No LLM needed.
3. **Survey-point assignment to UAVs** — Gemma 4 E4B with validation loop. The first agentic showcase.
4. **Replanning when conditions change** — Gemma 4 E4B re-runs assignment when triggered.

We add three responsibilities the paper doesn't fully implement:

5. **Operator command translation** — natural language (140+ languages) → structured swarm tasks. Gemma 4 E4B with validation.
6. **Aggregated finding management** — collect findings from drones, deduplicate, prioritize, surface to operator.
7. **Telemetry-driven monitoring** — detect drone failures, low battery, comm loss; trigger replanning.

## Architecture

```
                    ┌─────────────────────────────────┐
                    │ Gemma 4 E4B (Ollama instance)   │
                    └──────────────┬──────────────────┘
                                   │
              ┌────────────────────┼─────────────────────┐
              ▼                    ▼                     ▼
       ┌─────────────┐     ┌─────────────┐      ┌──────────────┐
       │ Survey-point│     │ Operator    │      │ Replanning   │
       │ assignment  │     │ command     │      │ trigger      │
       │ + validation│     │ translation │      │ logic        │
       └─────────────┘     └─────────────┘      └──────────────┘
              │                    │                     │
              └────────────────────┼─────────────────────┘
                                   ▼
                       ┌──────────────────────┐
                       │ Shared Situation     │
                       │ State (in-memory)    │
                       └──────────┬───────────┘
                                  │
                ┌─────────────────┼──────────────────┐
                ▼                 ▼                  ▼
       Drone Telemetry      WebSocket to        Findings DB
       Subscriber           Flutter UI          (deduplicated)
```

## Task 3: Survey-Point Assignment (THE CORE)

This is the EGS's primary agentic task, faithful to the paper's Algorithm 1.

**Inputs:**
- Zone polygon (predefined, mocked)
- Generated survey points (deterministic from polygon + grid size)
- Current drone states (positions, battery, current tasks)

**Process:**

1. Build prompt for Gemma 4 E4B (see [`11-prompt-templates.md`](11-prompt-templates.md)). Include:
   - List of all survey points with IDs and coordinates
   - List of drones with current state
   - Hard constraints: "every point must be assigned to exactly one drone; balance workload; minimize travel"
   - Required output schema (function call: `assign_survey_points`)

2. Call Gemma 4 E4B.

3. **Validate** the assignment against hard constraints:
   - Total assigned points = total available points
   - No duplicate assignments
   - Every drone has at least one point (unless explicitly excluded)
   - Each drone's count is within ±1 of the average (balanced)

4. **If invalid, append corrective prompt and retry.** The exact corrections from the paper:
   - Too many points: `"You are hallucinating, creating more survey points than required. Do not invent, modify, or add any new points."`
   - Missing points: `"You have not assigned all survey points to UAVs. You must allocate all survey points to UAVs."`
   - Duplicates: `"You have assigned the same survey point to multiple UAVs. Each survey point must be assigned to exactly one UAV."`
   - Imbalanced: `"Your assignment is unbalanced. Redistribute so each UAV has approximately the same number of points."`

5. Retry up to 3 times. If still failing, fall back to a deterministic round-robin assignment and log the LLM failure.

6. Once validated, transmit assignments to drones via `drones.<id>.tasks` (Redis publish).

**This is the single most important code in the EGS.** The validation-loop catch-and-correct moment from this task is the core technical demo of the project.

## Task 4: Replanning

Triggers:
- Drone telemetry shows a drone has gone offline (no heartbeat for 10 seconds)
- Drone reports `return_to_base` due to mechanical or low battery
- Operator command modifies the mission (zone change, drone exclusion, priority change)
- Mocked "fire spread" event expands the zone polygon

**Process:** identical to Task 3, but with the updated state.

When triggered, the EGS:
1. Recomputes the zone polygon (or uses the updated one)
2. Regenerates survey points
3. Excludes survey points already completed (from telemetry)
4. Excludes drones that are unavailable
5. Calls assignment task with the new state

## Task 5: Operator Command Translation

The operator types natural language; Gemma 4 E4B translates to structured commands.

**Input:** raw operator text (any language).

**Process:**
1. Build prompt with:
   - Current swarm state summary
   - List of available command schemas (see [`09-function-calling-schema.md`](09-function-calling-schema.md))
   - Operator's text
2. Call Gemma 4 E4B.
3. Validate the output is a valid command structure.
4. Show the structured translation in the Flutter UI for operator confirmation before dispatch.

**Supported commands (initial set):**
- `restrict_zone(zone_id)` — focus on a specific zone
- `exclude_zone(zone_id)` — avoid a specific zone
- `recall_drone(drone_id, reason)` — bring a drone back
- `set_priority(finding_type, priority_level)` — prioritize a type of finding
- `set_language(lang_code)` — change UI language

If the operator text doesn't match a command structure, Gemma 4 returns an `unknown_command` indicator and the UI shows "I didn't understand that command — could you rephrase?"

**Languages tested:** at minimum English and Spanish. Stretch: Arabic. Document in writeup which were tested.

## Task 6: Aggregated Finding Management

Drones independently emit findings. The EGS:

1. Receives all findings via `drones.*.findings` (Redis pattern subscribe `PSUBSCRIBE drones.*.findings`)
2. Deduplicates: if two findings have the same type and GPS within 10 meters and within 60 seconds, merge them (take the higher confidence, append both visual descriptions)
3. Prioritizes: maintain a priority queue ordered by `severity × confidence`
4. Pushes to operator UI via WebSocket bridge

**No LLM needed here** — pure rule-based logic.

## Task 7: Telemetry Monitoring

The EGS subscribes to `drones.*.state` (Redis pattern subscribe `PSUBSCRIBE drones.*.state`) from each drone and watches for:

- **Heartbeat loss:** no state update for 10 seconds → mark drone as failed, trigger replanning
- **Low battery:** below 20% → suggest recall to operator
- **High validation failure rate:** if a drone has >5 validation failures in 60 seconds → operator alert (drone may need restart)

These trigger automatic replanning or operator notifications.

## State Schema

The EGS maintains a single shared state object:

```json
{
  "mission_id": "demo_run_5",
  "mission_status": "active",
  "zone_polygon": [[...], [...], ...],
  "survey_points": [
    {"id": "sp_001", "lat": ..., "lon": ..., "assigned_to": "drone1", "status": "pending"},
    ...
  ],
  "drones": {
    "drone1": {<state from drones.drone1.state Redis channel>},
    "drone2": {<state from drones.drone2.state Redis channel>}
  },
  "findings": [<deduplicated findings, priority-sorted>],
  "validation_events": [
    {"timestamp": ..., "task": "survey_assignment", "retry_count": 1, "issue": "too_many_points"},
    ...
  ],
  "operator_commands_log": [...]
}
```

This state is published in full to the FastAPI WebSocket bridge (`frontend/ws_bridge/main.py`) every 1 second via the `egs.state` Redis channel. Flutter renders from it.

## Implementation Notes

- The EGS is a single Python process using FastAPI + asyncio + LangGraph
- LangGraph layout: a coordinator graph with task nodes (assignment, command translation, replanning) plus deterministic nodes (point generation, finding dedup, telemetry monitor). The `langgraph-supervisor` `create_supervisor` primitive is the right fit if we split into specialized sub-agents; otherwise a single `StateGraph` with conditional edges is simpler and sufficient for the demo.
- Redis connection via `redis-py` async client; pattern-subscribes to `drones.*.state`, `drones.*.findings`, `swarm.broadcasts.*`. Publishes to `drones.<id>.tasks` and `egs.state`.
- Ollama call to Gemma 4 E4B via the local HTTP API (`POST http://localhost:11434/api/chat`). Pass `format: <JSON Schema>` to force structured output for the function-calling schema in [`09-function-calling-schema.md`](09-function-calling-schema.md), or use `tools` for native tool-calling — pick one and stay consistent across calls. `stream: false` for assignment-style calls so we can validate the full response before retrying.
- WebSocket to Flutter via the FastAPI bridge at `frontend/ws_bridge/main.py` (`ws://localhost:9090`); the bridge mirrors Redis channels to connected Flutter clients.
- All validation code is unit-tested separately from LLM calls

## Performance Notes

Gemma 4 E4B is bigger and slower than E2B. Expect:
- 5-15 seconds per inference call on RTX 4090
- The assignment task is the slowest because the prompt is largest

This is fine because EGS calls are infrequent:
- Initial assignment: once at mission start
- Replanning: every 30-60 seconds typically, occasionally faster
- Operator command translation: when operator types

If Gemma 4 E4B is too slow, fall back to E2B for the EGS too. Frame it in the writeup as "the EGS LLM is also lightweight to enable deployment on smaller portable edge hardware." This is an acceptable degradation.

## Optional: Driving Findings Without the Drone Agent

Until Person 2's `agents/drone_agent/main.py` lands, you can rehearse Task 6
(Aggregated Finding Management) and Task 7 (Telemetry Monitoring) end-to-end
by piping hand-typed findings onto `drones.<id>.findings` from
[`sim/manual_pilot.py`](../sim/manual_pilot.py). It's a recommendation, not
a dependency — the demo always runs the real drone agent — but it's the
fastest way to *see what a drone is actually doing* on the wire while the
EGS aggregator is being built.

Recipe:

```bash
# Pane 1 — sim publishing state + camera, plus mesh forwarder.
scripts/launch_swarm.sh resilience_v1 --drones=drone2,drone3

# Pane 2 — REPL standing in for drone1's reasoning step.
uv run python sim/manual_pilot.py --drone-id drone1

# Inside the REPL — emit findings the EGS should aggregate, deduplicate,
# and surface to the operator.
(drone1) > finding victim 4 34.0028 -118.5000 0.85 Person prone, partial cover
(drone1) > finding victim 4 34.0028 -118.5000 0.82 Same target re-spotted
(drone1) > finding fire 3 33.9986 -118.5000 0.7 Smoke plume rising
```

Full command list in [`docs/15-multi-drone-spawning.md`](15-multi-drone-spawning.md).
Validation in the REPL is JSON-Schema only, so it's a useful loopback for
the *structural* contract on the channel; semantic dedup / priority logic
described in Task 6 above is yours to verify.

## What's Mocked at the EGS Layer

- U-Net wildfire segmentation → predefined polygons, optionally expanding on a timer
- Real satellite imagery feed → static aerial screenshot
- Multi-swarm coordination → single swarm only
- Forensic logging / regulatory compliance → out of scope

See [`16-mocks-and-cuts.md`](16-mocks-and-cuts.md) for full mock rationale.
