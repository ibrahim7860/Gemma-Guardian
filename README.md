# Gemma-Guardian / FieldAgent

Multi-drone disaster-response coordinator powered entirely by on-device Gemma 4. Submission to the [Gemma 4 Good Hackathon](https://www.kaggle.com/competitions/gemma-4-good-hackathon) (Kaggle × Google DeepMind, deadline May 18, 2026).

In post-disaster zones, cell towers fail in the first hour. Drones with cloud-AI dependencies become useless when they're needed most. We took the strongest published architecture for AI-driven disaster response ([Nguyen, Truong, Le 2026](https://arxiv.org/abs/2601.14437)) and removed its cloud GPT-4.1 dependency. Every drone has a brain. Every brain stays local. Every decision survives the disaster that broke the network.

![Operator dashboard rendering a live `report_finding` from drone1](docs_assets/dashboard-finding-rendered.png)

*Live capture: drone1's onboard Gemma 4 E2B fires `report_finding` on a CC0 FEMA Hurricane Katrina aerial; the finding traverses Redis → FastAPI bridge → Flutter dashboard. Capture procedure: [`docs/runbooks/mcp-dom-verification.md`](docs/runbooks/mcp-dom-verification.md).*

## Submission links

- **Kaggle Model (C2A victim-detection LoRA):** [`gemma4-e2b-victim-vision-lora-c2a`](https://www.kaggle.com/models/ibrahimahmed7860/gemma4-e2b-victim-vision-lora-c2a)
- **Kaggle Notebook (training):** [`gemma-4-e2b-victim-vision-lora-c2a-disaster`](https://www.kaggle.com/code/ibrahimahmed7860/gemma-4-e2b-victim-vision-lora-c2a-disaster)
- **Demo video:** [TODO: insert YouTube URL after upload]
- **Technical writeup:** [`WRITEUP.md`](WRITEUP.md)

## Demo video

*Submission video link added once the Beat 5 capture is final (target: Day 15, May 17, 2026).* Storyboard and capture rig: [`docs/21-demo-storyboard.md`](docs/21-demo-storyboard.md), [`scripts/run_beat5_capture.sh`](scripts/run_beat5_capture.sh).

## Quick start

```bash
git clone https://github.com/ibrahim7860/Gemma-Guardian.git
cd Gemma-Guardian
curl -LsSf https://astral.sh/uv/install.sh | sh   # one-time, https://docs.astral.sh/uv/
uv sync --all-extras
scripts/pull_models.sh                            # pulls gemma4:e2b + gemma4:e4b via ollama
brew services start redis    # macOS — see docs/13-runtime-setup.md for Linux/WSL2

# pane 1: full agent stack (sim + drones + EGS + bridge) on :9090
scripts/run_full_demo.sh disaster_zone_v1 --duration=60

# pane 2: Flutter dashboard dev server on :8000, talks to the bridge above
scripts/run_dashboard_dev.sh
```

Open the dashboard at [`http://localhost:8000/?ws=ws://127.0.0.1:9090/`](http://localhost:8000/?ws=ws://127.0.0.1:9090/). Clean up with `scripts/stop_demo.sh`.

For the cold-start path from a fresh box (no prior repo context, no warm uv cache), follow [`docs/sim-reproduction.md`](docs/sim-reproduction.md). It's the doc Phase G is locked to; a v1 cold-run from a fresh clone was completed on M1 macOS on 2026-05-12, and a fresh-machine outside-tester pass on Linux/WSL2 lands Days 15–16.

## C2A victim-detection adapter

The drone agent loads the C2A LoRA adapter in-process via [`agents/drone_agent/c2a_inference.py`](agents/drone_agent/c2a_inference.py) (PEFT/HF Transformers route — Unsloth's GGUF vision-tower export is blocked on [unslothai/unsloth#2290](https://github.com/unslothai/unsloth/issues/2290), so the adapter runs alongside Ollama rather than through it). Point at the adapter directory with the `--c2a-adapter-path` CLI flag on `python -m agents.drone_agent`:

```bash
uv run python -m agents.drone_agent --drone-id drone1 \
    --c2a-adapter-path kaggle_work_c2a/adapter/
```

Adapter weights live under [`kaggle_work_c2a/adapter/`](kaggle_work_c2a/) once the training notebook has been run, or can be pulled directly from the [Kaggle Model](https://www.kaggle.com/models/ibrahimahmed7860/gemma4-e2b-victim-vision-lora-c2a) (~120 MB, `Transformers/lora-c2a-bf16` variant). On adapter load failure the agent falls back transparently to the Ollama reasoning path; see the docstring at the top of `c2a_inference.py` for the unwrap/rename fixes baked into the loader.

## Hardware requirements

Reproduction works on **macOS (Metal), Linux (CPU or CUDA), or Windows 11 (WSL2)**:

- 16 GB RAM minimum (sufficient on Apple Silicon with the tuning recipe linked below; 32 GB recommended for headroom on Linux/CUDA where Ollama can't lean on Metal unified memory)
- 50 GB free disk (Gemma 4 E2B is 7.2 GB, E4B is 9.6 GB; `uv` + Flutter deps add ~5 GB)
- NVIDIA GPU optional — Ollama runs on CPU, Metal, or CUDA. The xBD fine-tune (Kaleel's GATE 3) needs a CUDA GPU; the resulting adapter loads on any Ollama-supported platform.

Apple Silicon M1 16GB note: the 3-drone concurrent vision+tools path requires Ollama tuning (`OLLAMA_NUM_PARALLEL=1`, KV-quant, flash attention). Full recipe: [`docs/plans/2026-05-12-drone3-reliability-capture.md`](docs/plans/2026-05-12-drone3-reliability-capture.md).

## Technical writeup

[`WRITEUP.md`](WRITEUP.md) — the ≤1,500-word Kaggle Writeup submission version (page-verified cap 2026-05-13). Long-form working draft retained at [`docs/22-writeup-draft.md`](docs/22-writeup-draft.md) for internal reference. Section budget: [`docs/22-writeup-outline.md`](docs/22-writeup-outline.md).

## Where to start

- **What we're building and why:** [`docs/01-vision-and-pitch.md`](docs/01-vision-and-pitch.md)
- **Architecture overview:** [`docs/04-system-architecture.md`](docs/04-system-architecture.md) — three layers (per-drone Gemma 4 E2B, EGS with Gemma 4 E4B, Flutter dashboard) with end-to-end flow diagrams for the command and finding paths.
- **The contracts that keep us in sync:** [`docs/20-integration-contracts.md`](docs/20-integration-contracts.md) (locked Day 1, do not change).
- **Scope and gates:** [`docs/17-feasibility-and-gates.md`](docs/17-feasibility-and-gates.md), [`docs/16-mocks-and-cuts.md`](docs/16-mocks-and-cuts.md).
- **AI assistant entry point:** [`CLAUDE.md`](CLAUDE.md) (read first if Claude Code or Cursor is editing this repo).

The full doc index — vision, hackathon context, fine-tuning plan, demo storyboard, submission checklist — lives under [`docs/`](docs/) and is mapped in [`CLAUDE.md`](CLAUDE.md).

## Per-role install

If you only need one slice of the stack, install the relevant extras instead of `--all-extras`:

```bash
uv sync --extra sim --extra mesh --extra dev   # Hazim   (sim + mesh)
uv sync --extra drone --extra ml --extra dev   # Kaleel  (drone agent + fine-tune)
uv sync --extra egs --extra dev                # Qasim   (EGS coordinator)
uv sync --extra ws_bridge --extra dev          # Ibrahim (bridge + dashboard)
```

Full setup (Redis, Ollama, per-platform notes, plain-pip fallback) lives in [`docs/13-runtime-setup.md`](docs/13-runtime-setup.md). The launcher contract (process wiring + transitional mocks) is in [`docs/15-multi-drone-spawning.md`](docs/15-multi-drone-spawning.md) + [`docs/16-mocks-and-cuts.md`](docs/16-mocks-and-cuts.md).

## Additional demo flavors

```bash
# fixed-duration scripted demo (sim runners self-terminate after N seconds;
# drone agents and EGS stay alive for inspection)
scripts/launch_swarm.sh disaster_zone_v1 --duration=60
scripts/stop_demo.sh

# bridge cutover hybrid (real sim drone state + fake EGS/findings until
# Qasim/Kaleel ship the real publishers — pass --no-fake-egs / --no-fake-findings
# to drop the fakes incrementally)
scripts/run_hybrid_demo.sh disaster_zone_v1
scripts/stop_demo.sh hybrid_demo

# Beat 5 offline-proof capture rig (wifi-drop simulation with buffered findings
# replay through the dashboard) — see docs/runbooks/mcp-dom-verification.md
scripts/run_beat5_capture.sh
```

## Team

Five-person team, vertical-slice ownership. Roles, interfaces, and decision-making authority: [`docs/18-team-roles.md`](docs/18-team-roles.md). 20-day timeline: [`docs/19-day-by-day-plan.md`](docs/19-day-by-day-plan.md).

| Person | Role | Primary scope |
|---|---|---|
| Hazim | Sim Lead | `sim/`, `agents/mesh_simulator/`, launch scripts, Redis infra |
| Kaleel | Drone Agent + ML | `agents/drone_agent/`, xBD fine-tuning |
| Qasim | EGS Coordinator | `agents/egs_agent/`, replanning, multilingual command path |
| Ibrahim | Frontend + Comms (lead) | `frontend/`, demo video, writeup, this README |
| Thayyil | Sim Co-Pilot | paired with Hazim — frame curation, scenario YAMLs |

## Status

In active development for the May 18, 2026 submission. Per-stream live status:

- [`sim/ROADMAP.md`](sim/ROADMAP.md) — Hazim / Thayyil surface (sim, mesh, scripts).
- [`TODOS.md`](TODOS.md) — cross-cutting follow-ups.

## License

Apache-2.0. See [`LICENSE`](LICENSE).

## Citation

If you build on this work, please cite both the project and the reference paper it implements:

```
@misc{gemmaguardian2026,
  title  = {Gemma-Guardian / FieldAgent: Offline Multi-Drone Disaster Response with Gemma 4},
  author = {{FieldAgent Team} (Ibrahim Ahmed, Hazim Kuniyil, Kaleel, Qasim, Thayyil)},
  year   = {2026},
  url    = {https://github.com/ibrahim7860/Gemma-Guardian}
}

@misc{nguyen2026agentic,
  title  = {Agentic AI Meets Edge Computing in Autonomous UAV Swarms},
  author = {Nguyen, T. M. and Truong, V. T. and Le, L. B.},
  year   = {2026},
  url    = {https://arxiv.org/abs/2601.14437}
}
```
