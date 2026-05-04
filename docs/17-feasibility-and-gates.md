# 17 — Feasibility and Gates

## Why This Doc Exists

Hackathons fail because teams keep building when they should be cutting. This doc defines explicit go/no-go gates with measurable criteria. **At each gate, the entire team meets, evaluates, and either continues or drops scope.** No exceptions. No "we'll catch up next week" optimism.

## The Five Gates

Dates below are anchored to the recalibrated 16-working-day schedule in [`19-day-by-day-plan.md`](19-day-by-day-plan.md), which terminates at the May 18, 23:59 UTC submission deadline.

| Gate | Date | What's evaluated | If pass | If fail |
|---|---|---|---|---|
| Gate 1: Stack | Day 2 (Wed Apr 30) | Redis + sim smoke-test + Gemma 4 inference | Continue | Debug setup OR drop project |
| Gate 2: Single-loop | Day 7 (Wed May 7) | One drone full agentic loop end-to-end on Redis | Continue to multi-drone | Stay on single-drone, drop swarm scope |
| Gate 3: Fine-tuning | Day 10 (Mon May 12) | LoRA adapter beats base by ≥10pp | Integrate adapter | Drop adapter, base model only |
| Gate 4: Multi-drone | Day 13 (Thu May 15) | 2-3 drones coordinating cleanly | Continue with 3 | Drop to 2 drones |
| Gate 5: Submission | Day 16 (Sun May 18) | All artifacts ready, submit by 23:59 UTC | Submit | No-buffer push: submit whatever is working |

## Gate 1: Stack Verification (Day 2, Wed Apr 30)

**Pass criteria — ALL of these must work:**

- [ ] `redis-server` running on `localhost:6379`; `redis-cli ping` returns `PONG`
- [ ] `sim/waypoint_runner.py` publishes `drones.drone1.state` messages; a Python subscriber (`redis-py`) prints them
- [ ] `sim/frame_server.py` publishes `drones.drone1.camera` (raw JPEG bytes); a Python subscriber receives them
- [ ] Ollama installed, Gemma 4 E2B pulled and runs (macOS with Metal, Linux with CUDA, or CPU fallback)
- [ ] End-to-end smoke test: frame bytes from Redis → Gemma 4 → structured response printed
- [ ] **Demo box designated** — the single machine where the final video will be recorded

**Risk profile vs. previous stack:** The old Gate 1 required Gazebo + PX4 + ROS 2 installed on a specific OS combination. The new Gate 1 requires Python 3.11+, `redis-server`, and Ollama — all cross-platform and installable in under 30 minutes on any modern laptop. The overall risk of Gate 1 failure is significantly lower.

**If any fail:**

| Failure | Pivot |
|---|---|
| Redis install fails | Use `redis-py`'s bundled `fakeredis` for local smoke-testing; real Redis must work before Day 3 |
| `waypoint_runner.py` or `frame_server.py` not publishing | Debug Python process; check Redis connection string in `shared/config.yaml` |
| Ollama / Gemma 4 incompatible | Use llama.cpp directly with quantized weights |
| Multi-drone setup unclear | Already plan for 2 drones; defer 3rd to Gate 4 |
| No team member has a machine capable of Ollama inference | Rent a dedicated cloud GPU instance (Lambda Labs, Paperspace) and use it as the demo box |

**If all pivots fail by end of Day 3:** the project as designed is not feasible. Pivot to a simpler use case (single drone, no swarm).

## Gate 2: Single-Drone Agentic Loop (Day 7, Wed May 7)

**Pass criteria — the full loop must work end-to-end:**

- [ ] Drone agent process subscribes to `drones.drone1.state` and `drones.drone1.camera` on Redis
- [ ] Camera frames (from `sim/frame_server.py`) are sampled at 1 Hz and passed to Gemma 4 E2B
- [ ] Gemma 4 returns valid function call from the schema
- [ ] Validation node catches at least one engineered failure case
- [ ] Action node publishes the function call result on `drones.drone1.findings` (Redis)
- [ ] EGS agent process receives the finding from Redis and updates shared state on `egs.state`
- [ ] Flutter dashboard shows the finding live via the FastAPI WebSocket bridge

**Plus measurable thresholds:**

- Validation pass rate on first attempt: ≥60%
- Inference latency per cycle: ≤5 seconds
- No crashes in a 5-minute continuous run

**If pass:** continue to multi-drone work in Week 3.

**If fail (any criterion missing):**

1. Drop multi-drone entirely. Demo with one drone.
2. Reframe pitch: "single-drone agentic disaster response with extensible swarm architecture documented."
3. Allocate the freed Hazim + Qasim capacity to polishing the single-drone demo and the operator UI.
4. The architecture argument is unchanged — we still implement Nguyen et al. with offline Gemma 4. Just at smaller scale.

This is still a winning submission. The previous Gemma 3n hackathon's first place was a single-device project. Scope discipline beats ambition.

## Gate 3: Fine-Tuning Go/No-Go (Day 10, Mon May 12)

**Pass criteria — LoRA adapter must:**

- [ ] Train successfully on at least 50K xBD patches
- [ ] Beat base Gemma 4 on validation accuracy by ≥10 percentage points
- [ ] Run at inference time without slowing the agent loop below 1 Hz
- [ ] Generalize to at least one disaster type held out of training

**If pass:**

1. Kaleel integrates adapter into the drone agent code (fine-tuning and the agent live in the same seat)
2. Adapter loads at startup of the Ollama instance
3. Writeup updates to claim Unsloth special prize
4. Evaluation section includes adapter-vs-base comparison numbers

**If fail:**

1. Adapter is **completely dropped** from the demo
2. Base Gemma 4 with prompt engineering is used everywhere
3. Writeup includes honest "we attempted fine-tuning, here's what happened" section
4. Thayyil stays with Hazim on simulation — no reassignment. If FT fails, Kaleel absorbs the fallback path (base Gemma 4 + heavy prompts) themselves, and Ibrahim ships the demo/writeup solo.

**No half-measures.** A partially-working adapter that sometimes helps and sometimes hurts is worse than no adapter. We ship what works or skip cleanly.

See [`12-fine-tuning-plan.md`](12-fine-tuning-plan.md) for the detailed plan.

## Gate 4: Multi-Drone Coordination (Day 13, Thu May 15)

**Pass criteria — 3-drone simulation must:**

- [ ] All three drone agent processes run stably for 5+ simulated minutes without crashes
- [ ] Each drone's agent loop runs at ≥0.5 Hz throughput
- [ ] `agents/mesh_simulator/main.py` delivers broadcasts between drones in range, drops them out of range (per `shared/config.yaml` `mesh.range_meters`)
- [ ] EGS replanning successfully reassigns survey points after scripted drone failure event
- [ ] At least one resilience scenario completes successfully (drone failure OR EGS dropout)

**Plus performance:**

- Memory usage stays below available VRAM
- No drone agent process exits unexpectedly
- Validation events visible on dashboard

**If pass:** continue with 3 drones, polish the resilience scenarios for the demo.

**If fail:**

1. Drop to 2-drone configuration immediately
2. The demo scenarios still work: drone 1 surveys west, drone 2 surveys east, drone 1 fails, drone 2 takes over
3. Update writeup framing: "core architecture validated; scaling to N drones is straightforward future work"
4. Reallocate freed time to polishing the 2-drone demo to perfection

A polished 2-drone demo absolutely beats a flaky 3-drone demo. There's no shame in this.

## Gate 5: Submission Readiness (Day 16, Sun May 18)

**Pass criteria — ALL deliverables ready:**

- [ ] GitHub repo public, README complete, all code committed
- [ ] Reproduction instructions tested by someone who didn't write them (cold-test was Day 15 / Sat May 17)
- [ ] 90-second demo video edited and reviewed
- [ ] Technical writeup completed (~2000-3000 words)
- [ ] Kaggle submission form filled out
- [ ] Backup of everything on at least 2 separate machines

**If pass:** submit on Day 16 (Sun May 18) **before 23:59 UTC**. Aim to upload by 18:00 UTC to leave a 6-hour buffer for upload failures, Kaggle outages, or last-minute corrections. Submit, then polish only if Kaggle allows post-deadline edits.

**If fail:** there is no Day 17. Submit whatever is working by 23:59 UTC with an honest writeup describing what shipped and what didn't. Do not miss the deadline trying to fix one more thing.

## Risk-Adjusted Outcome Tree

The realistic outcome distribution given typical hackathon execution:

```
                      ┌─ Best case (15%): Full 3-drone demo + 
                      │   fine-tuning + multilingual + all resilience
                      │   → Strong contender for top prize + Unsloth
                      │
                      ├─ Good case (40%): 3-drone demo + base model + 
                      │   multilingual + 1 resilience scenario
                      │   → Strong contender for primary track
                      │
   Project trajectory ┤
                      │
                      ├─ Acceptable case (30%): 2-drone demo + base 
                      │   model + multilingual + 1 resilience
                      │   → Solid submission, Honorable Mention possible
                      │
                      ├─ Recovery case (10%): Single-drone agentic 
                      │   demo + base model + EGS + dashboard
                      │   → Complete submission, less competitive
                      │
                      └─ Failure case (5%): No working demo
                          → Submit what we have, write honestly about it
```

The gates exist to migrate us up this tree as quickly as we know we're below the level we want.

## Communication Protocol at Gates

At each gate evaluation:

1. **Person leading the workstream demonstrates** the gate criteria live
2. **Team votes** PASS / FAIL by simple majority
3. **Decision is recorded** in `docs/decisions.md` with date and rationale
4. **No revisiting** until the next gate

Once a scope cut is made, it's made. No post-hoc adding back.

## What We Do NOT Cut Even Under Extreme Pressure

These are the irreducible minimums:

- **Real Gemma 4 inference doing real work.** No mocking the LLM itself.
- **The validation-and-retry loop.** This is the technical innovation. It must be in the demo.
- **The offline / on-device claim demonstrated, not asserted.** Terminal showing no internet at some point.
- **At least one working drone agent loop on Redis with real Gemma 4 driving decisions.**
- **A submission by May 18, 23:59 UTC.**

Everything else is negotiable.

## Cross-References

- The mock list (what's already cut): [`16-mocks-and-cuts.md`](16-mocks-and-cuts.md)
- The day-by-day plan that hits these gates: [`19-day-by-day-plan.md`](19-day-by-day-plan.md)
- Team roles per gate: [`18-team-roles.md`](18-team-roles.md)
- What we submit at Gate 5: [`23-submission-checklist.md`](23-submission-checklist.md)
