# 17 — Feasibility and Gates

## Why This Doc Exists

Hackathons fail because teams keep building when they should be cutting. This doc defines explicit go/no-go gates with measurable criteria. **At each gate, the entire team meets, evaluates, and either continues or drops scope.** No exceptions. No "we'll catch up next week" optimism.

## The Five Gates

| Gate | Date | What's evaluated | If pass | If fail |
|---|---|---|---|---|
| Gate 1: Stack | Day 2 (Apr 30) | Single drone flying + Gemma 4 inference | Continue | Switch sim platform OR drop project |
| Gate 2: Single-loop | Day 7 (May 5) | One drone full agentic loop end-to-end | Continue to multi-drone | Stay on single-drone, drop swarm scope |
| Gate 3: Fine-tuning | Day 10 (May 8) | LoRA adapter beats base by ≥10pp | Integrate adapter | Drop adapter, base model only |
| Gate 4: Multi-drone | Day 13 (May 11) | 2-3 drones coordinating cleanly | Continue with 3 | Drop to 2 drones |
| Gate 5: Submission | Day 18 (May 16) | All artifacts ready | Submit early | Final 48-hour push |

## Gate 1: Stack Verification (Day 2, April 30)

**Pass criteria — ALL of these must work:**

- [ ] Ubuntu 22.04 native install on dev machine
- [ ] ROS 2 Humble installed, `ros2 topic list` runs
- [ ] PX4 Autopilot built successfully
- [ ] Gazebo Harmonic launches with `make px4_sitl gz_x500_mono_cam`
- [ ] QGroundControl connects, drone takes off
- [ ] Camera frame accessible from Python via ROS 2
- [ ] Ollama installed, Gemma 4 E2B pulled and runs
- [ ] End-to-end test: take a frame, send to Gemma 4, get structured response

**If any fail:**

| Failure | Pivot |
|---|---|
| Gazebo Harmonic broken | Switch to Gazebo Classic 11 (stable, more tutorials) |
| PX4 unstable | Switch to AirSim (deprecated but works) |
| Multi-drone setup unclear | Already plan for 2 drones; defer 3rd to Gate 4 |
| Ollama / Gemma 4 incompatible | Use llama.cpp directly with quantized weights |
| Cannot install on dev machine | Use a cloud GPU instance (Vast.ai, Lambda) |

**If all five pivots fail by end of Day 3:** the project as designed is not feasible. Pivot to a simpler use case (single drone, no swarm, indoor environment).

## Gate 2: Single-Drone Agentic Loop (Day 7, May 5)

**Pass criteria — the full loop must work end-to-end:**

- [ ] Drone flies a survey path autonomously in Gazebo
- [ ] Camera frames are sampled at 1 Hz
- [ ] Frames + state pass to Gemma 4 E2B
- [ ] Gemma 4 returns valid function call from the schema
- [ ] Validation node catches at least one engineered failure case
- [ ] Action node publishes the function call result via ROS 2
- [ ] EGS receives the publish and updates shared state
- [ ] Flutter dashboard shows the finding live

**Plus measurable thresholds:**

- Validation pass rate on first attempt: ≥60%
- Inference latency per cycle: ≤5 seconds
- No crashes in a 5-minute continuous run

**If pass:** continue to multi-drone work in Week 3.

**If fail (any criterion missing):**

1. Drop multi-drone entirely. Demo with one drone.
2. Reframe pitch: "single-drone agentic disaster response with extensible swarm architecture documented."
3. Allocate the freed Person 1 + Person 3 capacity to polishing the single-drone demo and the operator UI.
4. The architecture argument is unchanged — we still implement Nguyen et al. with offline Gemma 4. Just at smaller scale.

This is still a winning submission. The previous Gemma 3n hackathon's first place was a single-device project. Scope discipline beats ambition.

## Gate 3: Fine-Tuning Go/No-Go (Day 10, May 8)

**Pass criteria — LoRA adapter must:**

- [ ] Train successfully on at least 50K xBD patches
- [ ] Beat base Gemma 4 on validation accuracy by ≥10 percentage points
- [ ] Run at inference time without slowing the agent loop below 1 Hz
- [ ] Generalize to at least one disaster type held out of training

**If pass:**

1. Person 2 integrates adapter into the drone agent code (fine-tuning and the agent live in the same seat)
2. Adapter loads at startup of the Ollama instance
3. Writeup updates to claim Unsloth special prize
4. Evaluation section includes adapter-vs-base comparison numbers

**If fail:**

1. Adapter is **completely dropped** from the demo
2. Base Gemma 4 with prompt engineering is used everywhere
3. Writeup includes honest "we attempted fine-tuning, here's what happened" section
4. Person 5 stays with Person 1 on simulation — no reassignment. If FT fails, Person 2 absorbs the fallback path (base Gemma 4 + heavy prompts) themselves, and Person 4 ships the demo/writeup solo.

**No half-measures.** A partially-working adapter that sometimes helps and sometimes hurts is worse than no adapter. We ship what works or skip cleanly.

See [`12-fine-tuning-plan.md`](12-fine-tuning-plan.md) for the detailed plan.

## Gate 4: Multi-Drone Coordination (Day 13, May 11)

**Pass criteria — 3-drone simulation must:**

- [ ] All three drones fly stably for 5+ minutes without crashes
- [ ] Each drone's agent loop runs at ≥0.5 Hz throughput
- [ ] Mesh broadcasts deliver between drones in range, drop out of range
- [ ] EGS replanning successfully reassigns survey points after triggered drone failure
- [ ] At least one resilience scenario completes successfully (drone failure OR EGS dropout)

**Plus performance:**

- Memory usage stays below available VRAM
- No drone exhibits erratic flight behavior
- Validation events visible on dashboard

**If pass:** continue with 3 drones, polish the resilience scenarios for the demo.

**If fail:**

1. Drop to 2-drone configuration immediately
2. The demo scenarios still work: drone 1 surveys west, drone 2 surveys east, drone 1 fails, drone 2 takes over
3. Update writeup framing: "core architecture validated; scaling to N drones is straightforward future work"
4. Reallocate freed time to polishing the 2-drone demo to perfection

A polished 2-drone demo absolutely beats a flaky 3-drone demo. There's no shame in this.

## Gate 5: Submission Readiness (Day 18, May 16)

**Pass criteria — ALL deliverables ready:**

- [ ] GitHub repo public, README complete, all code committed
- [ ] Reproduction instructions tested by someone who didn't write them
- [ ] 90-second demo video edited and reviewed
- [ ] Technical writeup completed (~2000-3000 words)
- [ ] Kaggle submission form filled out
- [ ] Backup of everything on at least 2 separate machines

**If pass:** submit on Day 18 (two days early). Don't wait. Submit, then polish if time allows.

**If fail:** 48-hour final push. Lock the team into the project for the remaining time. No new features. Only fixing what's broken in the deliverables.

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
- **At least one working drone in real Gazebo simulation.**
- **A submission by May 18, 23:59 UTC.**

Everything else is negotiable.

## Cross-References

- The mock list (what's already cut): [`16-mocks-and-cuts.md`](16-mocks-and-cuts.md)
- The day-by-day plan that hits these gates: [`19-day-by-day-plan.md`](19-day-by-day-plan.md)
- Team roles per gate: [`18-team-roles.md`](18-team-roles.md)
- What we submit at Gate 5: [`23-submission-checklist.md`](23-submission-checklist.md)
