# 04 — System Architecture

## Three Layers

The system has three layers, exactly mapping to the reference paper's edge-enabled architecture (Architecture B from Nguyen et al. 2026):

```
┌─────────────────────────────────────────────────────────┐
│ Layer 3: Operator Interface                             │
│   Flutter dashboard, multilingual command box,          │
│   live map, findings approval (HITL)                    │
└─────────────────────────────────────────────────────────┘
                          ▲
                          │ WebSocket via FastAPI bridge
                          │ (ws://localhost:9090)
                          ▼
┌─────────────────────────────────────────────────────────┐
│ Layer 2: Edge Ground Station (EGS)                      │
│   Gemma 4 E4B (Ollama instance)                         │
│   LangGraph coordinator: zone allocation, replanning,   │
│   command translation, validation loop                  │
└─────────────────────────────────────────────────────────┘
                          ▲
                          │ Redis pub/sub (localhost:6379)
                          │ drones.*.state, drones.*.findings,
                          │ drones.*.tasks, egs.state, ...
                          ▼
┌─────────────────────────────────────────────────────────┐
│ Layer 1: Per-Drone Agents (×2-3)                        │
│   Each: Gemma 4 E2B (Ollama instance, time-shared)      │
│   LangGraph agent: perception, reasoning, action,       │
│   memory, coordination                                  │
└─────────────────────────────────────────────────────────┘
                          ▲
                          │ Redis pub/sub
                          │ drones.<id>.camera (JPEG bytes),
                          │ drones.<id>.state (drone state)
                          ▼
┌─────────────────────────────────────────────────────────┐
│ Simulation: sim/ (software-only, cross-platform)        │
│   waypoint_runner.py — publishes drone state on a       │
│   scripted track at 2 Hz                                │
│   frame_server.py — publishes pre-recorded JPEG frames  │
└─────────────────────────────────────────────────────────┘
```

## Layer 1 — Per-Drone Agent

Each simulated drone is driven by `sim/waypoint_runner.py` (state) and `sim/frame_server.py` (camera frames), both publishing over Redis. On top of the simulated drone, we run an autonomous agent:

- **Inference:** Gemma 4 E2B via Ollama (time-shared across all drones in our setup; in real deployment each drone has its own Jetson Orin NX)
- **Orchestration:** LangGraph with five nodes (Perception, Reasoning, Action, Memory, Coordination)
- **Output:** Structured function calls (see [`09-function-calling-schema.md`](09-function-calling-schema.md))
- **Validation:** Local validation loop catches hallucinations before broadcasting

Detailed in [`05-per-drone-agent.md`](05-per-drone-agent.md).

## Layer 2 — Edge Ground Station

A single coordinator process running on the same machine (in production, a portable workstation):

- **Inference:** Gemma 4 E4B via separate Ollama instance
- **Responsibilities:**
  - Maintain shared situational picture from drone telemetry
  - Allocate survey points to drones (with validation loop)
  - Re-plan when conditions change (drone failure, fire spread, operator command)
  - Translate operator natural-language commands to structured swarm tasks
  - Aggregate findings and surface them to the operator UI
- **Validation loop:** Same Algorithm 1 pattern as drones, but at swarm level

Detailed in [`06-edge-ground-station.md`](06-edge-ground-station.md).

## Layer 3 — Operator Interface

Flutter web app providing the human-in-the-loop view:

- **Map view:** drone positions, survey points (color-coded per drone), fire boundary, findings as icons
- **Drone status panel:** per-drone battery, current task, current finding count, last action
- **Findings feed:** chronological, with confidence, visual description, APPROVE/DISMISS buttons
- **Command box:** multilingual natural-language input, shows Gemma 4's structured translation before dispatch

Detailed in [`07-operator-interface.md`](07-operator-interface.md).

## Communication Substrate

- **Drone ↔ Drone:** Redis pub/sub with simulated range-based dropout. Each drone publishes broadcasts on `swarm.broadcasts.<drone_id>`; the mesh simulator republishes to `swarm.<receiver_id>.visible_to.<receiver_id>` after range-filtering.
- **Drone ↔ EGS:** Redis pub/sub channels `drones.<id>.state` and `drones.<id>.findings` (drone → EGS); `drones.<id>.tasks` (EGS → drone).
- **EGS ↔ Operator:** FastAPI WebSocket bridge at `frontend/ws_bridge/main.py`, exposing `ws://localhost:9090`. Mirrors a fixed list of Redis channels; no rosbridge_suite.

All channel names follow dot-notation, glob-friendly with `redis-cli PSUBSCRIBE`. In real deployment this is WiFi mesh; in simulation we use Redis pub/sub with software dropout. See [`08-mesh-communication.md`](08-mesh-communication.md) and the canonical channel registry in [`20-integration-contracts.md`](20-integration-contracts.md).

## Data Flow Example: A Single Finding

This walks through a finding from camera frame to operator approval:

```
1. sim/frame_server.py publishes a pre-recorded JPEG frame on drones.1.camera (Redis)
2. Drone 1's Perception node samples one frame at 1 Hz from that channel
3. Perception passes (frame, current state, peer broadcasts) to Reasoning
4. Reasoning calls Gemma 4 E2B with structured prompt
5. Gemma 4 returns: report_finding(type="victim", severity=4, 
   gps_lat=..., gps_lon=..., confidence=0.78, 
   visual_description="...")
6. Validation node checks: GPS in assigned zone? Confidence threshold met? 
   Not duplicate of recent finding?
7. If invalid, retry with corrective prompt (max 3 retries).
   If valid, proceed.
8. Action node:
   a. Publishes finding on swarm.broadcasts.drone1 (Redis; mesh simulator
      redistributes to in-range peers)
   b. Publishes telemetry on drones.1.state (Redis; EGS receives)
9. EGS receives, adds to shared picture, pushes to operator UI via WebSocket bridge
10. Flutter dashboard renders the finding; operator sees "victim, severity 4, 
    confidence 0.78" with APPROVE/DISMISS buttons
11. Other drones' Memory nodes receive the broadcast; their next 
    Reasoning prompt includes "Drone 1 reports possible victim, conf 0.78"
```

This entire flow happens with no internet connection.

## Why This Architecture

Three reasons, all aligned with hackathon judging:

1. **Genuine offline operation** — no component requires cloud. The pitch isn't aspirational; it's demonstrated.
2. **Faithful to a published reference** — citing Nguyen et al. lets us claim academic credibility without overreaching.
3. **Showcases all five Gemma 4 capabilities** — vision (drone cameras), reasoning (per-drone decisions, swarm coordination), function calling (every action), multilingual (operator commands), on-device (Ollama). Nothing is bolted on.

## What's Outside the Architecture (Mocked)

- U-Net wildfire segmentation (we use predefined zones)
- Real satellite imagery (we use a static aerial screenshot)
- Real fire spread physics (we expand a polygon over time)
- Real GPS + sensor fusion (waypoint_runner.py provides synthetic GPS)
- xView2 / xBD inference at runtime (fine-tuned adapter is loaded once at startup)

See [`16-mocks-and-cuts.md`](16-mocks-and-cuts.md) for the rationale on each.

## Hardware Profile

Required for development:
- The simulation stack (`sim/waypoint_runner.py`, `sim/frame_server.py`) and all agent processes are pure Python + Redis — they run on macOS, Linux, and Windows without a GPU. Any machine with Python 3.11+ and Redis 7+ is sufficient.
- NVIDIA GPU (native Linux or WSL2 on Windows 11) is strongly preferred for Ollama inference throughput. Apple Silicon Macs run Ollama via Metal and are fully supported for all roles including sim.
- Fine-tuning still runs on a Linux+NVIDIA machine or rented cloud GPU. See [`12-fine-tuning-plan.md`](12-fine-tuning-plan.md).
- Designate one "demo box" by Day 1 — the machine the final video gets recorded from.

Theoretical real-deployment hardware (we cite this in the writeup but don't deploy):
- Per-drone: NVIDIA Jetson Orin NX (70 TOPS, 10-25W) running Gemma 4 E2B
- EGS: Portable workstation with single GPU running Gemma 4 E4B
- Mesh: WiFi 6 or WiFi-Halow
