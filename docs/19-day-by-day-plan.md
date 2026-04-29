# 19 — Day-by-Day Plan

## Why This Doc Exists

20 days from start to submission. Each day has assigned work for each person. Daily standup checks against this plan; deviations trigger replanning.

**Start date:** Tuesday, April 29, 2026
**Submission deadline:** Sunday, May 18, 2026, 23:59 UTC

## Week 1 (Days 1-7): Foundations and Single-Drone Loop

### Day 1 — Tuesday April 29: Setup Day

**All hands:** Lock the integration contracts. Read [`20-integration-contracts.md`](20-integration-contracts.md). Lock the function-calling schemas. Do not change them after today except for true bugs.

**Person 1:** Install Ubuntu 22.04 (if not already), ROS 2 Humble, PX4 Autopilot. Start the build.
**Person 2:** Install Ollama, pull Gemma 4 E2B, build standalone Python script that takes image + state → function call. Use stock images.
**Person 3:** Install second Ollama instance for E4B. Build assignment-and-validation loop with mock drone states.
**Person 4:** Set up Flutter project + rosbridge_suite. Static dashboard layout with mock data.
**Person 5:** Verify Unsloth supports Gemma 4 vision LoRA. Start xBD dataset download (~50GB). Vision prompts in notebook with stock images.

**End of day check:** Everyone has their dev environment working. Day 1 is mostly setup, not output.

### Day 2 — Wednesday April 30: GATE 1

**Person 1:** Single drone flying in Gazebo, camera frame accessible from Python.
**Person 2:** Standalone agent script returns valid function call from Gemma 4 on a stock image.
**Person 3:** EGS process generates valid survey-point assignment via Gemma 4 E4B with mock drones.
**Person 4:** Flutter dashboard renders mock state correctly.
**Person 5:** **Day-2 verification: Unsloth supports Gemma 4 vision LoRA.** If yes, continue with fine-tuning plan. If no, ABANDON fine-tuning and pivot full-time to demo polish + writeup. Vision prompt validation continues.

**Gate 1 evaluation at end of day:** All criteria met? See [`17-feasibility-and-gates.md`](17-feasibility-and-gates.md). Continue if yes, pivot if no.

### Day 3 — Thursday May 1

**Person 1:** Disaster scene world file v1: 16 buildings, basic terrain.
**Person 2:** Wire up real Gazebo camera topic to drone agent (replaces stock images).
**Person 3:** Connect EGS to mock telemetry stream (still no real drones yet).
**Person 4:** WebSocket connection live; rendering mock state from Person 3.
**Person 5:** Pre-process xBD into per-building patches with damage labels. Train/val/test splits by disaster.

### Day 4 — Friday May 2: First Integration Session

**Integration session (afternoon):** Person 1 + Person 2 wire up the camera topic into the drone agent. End of day: drone flies a fixed waypoint path while sampling camera at 1 Hz and emitting structured calls.

**Person 3:** Refine validation loop with corrective prompts from [`10-validation-and-retry-loop.md`](10-validation-and-retry-loop.md).
**Person 4:** Build the findings feed and command box panels.
**Person 5:** Begin LoRA training. First training run: small subset, conservative hyperparameters, validate it works.

**Friday dress rehearsal:** Whatever works, rehearse demoing it. 30-minute exercise.

### Day 5 — Monday May 5

**Person 1:** Disaster scene v2: add victims (AprilTags), fires (plume plugin), debris.
**Person 2:** Implement validation node with corrective re-prompts. Test catching engineered failures.
**Person 3:** Real drone state ingestion. Real assignment dispatched to drone via ROS 2.
**Person 4:** Map view panel showing drone position live.
**Person 5:** Continue LoRA training. Track validation accuracy.

### Day 6 — Tuesday May 6: Second Integration Session

**Integration session (afternoon):** End-to-end on a single drone. Drone flies, sees a victim marker, generates report_finding, validation passes, EGS receives, dashboard shows it. Iterate until it works.

**Person 5:** Vision prompts iterate based on real Gazebo screenshots.

### Day 7 — Wednesday May 7: GATE 2

**All hands:** Run the full single-drone scenario and demonstrate Gate 2 criteria. See [`17-feasibility-and-gates.md`](17-feasibility-and-gates.md).

**Gate 2 evaluation at end of day:**
- PASS: Continue to multi-drone in Week 2.
- FAIL: Drop swarm scope, polish single-drone for the demo.

## Week 2 (Days 8-13): Multi-Drone and EGS Polish

### Day 8 — Thursday May 8

**Person 1:** Spawn 2nd drone. Verify multi-drone Gazebo runs without crashing.
**Person 2:** Drone agent runs in parallel for 2 drones with shared Ollama instance + queue.
**Person 3:** Operator command translation path with English + Spanish.
**Person 4:** Multilingual command box with language selector. Live translation preview.
**Person 5:** Continue LoRA training. Approaching the gate decision.

### Day 9 — Friday May 9: Third Integration Session

**Integration session:** 2 drones running parallel agent loops, both reporting findings to EGS, both visible on dashboard.

**Person 5:** Final LoRA training runs before Gate 3.

**Friday dress rehearsal:** 2-drone scenario.

### Day 10 — Monday May 12: GATE 3

**Person 5 demonstrates fine-tuning results.** See [`12-fine-tuning-plan.md`](12-fine-tuning-plan.md) and [`17-feasibility-and-gates.md`](17-feasibility-and-gates.md).

**Gate 3 evaluation:**
- PASS: Person 2 + Person 5 integrate adapter into drone agent.
- FAIL: Adapter dropped. Person 5 pivots to demo polish + writeup full-time.

**Other people in parallel:**
**Person 1:** Spawn 3rd drone (if Gate 4 trajectory looks good).
**Person 2:** Implement peer broadcast handling in reasoning prompt.
**Person 3:** Replanning trigger logic: drone failure → re-assignment.
**Person 4:** Findings approval flow. Validation event ticker on drone status panels.

### Day 11 — Tuesday May 13

**Person 1:** Mesh simulator with range-based dropout running.
**Person 2:** Cross-drone awareness: drone B reasons about whether to investigate drone A's low-confidence finding.
**Person 3:** Standalone-mode logic: drone continues without EGS heartbeat.
**Person 4:** Polish dashboard visual hierarchy.
**Person 5:** Either: (a) integrate adapter and test on Gazebo imagery, or (b) full-time demo polish.

### Day 12 — Wednesday May 14: Fourth Integration Session

**Integration session:** Full 3-drone scenario (or 2-drone if dropped). Resilience scenario 1: drone failure triggers EGS replanning.

### Day 13 — Thursday May 15: GATE 4

**Gate 4 evaluation:** Multi-drone coordination working? See [`17-feasibility-and-gates.md`](17-feasibility-and-gates.md).

- PASS: Continue with 3 drones for demo.
- FAIL: Drop to 2 drones. Adjust demo storyboard.

## Week 3 (Days 14-18): Polish and Demo Capture

### Day 14 — Friday May 16: Demo Capture Begins

**All hands:** Begin running the full demo scenario repeatedly. Capture the cleanest runs.

**Person 1:** Provide stable demo runs. Fix any simulation jitter.
**Person 2:** Tune reasoning prompts for demo quality. Engineer the hallucination-catch moment.
**Person 3:** Script the resilience scenarios as deterministic events.
**Person 4:** Polish dashboard visual quality. Test all dashboard interactions for video.
**Person 5:** Begin video editing. Storyboard locked. First draft of writeup.

**Friday dress rehearsal:** Full demo run. Identify everything that's still rough.

### Day 15 — Saturday May 17

**Person 1:** Final scene polish.
**Person 2:** Engineer the validation-catch moment to reliably trigger.
**Person 3:** Multilingual command path tested on video-quality scenarios.
**Person 4:** Demo capture support — record dashboard runs cleanly.
**Person 5:** Video editing continues. Writeup draft.

### Day 16 — Sunday May 18: Lock Day

**Today is the day everything stops changing.** Only bug fixes after this point.

**Person 1:** Lock simulation. Document setup.
**Person 2:** Lock prompts. Don't iterate further.
**Person 3:** Lock EGS. Test resilience scenarios one final time.
**Person 4:** Lock dashboard. Final video captures.
**Person 5:** Video edit complete. Writeup near-final.

**No new features. No "small additions."** Whatever's there is what ships.

### Day 17 — Monday May 19: Polish and Reproduce

**Person 1:** Test reproduction instructions. Have someone who didn't write them try the setup.
**Person 2:** Code cleanup for public repo.
**Person 3:** Code cleanup for public repo.
**Person 4:** Code cleanup for public repo.
**Person 5:** Final video tweaks. Writeup proofreading. Submission form preparation.

### Day 18 — Tuesday May 20: GATE 5 — SUBMIT

**Note: original deadline was May 18. The day-by-day above slipped to keep workload realistic. Adjust the plan one of two ways:**

**Option A: Submit early (Day 18 = May 16, two days early).**
- Compress Week 3 to 4 days.
- Hit Day 16 lock day on May 14.
- Submission on May 16.

**Option B: Use full timeline (Day 20 = May 18).**
- Day 14 = May 12 (start polish).
- Day 18 = May 16 (lock day).
- Day 19 = May 17 (reproduce).
- Day 20 = May 18 (SUBMIT).

We use **Option B**. Below is the recalibrated schedule.

## Recalibrated Day Numbers (Anchored to May 18 Deadline)

| Day | Date | What's happening |
|---|---|---|
| 1 | Tue Apr 29 | Setup + contracts |
| 2 | Wed Apr 30 | **GATE 1** (stack working) |
| 3 | Thu May 1 | Wiring components together |
| 4 | Fri May 2 | First integration session + dress rehearsal |
| 5 | Mon May 5 | Drone agent loop building |
| 6 | Tue May 6 | Second integration session |
| 7 | Wed May 7 | **GATE 2** (single-drone loop) |
| 8 | Thu May 8 | Multi-drone work begins |
| 9 | Fri May 9 | Third integration + dress rehearsal |
| 10 | Mon May 12 | **GATE 3** (fine-tuning) |
| 11 | Tue May 13 | Multi-drone coordination |
| 12 | Wed May 14 | Fourth integration session |
| 13 | Thu May 15 | **GATE 4** (multi-drone working) |
| 14 | Fri May 16 | Demo capture + dress rehearsal |
| 15 | Sat May 17 | Polish |
| 16 | Sun May 18 | LOCK DAY (no new features) |
| 17 | Mon May 19 | Reproduce + polish |
| 18 | Tue May 20 | **GATE 5 + SUBMIT** |

Wait — May 20 is past the May 18 deadline. We need to submit on May 18 itself.

**Real schedule, anchored to May 18 23:59 UTC submission:**

| Day | Date | What's happening |
|---|---|---|
| 1 | Tue Apr 29 | Setup + contracts |
| 2 | Wed Apr 30 | **GATE 1** |
| 3 | Thu May 1 | Wiring |
| 4 | Fri May 2 | Integration 1 + dress rehearsal |
| 5 | Mon May 5 | Drone agent building |
| 6 | Tue May 6 | Integration 2 |
| 7 | Wed May 7 | **GATE 2** |
| 8 | Thu May 8 | Multi-drone begins |
| 9 | Fri May 9 | Integration 3 + dress rehearsal |
| 10 | Mon May 12 | **GATE 3** (fine-tuning) |
| 11 | Tue May 13 | Multi-drone coordination |
| 12 | Wed May 14 | Integration 4 |
| 13 | Thu May 15 | **GATE 4** |
| 14 | Fri May 16 | Demo capture + dress rehearsal |
| 15 | Sat May 17 | Final polish + video edit |
| 16 | Sun May 18 | **GATE 5 + SUBMIT** by 23:59 UTC |

That's 16 working days, which is realistic.

## Friday Dress Rehearsal Schedule

| Date | What we rehearse |
|---|---|
| Fri May 2 | Whatever works (probably single-drone loop partially) |
| Fri May 9 | Single-drone loop complete |
| Fri May 16 | Full demo (multi-drone + resilience + multilingual) |

Each rehearsal is timed and recorded. Rough cuts of the rehearsal videos are useful even before the final video shoot.

## Buffer

There is **no built-in buffer** in this plan. The buffers are the gates: each gate is an opportunity to descope.

If we hit Day 16 (May 18) and aren't ready:
- Submit what we have
- Honesty in writeup about limitations
- Better to submit a partial working demo than nothing

## Cross-References

- Roles assigned to each day: [`18-team-roles.md`](18-team-roles.md)
- Gate details: [`17-feasibility-and-gates.md`](17-feasibility-and-gates.md)
- Integration contracts to lock Day 1: [`20-integration-contracts.md`](20-integration-contracts.md)
- Demo storyboard for Week 3: [`21-demo-storyboard.md`](21-demo-storyboard.md)
- Submission deliverables for Day 16: [`23-submission-checklist.md`](23-submission-checklist.md)
