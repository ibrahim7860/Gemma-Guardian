# 18 — Team Roles

## Why This Doc Exists

Five people working in parallel only succeeds if each owns a vertical slice with clear interfaces to the others. This doc defines roles, ownership boundaries, and integration responsibilities so nobody is blocked waiting for someone else.

## The Five Roles

| Person | Role | Primary Owns | Secondary Owns |
|---|---|---|---|
| Person 1 | Lead / Simulation | Gazebo, PX4, ROS 2, multi-drone, integration glue | Project management, gate decisions |
| Person 2 | Per-Drone Agent | Drone LangGraph agent, function calling, validation loop | Prompt iteration on drone behavior |
| Person 3 | EGS / Coordination | EGS LangGraph, swarm allocation, multilingual command path | Scripting resilience scenarios |
| Person 4 | Frontend / Operator UX | Flutter dashboard, ROS 2 bridge, demo capture | Map view, multilingual UI |
| Person 5 | ML / Demo / Comms | xBD fine-tuning, vision prompts, video editing, writeup | Disaster scene design, ground-truth manifest |

## Person 1: Lead / Simulation

**Owns end-to-end:**
- Gazebo Harmonic + PX4 SITL + ROS 2 Humble installation and stability
- The disaster scene world file (works with Person 5 on visual content)
- Multi-drone spawning and namespacing
- ROS 2 ↔ Gazebo bridge configuration
- The launch scripts (`run_full_demo.sh`, `stop_demo.sh`)
- Integration testing (does everyone's code work together?)

**Day 1-2 output:** A single drone flying with camera accessible from Python.

**Day 7 output:** Two drones spawning together (or three if confidence is high).

**Day 13 output:** Three drones flying stably, mesh dropout simulated, resilience scenarios scripted.

**Interfaces with:**
- Person 2: provides `/drone<id>/camera` topic and accepts flight commands on `/drone<id>/cmd`
- Person 3: provides `/drones/<id>/state` for telemetry
- Person 4: provides ROS 2 bridge endpoint for Flutter
- Person 5: provides Gazebo screenshots for vision prompt iteration

**This is the highest-risk single role.** If Person 1's stack isn't working by Day 2, the whole project is in trouble. Person 1 should be the team's strongest infrastructure person.

## Person 2: Per-Drone Agent

**Owns end-to-end:**
- LangGraph agent for individual drones (5 nodes: Perception, Reasoning, Validation, Action, Memory)
- Function calling integration with Gemma 4 E2B
- Validation-and-retry loop implementation (Algorithm 1 pattern)
- Inference scheduling across multiple drones (single Ollama instance, queue)
- Drone agent system prompts and corrective re-prompts

**Day 1-2 output:** Standalone Python script: image + state → Gemma 4 → function call.

**Day 7 output:** Full single-drone agentic loop running end-to-end with Person 1's drone.

**Day 13 output:** All drones running their agent loops in parallel. Cross-drone awareness via peer broadcasts integrated into reasoning prompt.

**Interfaces with:**
- Person 1: subscribes to camera and state, publishes flight commands
- Person 3: publishes findings and state for EGS to aggregate
- Person 5: integrates fine-tuned vision adapter (if Day 10 gate passes)

**This role is the most agentic-AI heavy.** Person 2 needs strong familiarity with LangGraph, prompt engineering, and Python async.

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
- Person 4: pushes shared state to Flutter via WebSocket; receives operator commands
- Person 5: documents EGS in writeup

**This role is the second most agentic-AI heavy.** Person 3 owns the wow moment: the validation loop catching a hallucination on stage. They must engineer the demo scenario where this reliably happens.

## Person 4: Frontend / Operator UX

**Owns end-to-end:**
- Flutter web dashboard (4-panel layout: Map, Drone Status, Findings, Command)
- rosbridge_suite integration via WebSocket
- Real-time map rendering with drone positions, survey points, findings
- Multilingual command box with live structured-translation preview
- Findings approval flow (HITL)
- Demo recording and editing assistance

**Day 1-2 output:** Static Flutter app with mock data showing the layout.

**Day 7 output:** Live WebSocket connection, real EGS state rendered.

**Day 13 output:** Multilingual command path works end-to-end. Validation events visible. Drone status panels go offline correctly when drone fails.

**Interfaces with:**
- Person 3: receives state updates and sends operator commands
- Person 5: provides recording/editing collaboration

**This role is critical for the demo.** The dashboard is what the judge actually watches; Gazebo footage is supporting context. Person 4 must be a strong UI engineer.

## Person 5: ML / Demo / Comms

**Owns end-to-end:**
- xBD dataset preprocessing and LoRA fine-tuning with Unsloth (Day 1-10)
- Vision prompt engineering for the drone agent (Day 1-7)
- Disaster scene visual content (works with Person 1 on world file)
- Ground-truth manifest JSON
- 90-second demo video (capture, edit, narrate)
- Technical writeup (~2000-3000 words)
- GitHub repo README and reproduction docs

**Day 1-2 output:** Verify Unsloth supports Gemma 4 vision LoRA. xBD download started. Vision prompts validated on Gazebo screenshots.

**Day 10 output:** Fine-tuning gate decision (GO or NO-GO).

**Day 16-18 output:** Demo video edited. Writeup completed.

**Interfaces with:**
- Person 1: works on Gazebo scene visual content
- Person 2: integrates fine-tuned adapter (if applicable) and provides vision prompts
- Person 4: collaborates on video capture from dashboard

**This role is the most parallel-isolated.** Person 5 can work largely independently from Day 1-10 on fine-tuning, then pivot to Week 4 deliverables.

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
- `simulation/<feature>` (Person 1)
- `agent/<feature>` (Person 2)
- `egs/<feature>` (Person 3)
- `frontend/<feature>` (Person 4)
- `ml/<feature>` (Person 5)

**Daily merge to main** after standup, after local testing.

**Pull requests** for anything touching shared interfaces (function-calling schemas, message schemas). Reviewed by at least one other person.

## Decision-Making Authority

| Decision | Authority |
|---|---|
| Code style, internal API of own component | Component owner |
| Changes to shared schemas | Team consensus, requires PR review |
| Scope cuts | Team vote at gate evaluations |
| Demo storyline | Person 5 proposes, team approves |
| Submission timing | Person 1 calls it (Day 18 by default) |

## What If Someone Falls Behind

The plan accommodates one person being a day or two behind without breaking anything. If someone is more than 3 days behind:

1. Acknowledge in standup, no shame
2. Reassign or descope that person's deliverables
3. Reallocate work from that person's stretch goals to whoever has bandwidth

If someone is sick or unavailable for >3 days, we re-plan at the next gate. The redundancy in the plan is intentional.

## Skill Coverage Check

Before Day 1, verify the team has:

- [ ] At least one person comfortable with Linux + ROS 2 + simulation
- [ ] At least one person comfortable with Python async + LangGraph
- [ ] At least one person comfortable with Flutter / web frontend
- [ ] At least one person comfortable with PyTorch / Hugging Face
- [ ] At least one strong technical writer / video editor

If any are missing, redistribute work or recruit. Don't start Day 1 with a critical skill gap.

## Cross-References

- The day-by-day plan that schedules these roles: [`19-day-by-day-plan.md`](19-day-by-day-plan.md)
- The integration contracts the team builds against: [`20-integration-contracts.md`](20-integration-contracts.md)
- The gates the team evaluates against: [`17-feasibility-and-gates.md`](17-feasibility-and-gates.md)
