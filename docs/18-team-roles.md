# 18 — Team Roles

## Why This Doc Exists

Five people working in parallel only succeeds if each owns a vertical slice with clear interfaces to the others. This doc defines roles, ownership boundaries, and integration responsibilities so nobody is blocked waiting for someone else.

## The Five Roles

| Person | Role | Primary Owns | Secondary Owns |
|---|---|---|---|
| Person 1 | Simulation Lead | `sim/waypoint_runner.py`, `sim/frame_server.py`, `sim/scenarios/*.yaml`, `agents/mesh_simulator/main.py`, Redis infra, launch scripts | Gate trajectory call at standup, integration testing leadership |
| Person 2 | Per-Drone Agent + ML | Drone LangGraph agent, function calling, validation loop, **xBD fine-tuning, vision prompts, adapter integration** | Prompt iteration across the full drone-side stack |
| Person 3 | EGS / Coordination | EGS LangGraph, swarm allocation, multilingual command path | Scripting resilience scenarios |
| Person 4 | The Elevator Watcher + Frontend + Demo + Comms (**Ibrahim**) | Flutter dashboard, FastAPI WebSocket bridge, demo capture, **video editing, technical writeup, README**, **overall project management** | Map view, multilingual UI, demo storyline, scope-cut arbitration |
| Person 5 | Simulation Co-Pilot (paired with Person 1) | Disaster scene frame library curation, ground-truth manifest, scenario YAML authoring, launch scripts — every sim/infra task that can be parallelized | All integration-testing prep work for Person 1 |

## Person 1: Simulation Lead

**Owns end-to-end:**
- `redis-server` infrastructure setup on the demo box (`brew install redis` / `apt install redis-server`)
- `sim/waypoint_runner.py` — reads scenario YAML, publishes `drones.<id>.state` on Redis at 2 Hz
- `sim/frame_server.py` — reads scenario YAML frame mappings, publishes `drones.<id>.camera` (JPEG bytes) on Redis at 1 Hz
- `sim/scenarios/*.yaml` — scenario authoring (drone home positions, waypoint tracks, scripted events, frame mappings)
- `agents/mesh_simulator/main.py` — Redis-side range-dropout filter; subscribes to `swarm.broadcasts.*`, republishes to `swarm.<receiver_id>.visible_to.<receiver_id>`
- The launch scripts in `scripts/` (`launch_swarm.sh`, `run_full_demo.sh`, `stop_demo.sh`)
- Integration testing (does everyone's code work together on Redis?)

**Day 1-2 output:** Redis running; `sim/waypoint_runner.py` and `sim/frame_server.py` skeleton publishing on `drones.drone1.*`; Python subscriber smoke-test prints messages.

**Day 7 output:** Two drone sim processes running together (or three if confidence is high); scenario YAML includes waypoints for both.

**Day 13 output:** Three drone sim processes running, mesh dropout simulated, resilience scenario events scripted in YAML and firing correctly.

**Interfaces with:**
- Person 2: provides `drones.<id>.camera` and `drones.<id>.state` on Redis; provides frames from `sim/fixtures/frames/` for vision prompt iteration (via Person 5)
- Person 3: provides `drones.<id>.state` for telemetry
- Person 4: the FastAPI WebSocket bridge (`frontend/ws_bridge/`) connects to the same Redis; Person 1 confirms Redis is reachable from all processes
- **Person 5 (dedicated co-pilot):** works alongside Person 1 every day on the entire sim stack — frame library curation, scenario authoring, launch scripts, integration testing. Person 5 is paired exclusively with Person 1.

**This is the highest-risk single role, which is why Person 5 is dedicated to it.** The previous stack (Gazebo + PX4 + ROS 2) had the most install-hell risk. The new Python/Redis stack significantly lowers that risk, but Person 1 still owns the most cross-component plumbing. Pairing Person 5 with Person 1 effectively turns this seat into a two-person team, doubling parallelism on the workstream most likely to block everyone else.

## Person 2: Per-Drone Agent + ML

**Owns end-to-end:**
- LangGraph agent for individual drones (5 nodes: Perception, Reasoning, Validation, Action, Memory)
- Function calling integration with Gemma 4 E2B
- Validation-and-retry loop implementation (Algorithm 1 pattern)
- Inference scheduling across multiple drones (single Ollama instance, queue)
- Drone agent system prompts and corrective re-prompts
- **Vision prompt engineering** for the drone agent
- **xBD dataset preprocessing and LoRA fine-tuning with Unsloth**
- **Day-2 Unsloth verification gate and Day-10 fine-tuning go/no-go gate**
- **Fine-tuned adapter integration into the drone agent** (if Day 10 gate passes)

**Day 1-2 output:** Standalone Python script: image + state → Gemma 4 → function call. **Day-2 Unsloth verification complete.** xBD download started.

**Day 7 output:** Full single-drone agentic loop running end-to-end with Person 1's drone. LoRA training in progress on xBD.

**Day 10 output:** Fine-tuning gate decision (GO or NO-GO).

**Day 13 output:** All drones running their agent loops in parallel. Cross-drone awareness via peer broadcasts integrated into reasoning prompt. Fine-tuned adapter integrated (if GO).

**Interfaces with:**
- Person 1: subscribes to `drones.<id>.camera` and `drones.<id>.state` on Redis; receives frames from `sim/fixtures/frames/` for vision prompt iteration (Person 5 curates these)
- Person 3: publishes findings and state for EGS to aggregate

**This role is by far the heaviest single seat on the team.** Person 2 needs strong familiarity with LangGraph, prompt engineering, Python async, *and* PyTorch / Hugging Face / Unsloth fine-tuning. They are a single point of failure for both the agent loop and the ML pipeline; the Day-10 NO-GO gate is non-negotiable insurance. **Person 5 is dedicated to Person 1, so Person 2 has no shared support resource** — if Person 2 falls behind on the agent because of fine-tuning, the team must invoke the NO-GO gate early rather than reassign help.

## Person 3: EGS / Coordination

**Owns end-to-end:**
- EGS LangGraph coordinator (separate process from drone agents)
- Gemma 4 E4B integration via separate Ollama instance
- Survey-point assignment task with validation loop
- Replanning logic triggered by drone failure / operator command / scripted event
- Multilingual operator command translation
- Aggregated finding management (deduplication, prioritization)
- Telemetry monitoring (heartbeat, low battery, comm loss)

**Day 1-2 output:** EGS process accepts mock drone states, generates valid survey-point assignment via Gemma 4.

**Day 7 output:** Real drone telemetry from Person 1 / Person 2's drones drives real assignments. Validation loop catches engineered failures.

**Day 13 output:** Replanning triggered by scripted drone failure works cleanly. Multilingual command path works for English + Spanish.

**Interfaces with:**
- Person 1: receives `drones.<id>.state` from Redis (published by `sim/waypoint_runner.py` and merged with drone agent fields)
- Person 2: sends task assignments to drone agents via `drones.<id>.tasks` on Redis
- Person 4: pushes shared state to Flutter via the FastAPI WebSocket bridge (`egs.state` on Redis → `ws://localhost:9090`); receives operator commands; provides EGS context for the writeup

Person 3 owns resilience scenario scripting alone — Person 5 is dedicated to Person 1 and not available for cross-team support.

**This role is the second most agentic-AI heavy.** Person 3 owns the wow moment: the validation loop catching a hallucination on stage. They must engineer the demo scenario where this reliably happens.

## Person 4: Frontend + Demo + Comms

**Owns end-to-end:**
- Flutter web dashboard (4-panel layout: Map, Drone Status, Findings, Command)
- FastAPI WebSocket bridge (`frontend/ws_bridge/main.py`) integration via `ws://localhost:9090`
- Real-time map rendering with drone positions, survey points, findings
- Multilingual command box with live structured-translation preview
- Findings approval flow (HITL)
- **90-second demo video** (capture, edit, narrate)
- **Technical writeup** (~2000-3000 words)
- **GitHub repo README and reproduction docs**
- **Demo storyline ownership** (proposes, team approves)

**Day 1-2 output:** Static Flutter app with mock data showing the layout.

**Day 7 output:** Live WebSocket connection, real EGS state rendered.

**Day 13 output:** Multilingual command path works end-to-end. Validation events visible. Drone status panels go offline correctly when drone fails. Dashboard is feature-complete and entering polish mode.

**Day 14-18 output:** Dashboard locked. Demo video captured and edited. Writeup drafted and refined.

**Interfaces with:**
- Person 3: receives state updates via `ws://localhost:9090` and sends operator commands; receives EGS technical context for the writeup
- Person 1 (via Person 5): receives the ground-truth manifest for dashboard data

**This role merges what was previously Person 4 (Frontend) and Person 5 (ML/Demo/Comms), minus the ML workstream which moved to Person 2.** The merge works because the timing splits cleanly: Days 1-13 are frontend-heavy buildout, Days 14-20 are demo-and-comms heavy. The dashboard is largely feature-complete by Gate 4, freeing the same person to capture, edit, and write. Person 4 must be a strong web engineer with solid technical writing skills and basic video editing comfort. **Person 5 is dedicated to Person 1, so Person 4 has no shared support resource** — if frontend slips past Day 7, the team must descope rather than reassign help.

## Person 5: Simulation Co-Pilot (paired exclusively with Person 1)

**Person 5 works exclusively with Person 1.** They are not a floater across the team. Every day, Person 5 sits inside the simulation workstream and parallelizes whatever Person 1 is doing. This pairing exists because Person 1's seat owns the most cross-component plumbing, and the sim/infra workstream has the most parallelism-friendly tasks (frame curation, scenario YAML authoring, launch-script plumbing, integration testing).

**Owns end-to-end (always in collaboration with Person 1):**
- **Disaster scene frame library** — curating xBD post-disaster crops and public-domain aerial imagery for `sim/fixtures/frames/`; iterating on visual quality and ensuring frame diversity
- **Ground-truth manifest JSON** (`sim/scenarios/<name>_groundtruth.json`) — what's where, what damage class, what victims exist
- **Scenario YAML authoring** (`sim/scenarios/*.yaml`) — waypoint tracks, frame mappings, scripted events
- **Mesh dropout simulator support** — helping Person 1 wire `agents/mesh_simulator/main.py`
- **Resilience scenario scripting** for the demo (drone failures, comm dropouts) — encoded as scripted events in the scenario YAML, owned within the Person 1 / Person 5 workstream
- **Integration testing prep** — building the test harnesses and check scripts that Person 1 uses to verify everyone's code works together
- **Reproduction documentation for the simulation stack** — they are the natural "tester who didn't write it"

**Day 1-2 output:** Initial frame library curated from xBD dataset. xBD download handled (on Person 1's machine — no further xBD data-prep work; Person 2 owns that). Scenario YAML skeleton drafted.
**Day 7 output:** Scenario v1 complete with frame mappings for all waypoints. Ground-truth manifest drafted.
**Day 10 output:** Scenario v2 complete (victims, fires, debris frames). Multi-drone scenario YAML working with Person 1.
**Day 13 output:** Resilience scenarios scripted as deterministic events in YAML. Mesh dropout running.
**Day 14-18 output:** Stable demo runs. Reproduction docs validated by running them cold.

**Interfaces with:**
- **Person 1:** every day, all day. This is a true pairing.
- Other teammates: only via Person 1. Person 5 does not directly support Person 2, Person 3, or Person 4. If those roles need help, the answer is descope, not reassignment.

**Why exclusive pairing:** Person 1's stack owns the most cross-component plumbing and has the most parallelizable work (frame curation, YAML authoring, launch scripting, testing). Splitting Person 5 across multiple roles dilutes that effort and leaves Person 1 still solo on the riskiest seat. By dedicating Person 5 to Person 1, we effectively make the simulation workstream a two-person team. The cost: Person 2, Person 3, and Person 4 have no shared support resource, which means descope-not-reassignment is the team's mitigation strategy if those roles slip.

**Skill profile:** Python 3.11+, comfortable with YAML config and scripted automation, ability to read and tweak Python glue code. Does NOT need ML, frontend, LangGraph, or ROS 2 / Gazebo experience.

## Communication Cadence

### Daily Standup (15 minutes, fixed time)

Suggested: 9:00 AM Central Time (works for DFW-based team).

Format per person:
- What I shipped yesterday
- What I'm shipping today
- What's blocking me / what I need from someone

Standup ends with Person 1 (Simulation Lead) reporting gate trajectory ("We're on track for Gate N at Day X") and Person 4 (The Elevator Watcher, Ibrahim) confirming or calling for descope. Person 1 also confirms Redis + sim processes are stable before declaring the day green.

### Twice-Weekly Integration Sessions (90 minutes)

Tuesdays and Fridays. The whole team works in the same room (or video call) on whatever's most fragile that day.

Typical agenda:
- Demo a known-broken integration
- Fix it together
- Identify the next-most-fragile piece

### Weekly Friday Dress Rehearsal (60 minutes)

Run the full demo scenario end-to-end. No exceptions. Even in Week 1 when only the single-drone loop works, we rehearse demoing what we have.

This catches integration issues early and builds the team's demo muscle memory.

## Repository / Branch Discipline

**Main branch is always demoable.** If you push to main, you ran the demo locally first.

**Per-person feature branches:**
- `sim/<feature>` (Person 1 and Person 5 — they share the namespace since they pair on this stack)
- `agent/<feature>`, `ml/<feature>` (Person 2)
- `egs/<feature>` (Person 3)
- `frontend/<feature>`, `comms/<feature>` (Person 4)
- `scene/<feature>`, `mesh/<feature>` (Person 5 specifically, when isolating their work)

**Daily merge to main** after standup, after local testing.

**Pull requests** for anything touching shared interfaces (function-calling schemas, message schemas). Reviewed by at least one other person.

## Decision-Making Authority

| Decision | Authority |
|---|---|
| Code style, internal API of own component | Component owner |
| Changes to shared schemas | Team consensus, requires PR review |
| Scope cuts | Team vote at gate evaluations |
| Demo storyline | Person 4 proposes, team approves |
| Scope cuts (final call after team vote) | Person 4 (The Elevator Watcher, Ibrahim) |
| Submission timing | Person 4 (The Elevator Watcher, Ibrahim) calls it (Day 18 by default), with Person 1 confirming sim-stack readiness |

## What If Someone Falls Behind

The plan accommodates one person being a day or two behind without breaking anything. If someone is more than 3 days behind:

1. Acknowledge in standup, no shame
2. Reassign or descope that person's deliverables
3. Reallocate work from that person's stretch goals to whoever has bandwidth

If someone is sick or unavailable for >3 days, we re-plan at the next gate. The redundancy in the plan is intentional.

## Skill Coverage Check

Before Day 1, verify the team has:

- [ ] At least one person comfortable with Python scripting + Redis + scripted automation (Person 1) — any modern OS with Python 3.11+, `redis-server`, and Ollama
- [ ] A second person comfortable with Python scripting and YAML config, willing to pair daily on simulation work (Person 5 — does not need ML, frontend, LangGraph, or ROS 2 / Gazebo experience)
- [ ] At least one person comfortable with Python async + LangGraph **AND** PyTorch / Hugging Face / Unsloth (Person 2 — both skill sets required in the same seat). **Comfortable provisioning a cloud GPU instance** (Lambda Labs / Paperspace / Runpod) if no local NVIDIA GPU is available.
- [ ] At least one person comfortable with Python async + LangGraph (Person 3) — any OS with Ollama
- [ ] At least one strong web engineer (Flutter / web frontend) **who can also handle technical writing and basic video editing** (Person 4 — frontend + comms merged) — any OS

**Hardware floor for the team:** every team member needs **Python 3.11+, `redis-server`, and Ollama** on a modern laptop. The simulation stack is cross-platform (macOS, Linux, Windows). No WSL2 or native Linux requirement.

If any are missing, redistribute work or recruit. Don't start Day 1 with a critical skill gap.

## Cross-References

- The day-by-day plan that schedules these roles: [`19-day-by-day-plan.md`](19-day-by-day-plan.md)
- The integration contracts the team builds against: [`20-integration-contracts.md`](20-integration-contracts.md)
- The gates the team evaluates against: [`17-feasibility-and-gates.md`](17-feasibility-and-gates.md)
