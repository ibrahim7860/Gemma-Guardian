# 19 — Day-by-Day Plan

## Why This Doc Exists

20 days from start to submission. Each day has assigned work for each person. Daily standup checks against this plan; deviations trigger replanning.

**Start date:** Tuesday, April 29, 2026
**Submission deadline:** Sunday, May 18, 2026, 23:59 UTC

## Week 1 (Days 1-7): Foundations and Single-Drone Loop

### Day 1 — Tuesday April 29: Setup Day

**All hands:** Lock the integration contracts. Read [`20-integration-contracts.md`](20-integration-contracts.md). Lock the function-calling schemas. Do not change them after today except for true bugs.

**Person 1:** Install Ubuntu 22.04 (if not already), ROS 2 Humble, PX4 Autopilot. Start the build.
**Person 2:** Install Ollama, pull Gemma 4 E2B, build standalone Python script that takes image + state → function call. Use stock images. Start Unsloth verification and kick off xBD download (~50GB) on Person 2's own machine.
**Person 3:** Install second Ollama instance for E4B. Build assignment-and-validation loop with mock drone states.
**Person 4:** Set up Flutter project + rosbridge_suite. Static dashboard layout with mock data.
**Person 5 (paired with Person 1):** Install Ubuntu 22.04 + ROS 2 Humble in parallel with Person 1 (so they have a working sim machine of their own). Browse Gazebo Fuel for disaster scene assets — buildings, victims, fires. Draft ground-truth manifest schema.

**End of day check:** Everyone has their dev environment working. Day 1 is mostly setup, not output.

### Day 2 — Wednesday April 30: GATE 1

**Person 1:** Single drone flying in Gazebo, camera frame accessible from Python.
**Person 2:** Standalone agent script returns valid function call from Gemma 4 on a stock image. **Day-2 verification: Unsloth supports Gemma 4 vision LoRA.** If yes, continue with fine-tuning plan. If no, ABANDON fine-tuning. Vision prompt validation continues against stock images.
**Person 3:** EGS process generates valid survey-point assignment via Gemma 4 E4B with mock drones.
**Person 4:** Flutter dashboard renders mock state correctly.
**Person 5 (paired with Person 1):** Person 5's Ubuntu + ROS 2 + Gazebo install verified working. Disaster scene asset list locked. First test world file loaded with placeholder building.

**Gate 1 evaluation at end of day:** All criteria met? See [`17-feasibility-and-gates.md`](17-feasibility-and-gates.md). Continue if yes, pivot if no.

### Day 3 — Thursday May 1

**Person 1:** Disaster scene world file v1: 16 buildings, basic terrain. Working with Person 5 on the placement.
**Person 2:** Wire up real Gazebo camera topic to drone agent (replaces stock images). Define eval criteria for fine-tuned adapter (what counts as passing). Begin xBD preprocessing on own time.
**Person 3:** Connect EGS to mock telemetry stream (still no real drones yet).
**Person 4:** WebSocket connection live; rendering mock state from Person 3.
**Person 5 (paired with Person 1):** Place buildings in 4×4 grid in the world file. Start working on roads (textured ground polygons). Begin ground-truth manifest JSON for placed buildings.

### Day 4 — Friday May 2: First Integration Session

**Integration session (afternoon):** Person 1 + Person 2 wire up the camera topic into the drone agent. End of day: drone flies a fixed waypoint path while sampling camera at 1 Hz and emitting structured calls.

**Person 3:** Refine validation loop with corrective prompts from [`10-validation-and-retry-loop.md`](10-validation-and-retry-loop.md).
**Person 4:** Build the findings feed and command box panels.
**Person 2:** Begin LoRA training solo. First training run: small subset, conservative hyperparameters, validate it works.
**Person 5 (paired with Person 1):** Disaster scene v1 complete (16 buildings + roads + flat ground). Ground-truth manifest JSON drafted.

**Friday dress rehearsal:** Whatever works, rehearse demoing it. 30-minute exercise.

### Day 5 — Monday May 5

**Person 1:** Disaster scene v2 leadership — add victims (AprilTags), fires (plume plugin), debris. Multi-drone spawn experimentation begins.
**Person 2:** Implement validation node with corrective re-prompts. Test catching engineered failures. Continue LoRA training solo; track validation accuracy.
**Person 3:** Real drone state ingestion. Real assignment dispatched to drone via ROS 2.
**Person 4:** Map view panel showing drone position live.
**Person 5 (paired with Person 1):** Place all victims, fires, and debris in the scene. Update ground-truth manifest. Begin researching multi-drone spawn patterns (PX4 instance ports, ROS 2 namespacing).

### Day 6 — Tuesday May 6: Second Integration Session

**Integration session (afternoon):** End-to-end on a single drone. Drone flies, sees a victim marker, generates report_finding, validation passes, EGS receives, dashboard shows it. Iterate until it works.

**Person 2:** Vision prompts iterate based on real Gazebo screenshots.
**Person 5 (paired with Person 1):** Capture clean drone-eye-view screenshots at multiple altitudes and hand them to Person 2 for prompt iteration. Validate the scene reads cleanly from drone perspective; iterate visuals if Gemma struggles.

### Day 7 — Wednesday May 7: GATE 2

**All hands:** Run the full single-drone scenario and demonstrate Gate 2 criteria. See [`17-feasibility-and-gates.md`](17-feasibility-and-gates.md).

**Gate 2 evaluation at end of day:**
- PASS: Continue to multi-drone in Week 2.
- FAIL: Drop swarm scope, polish single-drone for the demo.

## Week 2 (Days 8-13): Multi-Drone and EGS Polish

### Day 8 — Thursday May 8

**Person 1:** Spawn 2nd drone. Verify multi-drone Gazebo runs without crashing.
**Person 2:** Drone agent runs in parallel for 2 drones with shared Ollama instance + queue. Continue LoRA training solo; approaching the gate decision.
**Person 3:** Operator command translation path with English + Spanish.
**Person 4:** Multilingual command box with language selector. Live translation preview.
**Person 5 (paired with Person 1):** Own the launch-file plumbing for multi-drone spawn — namespacing, instance ports, model parameter overrides. Verify telemetry topics are properly per-drone scoped.

### Day 9 — Friday May 9: Third Integration Session

**Integration session:** 2 drones running parallel agent loops, both reporting findings to EGS, both visible on dashboard.

**Person 2:** Final LoRA training runs before Gate 3 (solo).

**Friday dress rehearsal:** 2-drone scenario.

### Day 10 — Monday May 12: GATE 3

**Person 2 demonstrates fine-tuning results.** See [`12-fine-tuning-plan.md`](12-fine-tuning-plan.md) and [`17-feasibility-and-gates.md`](17-feasibility-and-gates.md).

**Gate 3 evaluation:**
- PASS: Person 2 integrates adapter into drone agent (same seat, no handoff).
- FAIL: Adapter dropped. Person 2 falls back to base Gemma 4 + heavy prompts. **Person 5 stays with Person 1 — no reassignment.**

**Other people in parallel:**
**Person 1:** Spawn 3rd drone (if Gate 4 trajectory looks good).
**Person 2:** Implement peer broadcast handling in reasoning prompt.
**Person 3:** Replanning trigger logic: drone failure → re-assignment.
**Person 4:** Findings approval flow. Validation event ticker on drone status panels.
**Person 5 (paired with Person 1):** 3-drone spawn plumbing. Begin scripting resilience scenarios as Gazebo-side events (drone kill, comm dropout) — these are sim events that Person 1's stack triggers.

### Day 11 — Tuesday May 13

**Person 1:** Mesh simulator with range-based dropout running.
**Person 2:** Cross-drone awareness: drone B reasons about whether to investigate drone A's low-confidence finding. If GO: integrate adapter and test on Gazebo imagery.
**Person 3:** Standalone-mode logic: drone continues without EGS heartbeat.
**Person 4:** Polish dashboard visual hierarchy.
**Person 5 (paired with Person 1):** Build the mesh dropout simulator with Person 1. Wire scripted resilience events (drone failure, comm loss) into the launch system.

### Day 12 — Wednesday May 14: Fourth Integration Session

**Integration session:** Full 3-drone scenario (or 2-drone if dropped). Resilience scenario 1: drone failure triggers EGS replanning.

### Day 13 — Thursday May 15: GATE 4

**Gate 4 evaluation:** Multi-drone coordination working? See [`17-feasibility-and-gates.md`](17-feasibility-and-gates.md).

- PASS: Continue with 3 drones for demo.
- FAIL: Drop to 2 drones. Adjust demo storyboard.

**Post-gate work (afternoon, all hands):**
**Person 1:** Identify and fix any sim instability surfaced during the gate run.
**Person 2:** Note any prompt-quality issues spotted during the gate run; queue for Day 14 tuning.
**Person 3:** Lock the demo's resilience-scenario script (which scenarios run, in what order).
**Person 4:** Lock demo storyboard with the team. **Begin writeup first draft** (architecture and approach sections — these are stable post-Gate 4).
**Person 5 (paired with Person 1):** Help Person 1 diagnose any sim issues from the gate run.

## Week 3 (Days 14-18): Polish and Demo Capture

### Day 14 — Friday May 16: Demo Capture Begins

**All hands:** Begin running the full demo scenario repeatedly. Capture the cleanest runs.

**Person 1:** Provide stable demo runs. Fix any simulation jitter.
**Person 2:** Tune reasoning prompts for demo quality. Engineer the hallucination-catch moment.
**Person 3:** Script the resilience scenarios as deterministic events on the EGS side (sim-side events were prepped by Person 5).
**Person 4:** Polish dashboard visual quality. Test all dashboard interactions for video. **Begin video editing** (using clean runs as they're captured). Writeup draft continues from Day 13 start.
**Person 5 (paired with Person 1):** Run the simulator while Person 1 monitors stability. Reproduce the demo scenario over and over to surface any sim jitter. Help Person 1 with final scene polish.

**Friday dress rehearsal:** Full demo run. Identify everything that's still rough.

### Day 15 — Saturday May 17

**Person 1:** Final scene polish.
**Person 2:** Engineer the validation-catch moment to reliably trigger.
**Person 3:** Multilingual command path tested on video-quality scenarios.
**Person 4:** Demo capture — record dashboard runs cleanly. Video editing continues. Writeup draft.
**Person 5 (paired with Person 1):** Operate the simulator on the demo machine so Person 4 can record the dashboard cleanly. Help Person 1 lock the scene.

### Day 15 — Saturday May 17: Lock + Reproduce

**Today is the day everything stops changing.** Only bug fixes after this point. **No new features. No "small additions."** Whatever's there is what ships.

**Person 1:** Lock simulation. Have an outside-the-team tester run reproduction instructions cold; Person 5 acts as backup tester. Fix anything that breaks the cold run.
**Person 2:** Lock prompts. Don't iterate further. Code cleanup for public repo.
**Person 3:** Lock EGS. Test resilience scenarios one final time. Code cleanup for public repo.
**Person 4:** Lock dashboard. Final video captures. Video edit to picture-lock. Writeup near-final draft circulated for team review.
**Person 5 (paired with Person 1):** Co-write the simulation reproduction docs with Person 1. Run them cold from a fresh Ubuntu image. Document any rough edges.

### Day 16 — Sunday May 18: GATE 5 + SUBMIT (deadline 23:59 UTC)

**Submission day. The plan calls for submitting by ~18:00 UTC, leaving ~6 hours of buffer before the 23:59 UTC deadline.** No new features today, only finalizing deliverables and pressing the button.

**Person 1:** Final reproduction-doc fixes from cold tester feedback. Backup the demo box. On-call for any submission-time sim issue.
**Person 2:** Final repo cleanup. Confirm Ollama / model pull instructions work from scratch. On-call for prompt or model issues.
**Person 3:** Final repo cleanup. Confirm EGS launches from the documented command. On-call for EGS issues.
**Person 4:** Video final export and upload. Writeup proofread and finalized. **Owns the Kaggle submission form.** Confirms all required fields, links, and attachments. Submits by 18:00 UTC. Posts confirmation to the team.
**Person 5 (paired with Person 1):** Final reproduction validation pass. Backup of repo + assets to a second machine. On-call for sim issues.

**Submission gate (per [`17-feasibility-and-gates.md`](17-feasibility-and-gates.md) and [`23-submission-checklist.md`](23-submission-checklist.md)):** GitHub repo public, README complete, video uploaded, writeup complete, Kaggle form submitted, two-machine backup confirmed.

## Schedule (Anchored to May 18 23:59 UTC Deadline)

The plan compresses to 16 working days so submission lands on May 18 with buffer.

| Day | Date | What's happening |
|---|---|---|
| 1 | Tue Apr 29 | Setup + contracts |
| 2 | Wed Apr 30 | **GATE 1** (stack working) |
| 3 | Thu May 1 | Wiring components together |
| 4 | Fri May 2 | Integration 1 + dress rehearsal |
| 5 | Mon May 5 | Drone agent building |
| 6 | Tue May 6 | Integration 2 |
| 7 | Wed May 7 | **GATE 2** (single-drone loop) |
| 8 | Thu May 8 | Multi-drone begins |
| 9 | Fri May 9 | Integration 3 + dress rehearsal |
| 10 | Mon May 12 | **GATE 3** (fine-tuning) |
| 11 | Tue May 13 | Multi-drone coordination |
| 12 | Wed May 14 | Integration 4 |
| 13 | Thu May 15 | **GATE 4** (multi-drone working) |
| 14 | Fri May 16 | Demo capture + dress rehearsal |
| 15 | Sat May 17 | Lock day + cold-run reproduce |
| 16 | Sun May 18 | **GATE 5 + SUBMIT** by 23:59 UTC |

Note: docs/17 currently lists earlier dates for these gates (e.g., Gate 2 May 5, Gate 5 May 16). The dates in this table are the ones the team executes against; docs/17's gate table will be reconciled to match in a follow-up edit.

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
