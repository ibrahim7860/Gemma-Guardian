# Gemma-Guardian / FieldAgent

Multi-drone disaster-response coordinator powered entirely by on-device Gemma 4. Submission to the [Gemma 4 Good Hackathon](https://www.kaggle.com/competitions/gemma-4-good-hackathon) (Kaggle × Google DeepMind).

In post-disaster zones, cell towers fail in the first hour. Drones with cloud-AI dependencies become useless when they're needed most. We took the strongest published architecture for AI-driven disaster response ([Nguyen, Truong, Le 2026](https://arxiv.org/abs/2601.14437)) and removed its cloud GPT-4.1 dependency. Every drone has a brain. Every brain stays local. Every decision survives the disaster that broke the network.

## Where to start

- **What we're building and why:** [`docs/01-vision-and-pitch.md`](docs/01-vision-and-pitch.md)
- **Architecture overview:** [`docs/04-system-architecture.md`](docs/04-system-architecture.md) — three layers: per-drone Gemma 4 E2B agent, edge ground station with Gemma 4 E4B, Flutter operator dashboard.
- **The contracts that keep us in sync:** [`docs/20-integration-contracts.md`](docs/20-integration-contracts.md) (locked Day 1, do not change).
- **Scope and gates:** [`docs/17-feasibility-and-gates.md`](docs/17-feasibility-and-gates.md), [`docs/16-mocks-and-cuts.md`](docs/16-mocks-and-cuts.md).
- **AI assistant entry point:** [`CLAUDE.md`](CLAUDE.md) (read first if Claude Code or Cursor is editing this repo).

The full doc index — vision, hackathon context, fine-tuning plan, demo storyboard, submission checklist — lives under [`docs/`](docs/) and is mapped in [`CLAUDE.md`](CLAUDE.md).

## Install

```bash
# install uv (one-time): https://docs.astral.sh/uv/
curl -LsSf https://astral.sh/uv/install.sh | sh
# pick your role's slice (or --all-extras for everything)
uv sync --extra sim --extra mesh --extra dev   # Person 1
uv sync --extra drone --extra ml --extra dev   # Person 2
uv sync --extra egs --extra dev                # Person 3
uv sync --extra ws_bridge --extra dev          # Person 4
```

Full setup (Redis, Ollama, per-platform notes, plain-pip fallback) lives in [`docs/13-runtime-setup.md`](docs/13-runtime-setup.md).

## Run the demo

```bash
# bring up Redis (system-managed) — see docs/13-runtime-setup.md for per-OS details
sudo service redis-server start    # Linux / WSL2
brew services start redis          # macOS

# one-command launch — full swarm in tmux, tails the waypoint log,
# stops cleanly on Ctrl-C.
scripts/run_full_demo.sh

# or launch with a fixed-duration self-terminate (handy for scripted demos)
scripts/launch_swarm.sh disaster_zone_v1 --duration=60
scripts/stop_demo.sh
```

The launcher is [`scripts/launch_swarm.sh`](scripts/launch_swarm.sh); how the eight processes wire together is in [`docs/15-multi-drone-spawning.md`](docs/15-multi-drone-spawning.md).

## Team

Five-person team, vertical-slice ownership. Roles, interfaces, and decision-making authority: [`docs/18-team-roles.md`](docs/18-team-roles.md). 20-day timeline: [`docs/19-day-by-day-plan.md`](docs/19-day-by-day-plan.md).

| Person | Role | Primary scope |
|---|---|---|
| Person 1 | Sim Lead | `sim/`, `agents/mesh_simulator/`, launch scripts, Redis infra |
| Person 2 | Drone Agent + ML | `agents/drone_agent/`, xBD fine-tuning |
| Person 3 | EGS Coordinator | `agents/egs_agent/`, replanning, multilingual command path |
| Person 4 | Frontend + Comms (lead) | `frontend/`, demo video, writeup, this README |
| Person 5 | Sim Co-Pilot | paired with Person 1 — frame curation, scenario YAMLs |

## Status

In active development for the May 18, 2026 submission. Per-stream live status:

- [`sim/ROADMAP.md`](sim/ROADMAP.md) — Person 1 / Person 5 surface (sim, mesh, scripts).
- [`TODOS.md`](TODOS.md) — cross-cutting follow-ups.

## License

Apache-2.0. See [`LICENSE`](LICENSE) (TBD prior to submission).
