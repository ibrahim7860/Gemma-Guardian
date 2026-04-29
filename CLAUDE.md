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
- [`docs/13-gazebo-setup.md`](docs/13-gazebo-setup.md) — Gazebo + PX4 + ROS 2 install and verification
- [`docs/14-disaster-scene-design.md`](docs/14-disaster-scene-design.md) — what the simulated world contains
- [`docs/15-multi-drone-spawning.md`](docs/15-multi-drone-spawning.md) — running 2-3 drones simultaneously

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

- **OS:** Ubuntu 22.04 — native install OR WSL2 on Windows 11 with WSLg. (VirtualBox/Parallels-class VMs still NOT acceptable.) Apple Silicon Macs are supported for non-sim roles only.
- **Simulation:** Gazebo Harmonic + PX4 SITL + ROS 2 Humble
- **LLM runtime:** Ollama, two instances (E2B onboard, E4B at EGS) — runs on Linux/WSL2 (CUDA) or macOS (Metal)
- **Orchestration:** LangGraph (per-drone agent + EGS coordinator)
- **Fine-tuning:** Unsloth on xBD dataset (LoRA on vision adapter) — runs on WSL2+NVIDIA OR rented cloud GPU (Lambda Labs / Paperspace / Runpod)
- **Frontend:** Flutter web dashboard via rosbridge_suite WebSocket — runs on macOS, Windows, or Linux
- **Mesh:** ROS 2 topics with namespaced per-drone channels, software dropout
- **Team hardware floor:** at least one team member must have a Windows 11 machine capable of running WSL2 with WSLg. See [`docs/13-gazebo-setup.md`](docs/13-gazebo-setup.md) for the platform-path selection.

## Repository Structure (Target)

```
fieldagent/
├── CLAUDE.md                        # this file
├── README.md                        # public-facing project description
├── docs/                            # all detailed documentation
├── simulation/
│   ├── worlds/                      # Gazebo world files (disaster scenes)
│   ├── px4_patches/                 # PX4 model overrides
│   └── ros2_ws/                     # ROS 2 workspace with custom packages
├── agents/
│   ├── drone_agent/                 # LangGraph per-drone agent
│   └── egs_agent/                   # LangGraph EGS coordinator
├── shared/
│   ├── schemas/                     # JSON Schema definitions (locked contracts)
│   └── prompts/                     # All Gemma 4 prompt templates
├── frontend/
│   └── flutter_dashboard/           # Operator UI
├── ml/
│   ├── data_prep/                   # xBD preprocessing scripts
│   ├── training/                    # Unsloth fine-tuning notebooks
│   └── evaluation/                  # Metrics, baselines
├── scripts/
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
