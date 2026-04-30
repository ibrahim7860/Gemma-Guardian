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
                          │ WebSocket via rosbridge
                          ▼
┌─────────────────────────────────────────────────────────┐
│ Layer 2: Edge Ground Station (EGS)                      │
│   Gemma 4 E4B (Ollama instance)                         │
│   LangGraph coordinator: zone allocation, replanning,   │
│   command translation, validation loop                  │
└─────────────────────────────────────────────────────────┘
                          ▲
                          │ Telemetry + commands via ROS 2
                          ▼
┌─────────────────────────────────────────────────────────┐
│ Layer 1: Per-Drone Agents (×2-3)                        │
│   Each: Gemma 4 E2B (Ollama instance, time-shared)      │
│   LangGraph agent: perception, reasoning, action,       │
│   memory, coordination                                  │
└─────────────────────────────────────────────────────────┘
                          ▲
                          │ ROS 2 + PX4 + Gazebo
                          ▼
┌─────────────────────────────────────────────────────────┐
│ Simulation: Gazebo Harmonic + PX4 SITL                  │
│   Disaster scene world, drone models, cameras           │
└─────────────────────────────────────────────────────────┘
```

## Layer 1 — Per-Drone Agent

Each drone is a fully-simulated PX4 quadcopter with a downward-facing camera. On top of the simulated drone, we run an autonomous agent:

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

- **Drone ↔ Drone:** ROS 2 topics with simulated range-based dropout. Each drone publishes findings on `/swarm/broadcasts/<drone_id>`; all drones subscribe.
- **Drone ↔ EGS:** ROS 2 topics for telemetry (`/drones/<id>/state`) and commands (`/drones/<id>/tasks`).
- **EGS ↔ Operator:** rosbridge_suite WebSocket bridge into Flutter.

In real deployment this is WiFi mesh; in simulation we use namespaced ROS 2 with software dropout. See [`08-mesh-communication.md`](08-mesh-communication.md).

## Data Flow Example: A Single Finding

This walks through a finding from camera frame to operator approval:

```
1. Drone 1's PX4 publishes camera frame on /drones/1/camera
2. Drone 1's Perception node samples one frame at 1 Hz
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
   a. Publishes finding on /swarm/broadcasts/drone1 (peers receive)
   b. Publishes telemetry on /drones/1/state (EGS receives)
9. EGS receives, adds to shared picture, pushes to operator UI via WebSocket
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
- Real GPS + sensor fusion (Gazebo's defaults)
- xView2 / xBD inference at runtime (fine-tuned adapter is loaded once at startup)

See [`16-mocks-and-cuts.md`](16-mocks-and-cuts.md) for the rationale on each.

## Hardware Profile

Required for development:
- At least one machine running the simulation stack on Ubuntu 22.04 — either **native install** OR **WSL2 on Windows 11** (32+ GB RAM, 100+ GB free disk; NVIDIA GPU strongly preferred for multi-drone scenes).
- VirtualBox/Parallels-class VMs are NOT acceptable; WSL2 is acceptable because it provides near-native Linux performance with WSLg GUI support.
- Apple Silicon Macs are acceptable for the agent (Ollama Metal), EGS, and frontend roles, but NOT for the simulation stack.
- Fine-tuning runs on a Linux+NVIDIA machine (WSL2 with NVIDIA GPU works) OR on a rented cloud GPU instance (Lambda Labs / Paperspace / Runpod). See [`12-fine-tuning-plan.md`](12-fine-tuning-plan.md).
- Designate one "demo box" by Day 1 — the machine the final video gets recorded from. This must be a stable native-Ubuntu or well-tested WSL2 setup.

Theoretical real-deployment hardware (we cite this in the writeup but don't deploy):
- Per-drone: NVIDIA Jetson Orin NX (70 TOPS, 10-25W) running Gemma 4 E2B
- EGS: Portable workstation with single GPU running Gemma 4 E4B
- Mesh: WiFi 6 or WiFi-Halow
