# CLAUDE.md — FieldAgent Project Context

This file is the entry point for any AI assistant (Claude Code, Cursor, etc.) working on this repository. Read this first, then load the referenced docs as needed.

## What This Project Is

**FieldAgent** is a simulated multi-drone disaster response coordinator powered entirely by on-device Gemma 4. It is our submission to the **Gemma 4 Good Hackathon** (Kaggle × Google DeepMind, deadline May 18, 2026, $200K prize pool).

The project implements the architecture proposed in *Nguyen, Truong, Le (2026), "Agentic AI Meets Edge Computing in Autonomous UAV Swarms"* (arXiv 2601.14437) with one fundamental change: **every LLM in the system runs Gemma 4 locally, eliminating the paper's dependency on cloud GPT-4.1**. The system survives total internet failure, which is the actual condition of post-disaster zones.

## Quick Pitch

In post-disaster zones, cell towers fail in the first hour. Drones with cloud-AI dependencies become useless when they're needed most. We took the strongest published architecture for AI-driven disaster response and removed its cloud dependency. Every drone has a brain. Every brain stays local. Every decision survives the disaster that broke the network.

## Hackathon Track Fit

- **Primary:** Global Resilience (with Climate & Green Energy special-track framing)
- **Secondary:** Safety
- **Special prize plays:** Unsloth (xBD vision fine-tuning), Ollama (deployment)

## Documentation Map

Read docs in this order when getting up to speed:

### Foundation (read first)
- [`docs/01-vision-and-pitch.md`](docs/01-vision-and-pitch.md) — what we're building and why
- [`docs/02-hackathon-context.md`](docs/02-hackathon-context.md) — judging criteria, tracks, deadlines, what wins
- [`docs/03-reference-paper.md`](docs/03-reference-paper.md) — the academic paper we implement, what we change

### Architecture
- [`docs/04-system-architecture.md`](docs/04-system-architecture.md) — three-layer design overview
- [`docs/05-per-drone-agent.md`](docs/05-per-drone-agent.md) — onboard Gemma 4 E2B agent (LangGraph, 5 nodes)
- [`docs/06-edge-ground-station.md`](docs/06-edge-ground-station.md) — EGS with Gemma 4 E4B
- [`docs/07-operator-interface.md`](docs/07-operator-interface.md) — Flutter dashboard, multilingual command path
- [`docs/08-mesh-communication.md`](docs/08-mesh-communication.md) — drone-to-drone broadcasts, simulated dropout

### Gemma 4 Integration
- [`docs/09-function-calling-schema.md`](docs/09-function-calling-schema.md) — every structured output the system emits
- [`docs/10-validation-and-retry-loop.md`](docs/10-validation-and-retry-loop.md) — Algorithm 1 hallucination mitigation
- [`docs/11-prompt-templates.md`](docs/11-prompt-templates.md) — system prompts for all Gemma 4 calls
- [`docs/12-fine-tuning-plan.md`](docs/12-fine-tuning-plan.md) — Unsloth + xBD vision adapter LoRA

### Simulation
- [`docs/13-runtime-setup.md`](docs/13-runtime-setup.md) — Redis + Python + Ollama install (cross-platform)
- [`docs/14-disaster-scene-design.md`](docs/14-disaster-scene-design.md) — pre-recorded imagery and scripted-motion scenarios
- [`docs/15-multi-drone-spawning.md`](docs/15-multi-drone-spawning.md) — running 2-3 drone agent processes against one Redis broker

### Risk Management
- [`docs/16-mocks-and-cuts.md`](docs/16-mocks-and-cuts.md) — what's mocked, why, fallback paths
- [`docs/17-feasibility-and-gates.md`](docs/17-feasibility-and-gates.md) — go/no-go decision points

### Team Execution
- [`docs/18-team-roles.md`](docs/18-team-roles.md) — 5-person role breakdown
- [`docs/19-day-by-day-plan.md`](docs/19-day-by-day-plan.md) — 20-day timeline with daily milestones
- [`docs/20-integration-contracts.md`](docs/20-integration-contracts.md) — JSON schemas locked Day 1, do not change

### Submission
- [`docs/21-demo-storyboard.md`](docs/21-demo-storyboard.md) — 90-second video plan
- [`docs/22-writeup-outline.md`](docs/22-writeup-outline.md) — technical writeup structure
- [`docs/23-submission-checklist.md`](docs/23-submission-checklist.md) — what must be ready May 18

## Key Constraints (Always Respect)

1. **Gemma 4 must be doing real work.** No mocking the LLM itself. If Gemma 4 isn't visibly the agentic brain, the project has no submission.
2. **Everything offline.** No cloud APIs. Demo must include a moment showing no internet connectivity while the system operates.
3. **Function calling is the agentic backbone.** Every action-driving output is a structured function call validated against hard constraints.
4. **Day 7 is the integration gate.** If the full single-drone loop isn't working by then, scope drops further. See [`docs/17-feasibility-and-gates.md`](docs/17-feasibility-and-gates.md).
5. **Day 10 is the fine-tuning go/no-go.** See [`docs/12-fine-tuning-plan.md`](docs/12-fine-tuning-plan.md).
6. **Stack is locked Day 1, do not change.** See [`docs/20-integration-contracts.md`](docs/20-integration-contracts.md).

## Tech Stack Summary

- **OS:** macOS, Linux, or Windows 11 — all roles run cross-platform. Each developer needs Python 3.11+, Redis (`brew install redis` / `apt install redis-server` / WSL2), and Ollama. No simulator dependencies, no WSL2 requirement, no virtualization gates.
- **Drone "simulation":** Pure Python — drones move along scripted waypoint tracks at configurable speeds. "Camera frames" are pre-recorded disaster imagery (xBD post-disaster crops, public satellite/aerial photography) served from disk. No Gazebo, no PX4 SITL.
- **Inter-process messaging:** Redis pub/sub (single local `redis-server`). Channel naming: `drones.<drone_id>.state`, `drones.<drone_id>.findings`, `egs.state`, `swarm.broadcasts.<drone_id>`, etc. See [`docs/20-integration-contracts.md`](docs/20-integration-contracts.md) Contract 9.
- **LLM runtime:** Ollama, two instances (Gemma 4 E2B onboard, Gemma 4 E4B at EGS) — runs on Linux (CUDA), macOS (Metal), or Windows 11 with WSL2/CUDA. The exact Ollama tag for each Gemma 4 variant must be pinned in [`docs/20-integration-contracts.md`](docs/20-integration-contracts.md) once confirmed against `ollama.com/library` at integration time; do not hard-code a tag elsewhere.
- **Orchestration:** LangGraph (per-drone agent + EGS coordinator)
- **Fine-tuning:** Unsloth on xBD dataset (LoRA on vision adapter) — runs on Linux+NVIDIA, WSL2+NVIDIA, or rented cloud GPU (Lambda Labs / Paperspace / Runpod). Apple Silicon is not viable for the fine-tune itself, but the resulting adapter is loaded on any Ollama-supported platform.
- **Frontend:** Flutter web dashboard talking directly to a FastAPI WebSocket bridge that mirrors selected Redis channels — runs on macOS, Windows, or Linux. No `rosbridge_suite`.
- **Mesh:** Software-mocked drone-to-drone broadcasts over Redis pub/sub with Euclidean-distance dropout. Behavior is identical from the agent's perspective to a real WiFi mesh; the abstraction is documented honestly in the writeup.
- **Team hardware floor:** any modern laptop (8 GB RAM, Python 3.11+, Redis). Fine-tuning (Day 10–13) is the only step that requires a CUDA GPU; that workstream is owned by one person and uses a rented cloud GPU as a fallback.

## Repository Structure (Target)

```
gemma-guardian/
├── CLAUDE.md                        # this file
├── README.md                        # public-facing project description
├── docs/                            # all detailed documentation
├── sim/                             # software-only drone "simulator"
│   ├── waypoint_runner.py           # scripted drone motion + GPS feed
│   ├── frame_server.py              # serves pre-recorded JPEG frames per drone
│   ├── scenarios/                   # YAML scripts: waypoints, scripted failures, frame mappings
│   └── fixtures/                    # pre-recorded disaster imagery (xBD crops, public aerials)
├── agents/
│   ├── drone_agent/                 # LangGraph per-drone agent
│   ├── egs_agent/                   # LangGraph EGS coordinator
│   └── mesh_simulator/              # Redis-side range-dropout filter on /swarm channels
├── shared/
│   ├── schemas/                     # JSON Schema definitions (locked contracts)
│   ├── contracts/                   # Python loader, Pydantic mirrors, RuleID, topic constants
│   └── prompts/                     # All Gemma 4 prompt templates
├── frontend/
│   ├── flutter_dashboard/           # Operator UI
│   └── ws_bridge/                   # FastAPI WebSocket bridge (mirrors Redis channels to Flutter)
├── ml/
│   ├── data_prep/                   # xBD preprocessing scripts
│   ├── training/                    # Unsloth fine-tuning notebooks
│   └── evaluation/                  # Metrics, baselines
├── scripts/
│   ├── gen_topic_constants.py       # codegen Redis-channel constants for Python and Dart
│   ├── run_full_demo.sh             # one-command demo launcher
│   └── run_resilience_scenario.sh   # scripted failure tests
└── docs_assets/                     # video, screenshots, diagrams
```

## How to Help This Project

If you are an AI assistant being asked to work on this repo:

1. **Always read the relevant doc(s) before generating code.** Don't assume; the contracts in `docs/20-integration-contracts.md` are non-negotiable.
2. **Respect the mocks.** If something is listed in `docs/16-mocks-and-cuts.md` as deliberately mocked, do not try to "improve" it by building the real version. That risks the timeline.
3. **Cite the function-calling schema.** Any code that produces a Gemma 4 prompt must align with `docs/09-function-calling-schema.md`.
4. **Match the prompt style.** Prompts must follow the patterns in `docs/11-prompt-templates.md`, including the corrective re-prompt strings from the validation loop.
5. **Flag scope creep.** If a request would expand the project beyond what's documented, push back and reference `docs/17-feasibility-and-gates.md`.

## Contact / Owner

Project lead: Ibrahim
Hackathon: Gemma 4 Good Hackathon (Kaggle × Google DeepMind)
Submission deadline: May 18, 2026, 23:59 UTC
