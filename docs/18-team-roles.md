# 18 — Team Roles

## Why This Doc Exists

Five people working in parallel only succeeds if each owns a vertical slice with clear interfaces to the others. This doc defines roles, ownership boundaries, and integration responsibilities so nobody is blocked waiting for someone else.

## The Five Roles

| Person | Role | Primary Owns | Secondary Owns |
|---|---|---|---|
| Person 1 | Lead / Simulation | Gazebo, PX4, ROS 2, multi-drone, integration glue | Project management, gate decisions |
| Person 2 | Per-Drone Agent + ML | Drone LangGraph agent, function calling, validation loop, **xBD fine-tuning, vision prompts, adapter integration** | Prompt iteration across the full drone-side stack |
| Person 3 | EGS / Coordination | EGS LangGraph, swarm allocation, multilingual command path | Scripting resilience scenarios |
| Person 4 | Frontend + Demo + Comms | Flutter dashboard, ROS 2 bridge, demo capture, **video editing, technical writeup, README** | Map view, multilingual UI, demo storyline |
| Person 5 | Simulation Co-Pilot (paired with Person 1) | Disaster scene visuals, ground-truth manifest, multi-drone spawn assist, ROS 2 launch plumbing — every sim/infra task that can be parallelized | All integration-testing prep work for Person 1 |

## Person 1: Lead / Simulation

**Owns end-to-end:**
- Gazebo Harmonic + PX4 SITL + ROS 2 Humble installation and stability
- The disaster scene world file (works with Person 5 on visual content placement)
- Multi-drone spawning and namespacing
- ROS 2 ↔ Gazebo bridge configuration
- The launch scripts (`run_full_demo.sh`, `stop_demo.sh`)
- Integration testing (does everyone's code work together?)

**Day 1-2 output:** A single drone flying with camera accessible from Python.

**Day 7 output:** Two drones spawning together (or three if confidence is high).

**Day 13 output:** Three drones flying stably, mesh dropout simulated, resilience scenarios scripted.

**Interfaces with:**
- Person 2: provides `/drone<id>/camera` topic and accepts flight commands on `/drone<id>/cmd`; provides Gazebo screenshots for vision prompt iteration (via Person 5)
- Person 3: provides `/drones/<id>/state` for telemetry
- Person 4: provides ROS 2 bridge endpoint for Flutter
- **Person 5 (dedicated co-pilot):** works alongside Person 1 every day on the entire sim stack — disaster scene, multi-drone spawning, launch files, integration testing. Person 5 is paired exclusively with Person 1.

**This is the highest-risk single role, which is why Person 5 is dedicated to it.** If Person 1's stack isn't working by Day 2, the whole project is in trouble. Person 1 should be the team's strongest infrastructure person. Pairing Person 5 with Person 1 effectively turns the highest-risk seat into a two-person team, doubling parallelism on the workstream most likely to break.

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
- Person 1: subscribes to camera and state, publishes flight commands; receives Gazebo screenshots for vision prompt iteration (Person 5 captures these)
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
- Person 1: receives drone state via ROS 2
- Person 2: sends task assignments to drone agents
- Person 4: pushes shared state to Flutter via WebSocket; receives operator commands; provides EGS context for the writeup

Person 3 owns resilience scenario scripting alone — Person 5 is dedicated to Person 1 and not available for cross-team support.

**This role is the second most agentic-AI heavy.** Person 3 owns the wow moment: the validation loop catching a hallucination on stage. They must engineer the demo scenario where this reliably happens.

## Person 4: Frontend + Demo + Comms

**Owns end-to-end:**
- Flutter web dashboard (4-panel layout: Map, Drone Status, Findings, Command)
- rosbridge_suite integration via WebSocket
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
- Person 3: receives state updates and sends operator commands; receives EGS technical context for the writeup
- Person 1 (via Person 5): receives the ground-truth manifest for dashboard data

**This role merges what was previously Person 4 (Frontend) and Person 5 (ML/Demo/Comms), minus the ML workstream which moved to Person 2.** The merge works because the timing splits cleanly: Days 1-13 are frontend-heavy buildout, Days 14-20 are demo-and-comms heavy. The dashboard is largely feature-complete by Gate 4, freeing the same person to capture, edit, and write. Person 4 must be a strong web engineer with solid technical writing skills and basic video editing comfort. **Person 5 is dedicated to Person 1, so Person 4 has no shared support resource** — if frontend slips past Day 7, the team must descope rather than reassign help.

## Person 5: Simulation Co-Pilot (paired exclusively with Person 1)

**Person 5 works exclusively with Person 1.** They are not a floater across the team. Every day, Person 5 sits inside the simulation workstream and parallelizes whatever Person 1 is doing. This pairing exists because Person 1's seat is the highest-risk single point of failure in the project, and the sim/infra workstream has the most parallelism-friendly tasks (asset placement, launch-file plumbing, integration testing, scene buildout).

**Owns end-to-end (always in collaboration with Person 1):**
- **Disaster scene visual content** — sourcing models from Gazebo Fuel, placing buildings/victims/fires/debris, iterating on visual quality
- **Ground-truth manifest JSON** for the disaster scene (what's where, what damage class, what victims exist)
- **Multi-drone spawn plumbing** — namespacing, launch files, model parameters
- **ROS 2 ↔ Gazebo bridge configuration support**
- **Mesh dropout simulator** in collaboration with Person 1
- **Resilience scenario scripting** for the demo (drone failures, comm dropouts) — these are sim-side events, owned within the Person 1 / Person 5 workstream
- **Integration testing prep** — building the test harnesses and check scripts that Person 1 uses to verify everyone's code works together
- **Reproduction documentation for the simulation stack** — they are the natural "tester who didn't write it"

**Day 1-3 output:** Disaster scene asset list locked. xBD download handled (since the file lives on Person 1's machine — but no further xBD work; Person 2 owns data prep).
**Day 7 output:** Disaster scene v1 complete with 16 buildings, basic terrain. Ground-truth manifest drafted.
**Day 10 output:** Disaster scene v2 complete (victims, fires, debris). Multi-drone spawn working with Person 1.
**Day 13 output:** Resilience scenarios scripted as deterministic events. Mesh dropout running.
**Day 14-18 output:** Stable demo runs. Reproduction docs validated by running them cold.

**Interfaces with:**
- **Person 1:** every day, all day. This is a true pairing.
- Other teammates: only via Person 1. Person 5 does not directly support Person 2, Person 3, or Person 4. If those roles need help, the answer is descope, not reassignment.

**Why exclusive pairing:** Person 1's stack is the project's biggest risk and has the most parallelizable work (placement, plumbing, testing). Splitting Person 5 across multiple roles dilutes that effort and leaves Person 1 still solo on the riskiest seat. By dedicating Person 5 to Person 1, we effectively make the simulation workstream a two-person team. The cost: Person 2, Person 3, and Person 4 have no shared support resource, which means descope-not-reassignment is the team's mitigation strategy if those roles slip.

**Skill profile:** Familiarity with Linux, basic ROS 2 / Gazebo concepts (or willingness to learn fast), comfortable with launch files and YAML config, ability to read and tweak Python/C++ glue code. Does NOT need ML, frontend, or LangGraph experience.

## Communication Cadence

### Daily Standup (15 minutes, fixed time)

Suggested: 9:00 AM Central Time (works for DFW-based team).

Format per person:
- What I shipped yesterday
- What I'm shipping today
- What's blocking me / what I need from someone

Standup ends with the leader (Person 1) confirming gate trajectory: "We're on track for Gate N at Day X."

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
- `simulation/<feature>` (Person 1 and Person 5 — they share the namespace since they pair on this stack)
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
| Submission timing | Person 1 calls it (Day 18 by default) |

## What If Someone Falls Behind

The plan accommodates one person being a day or two behind without breaking anything. If someone is more than 3 days behind:

1. Acknowledge in standup, no shame
2. Reassign or descope that person's deliverables
3. Reallocate work from that person's stretch goals to whoever has bandwidth

If someone is sick or unavailable for >3 days, we re-plan at the next gate. The redundancy in the plan is intentional.

## Skill Coverage Check

Before Day 1, verify the team has:

- [ ] At least one person comfortable with Linux + ROS 2 + simulation (Person 1)
- [ ] A second person comfortable with Linux + basic ROS 2 / Gazebo, willing to pair daily on simulation work (Person 5 — does not need ML, frontend, or LangGraph experience)
- [ ] At least one person comfortable with Python async + LangGraph **AND** PyTorch / Hugging Face / Unsloth (Person 2 — both skill sets now required in the same seat)
- [ ] At least one person comfortable with Python async + LangGraph (Person 3)
- [ ] At least one strong web engineer (Flutter / web frontend) **who can also handle technical writing and basic video editing** (Person 4 — frontend + comms merged)

If any are missing, redistribute work or recruit. Don't start Day 1 with a critical skill gap.

## Cross-References

- The day-by-day plan that schedules these roles: [`19-day-by-day-plan.md`](19-day-by-day-plan.md)
- The integration contracts the team builds against: [`20-integration-contracts.md`](20-integration-contracts.md)
- The gates the team evaluates against: [`17-feasibility-and-gates.md`](17-feasibility-and-gates.md)
