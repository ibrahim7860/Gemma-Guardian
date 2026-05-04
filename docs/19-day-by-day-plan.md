# 19 — Day-by-Day Plan

## Why This Doc Exists

20 days from start to submission. Each day has assigned work for each person. Daily standup checks against this plan; deviations trigger replanning.

**Start date:** Tuesday, April 29, 2026
**Submission deadline:** Sunday, May 18, 2026, 23:59 UTC

## Week 1 (Days 1-7): Foundations and Single-Drone Loop

### Day 1 — Tuesday April 29: Setup Day

**All hands:** Lock the integration contracts. Read [`20-integration-contracts.md`](20-integration-contracts.md). Lock the function-calling schemas. Do not change them after today except for true bugs. (Contracts locked April 30, 2026 — this is already in-flight.)

**Hazim:** Install `redis-server` (`brew install redis` / `apt install redis-server`). Set up `sim/` directory skeleton. Write the `sim/waypoint_runner.py` skeleton that reads `sim/scenarios/disaster_zone_v1.yaml` and publishes `drones.drone1.state` on Redis.
**Kaleel:** Install Ollama, pull Gemma 4 E2B, build standalone Python script that takes image + state → function call. Use stock images. Start Unsloth verification and kick off xBD download (~50GB) on Kaleel's own machine.
**Qasim:** Install second Ollama instance for E4B. Build assignment-and-validation loop with mock drone states.
**Ibrahim:** Set up Flutter project + FastAPI WebSocket bridge (`frontend/ws_bridge/`). Static dashboard layout with mock data.
**Thayyil (paired with Hazim):** Install Python 3.11+ and `redis-server` on their own machine (identical setup, any OS). Begin curating frame library from xBD dataset — browse xBD post-disaster crops; identify visually distinct tiles for victims, fires, damaged structures. Draft ground-truth manifest schema.

**End of day check:** Everyone has their dev environment working. Day 1 is mostly setup, not output.

### Day 2 — Wednesday April 30: GATE 1

**Hazim:** `sim/waypoint_runner.py` publishes `drones.drone1.state` on Redis. `sim/frame_server.py` skeleton publishes `drones.drone1.camera` (JPEG bytes). Smoke-test: a Python subscriber script prints both.
**Kaleel:** Standalone agent script returns valid function call from Gemma 4 on a stock image. **Day-2 verification: Unsloth supports Gemma 4 vision LoRA.** If yes, continue with fine-tuning plan. If no, ABANDON fine-tuning. Vision prompt validation continues against stock images.
**Qasim:** EGS process generates valid survey-point assignment via Gemma 4 E4B with mock drones.
**Ibrahim:** Flutter dashboard renders mock state correctly. FastAPI WebSocket bridge connects to Redis.
**Thayyil (paired with Hazim):** Thayyil's Redis + Python install verified working. Initial frame library curated from xBD: first batch of frames committed to `sim/fixtures/frames/`. `disaster_zone_v1.yaml` skeleton with drone home positions created.

**Gate 1 evaluation at end of day:** All criteria met? See [`17-feasibility-and-gates.md`](17-feasibility-and-gates.md). Continue if yes, pivot if no.

### Day 3 — Thursday May 1

**Hazim:** Wire frame mappings into `sim/frame_server.py` — serve the correct JPEG for each drone/tick combination from `disaster_zone_v1.yaml`. Verify end-to-end: subscriber receives correct frame for each simulated tick.
**Kaleel:** Wire up real Redis camera channel (`drones.drone1.camera`) to drone agent (replaces stock images). Define eval criteria for fine-tuned adapter (what counts as passing). Begin xBD preprocessing on own time.
**Qasim:** Connect EGS to mock telemetry stream from Redis (still no real drone agents yet).
**Ibrahim:** WebSocket bridge forwarding live `egs.state` mock from Qasim; Flutter rendering it.
**Thayyil (paired with Hazim):** Expand frame library (victims, fires, blocked routes). Wire all frame files into `disaster_zone_v1.yaml` frame mappings. Begin `disaster_zone_v1_groundtruth.json` with victim and damage entries.

### Day 4 — Friday May 2: First Integration Session

**Integration session (afternoon):** Hazim + Kaleel wire the Redis camera channel into the drone agent. End of day: drone sim publishes state + camera on Redis; drone agent subscribes, calls Gemma 4 at 1 Hz, emits structured function calls.

**Qasim:** Refine validation loop with corrective prompts from [`10-validation-and-retry-loop.md`](10-validation-and-retry-loop.md).
**Ibrahim:** Build the findings feed and command box panels.
**Kaleel:** Begin LoRA training solo. First training run: small subset, conservative hyperparameters, validate it works.
**Thayyil (paired with Hazim):** Scenario v1 complete (all waypoints mapped, all frame mappings wired). Ground-truth manifest JSON drafted with initial entries.

**Friday dress rehearsal:** Whatever works, rehearse demoing it. 30-minute exercise.

### Day 5 — Monday May 5

**Hazim:** Add `drone2` to `disaster_zone_v1.yaml` (home position, waypoints, frame mappings). Multi-drone sim experimentation begins — verify `waypoint_runner.py` and `frame_server.py` handle multiple drone IDs on separate Redis channels.
**Kaleel:** Implement validation node with corrective re-prompts. Test catching engineered failures. Continue LoRA training solo; track validation accuracy.
**Qasim:** Real drone state ingestion from Redis. Real assignment dispatched to drone via `drones.<id>.tasks` channel.
**Ibrahim:** Map view panel showing drone position live (from `drones.*.state` via WebSocket bridge).
**Thayyil (paired with Hazim):** Expand frame library with victim, fire, and debris frames. Update ground-truth manifest with all scenario entries. Research multi-drone Redis channel namespacing — verify pattern-subscribe works for `drones.*.state`.

### Day 6 — Tuesday May 6: Second Integration Session

**Integration session (afternoon):** End-to-end on a single drone. Sim publishes state + camera on Redis, drone agent picks up a victim frame, generates `report_finding`, validation passes, EGS receives on `drones.drone1.findings`, dashboard shows it. Iterate until it works.

**Kaleel:** Vision prompts iterate based on real frames from `sim/fixtures/frames/`.
**Thayyil (paired with Hazim):** Pull candidate frames from the frame library at victim/fire waypoints and hand them to Kaleel for prompt iteration. Swap out any frames Gemma struggles with; document substitutions in the scenario YAML comment.

### Day 7 — Wednesday May 7: GATE 2

**All hands:** Run the full single-drone scenario and demonstrate Gate 2 criteria. See [`17-feasibility-and-gates.md`](17-feasibility-and-gates.md).

**Gate 2 evaluation at end of day:**
- PASS: Continue to multi-drone in Week 2.
- FAIL: Drop swarm scope, polish single-drone for the demo.

## Week 2 (Days 8-13): Multi-Drone and EGS Polish

### Day 8 — Thursday May 8

**Hazim:** Run 2-drone simulation: `waypoint_runner.py` and `frame_server.py` publish on `drones.drone1.*` and `drones.drone2.*` simultaneously. Verify no message collisions.
**Kaleel:** Drone agent runs in parallel for 2 drones with shared Ollama instance + queue. Continue LoRA training solo; approaching the gate decision.
**Qasim:** Operator command translation path with English + Spanish.
**Ibrahim:** Multilingual command box with language selector. Live translation preview.
**Thayyil (paired with Hazim):** Own the launch-script plumbing for multi-drone — `launch_swarm.sh` starts `redis-server`, both sim processes, both drone agents, EGS, WebSocket bridge. Verify all Redis channels are properly per-drone scoped.

### Day 9 — Friday May 9: Third Integration Session

**Integration session:** 2 drones running parallel agent loops, both reporting findings to EGS, both visible on dashboard.

**Kaleel:** Final LoRA training runs before Gate 3 (solo).

**Friday dress rehearsal:** 2-drone scenario.

### Day 10 — Monday May 12: GATE 3

**Kaleel demonstrates fine-tuning results.** See [`12-fine-tuning-plan.md`](12-fine-tuning-plan.md) and [`17-feasibility-and-gates.md`](17-feasibility-and-gates.md).

**Gate 3 evaluation:**
- PASS: Kaleel integrates adapter into drone agent (same seat, no handoff).
- FAIL: Adapter dropped. Kaleel falls back to base Gemma 4 + heavy prompts. **Thayyil stays with Hazim — no reassignment.**

**Other people in parallel:**
**Hazim:** Spawn 3rd drone (if Gate 4 trajectory looks good).
**Kaleel:** Implement peer broadcast handling in reasoning prompt.
**Qasim:** Replanning trigger logic: drone failure → re-assignment.
**Ibrahim:** Findings approval flow. Validation event ticker on drone status panels.
**Thayyil (paired with Hazim):** 3-drone scenario YAML plumbing (add `drone3` to `disaster_zone_v1.yaml`). Begin scripting resilience scenarios as scripted events in the YAML — `drone_failure` at T+45s, `zone_update` at T+60s — and verify `waypoint_runner.py` fires them.

### Day 11 — Tuesday May 13

**Hazim:** `agents/mesh_simulator/main.py` with range-based dropout running on Redis (`swarm.broadcasts.*` → `swarm.<id>.visible_to.<id>`).
**Kaleel:** Cross-drone awareness: drone B reasons about whether to investigate drone A's low-confidence finding. If GO: integrate adapter and test on frames from `sim/fixtures/frames/`.
**Qasim:** Standalone-mode logic: drone continues without EGS heartbeat.
**Ibrahim:** Polish dashboard visual hierarchy.
**Thayyil (paired with Hazim):** Help Hazim build the mesh dropout simulator. Wire scripted resilience events (drone failure, comm loss) into `scripts/launch_swarm.sh` and scenario YAML.

### Day 12 — Wednesday May 14: Fourth Integration Session

**Integration session:** Full 3-drone scenario (or 2-drone if dropped). Resilience scenario 1: drone failure triggers EGS replanning.

### Day 13 — Thursday May 15: GATE 4

**Gate 4 evaluation:** Multi-drone coordination working? See [`17-feasibility-and-gates.md`](17-feasibility-and-gates.md).

- PASS: Continue with 3 drones for demo.
- FAIL: Drop to 2 drones. Adjust demo storyboard.

**Post-gate work (afternoon, all hands):**
**Hazim:** Identify and fix any sim instability surfaced during the gate run.
**Kaleel:** Note any prompt-quality issues spotted during the gate run; queue for Day 14 tuning.
**Qasim:** Lock the demo's resilience-scenario script (which scenarios run, in what order).
**Ibrahim:** Lock demo storyboard with the team. **Begin writeup first draft** (architecture and approach sections — these are stable post-Gate 4).
**Thayyil (paired with Hazim):** Help Hazim diagnose any sim issues from the gate run.

## Week 3 (Days 14-18): Polish and Demo Capture

### Day 14 — Friday May 16: Demo Capture Begins

**All hands:** Begin running the full demo scenario repeatedly. Capture the cleanest runs.

**Hazim:** Provide stable demo runs. Fix any simulation jitter.
**Kaleel:** Tune reasoning prompts for demo quality. Engineer the hallucination-catch moment.
**Qasim:** Script the resilience scenarios as deterministic events on the EGS side (sim-side events were prepped by Thayyil).
**Ibrahim:** Polish dashboard visual quality. Test all dashboard interactions for video. **Begin video editing** (using clean runs as they're captured). Writeup draft continues from Day 13 start.
**Thayyil (paired with Hazim):** Run the simulator while Hazim monitors stability. Reproduce the demo scenario over and over to surface any sim jitter. Help Hazim with final scene polish.

**Friday dress rehearsal:** Full demo run. Identify everything that's still rough.

### Day 15 — Saturday May 17

**Hazim:** Final scenario and frame-library polish.
**Kaleel:** Engineer the validation-catch moment to reliably trigger.
**Qasim:** Multilingual command path tested on video-quality scenarios.
**Ibrahim:** Demo capture — record dashboard runs cleanly. Video editing continues. Writeup draft.
**Thayyil (paired with Hazim):** Operate the sim processes on the demo machine so Ibrahim can record the dashboard cleanly. Help Hazim lock the scenario YAML.

### Day 15 — Saturday May 17: Lock + Reproduce

**Today is the day everything stops changing.** Only bug fixes after this point. **No new features. No "small additions."** Whatever's there is what ships.

**Hazim:** Lock simulation. Have an outside-the-team tester run reproduction instructions cold; Thayyil acts as backup tester. Fix anything that breaks the cold run.
**Kaleel:** Lock prompts. Don't iterate further. Code cleanup for public repo.
**Qasim:** Lock EGS. Test resilience scenarios one final time. Code cleanup for public repo.
**Ibrahim:** Lock dashboard. Final video captures. Video edit to picture-lock. Writeup near-final draft circulated for team review.
**Thayyil (paired with Hazim):** Co-write the simulation reproduction docs with Hazim. Run them cold from a fresh machine (any OS — the stack is cross-platform). Document any rough edges.

### Day 16 — Sunday May 18: GATE 5 + SUBMIT (deadline 23:59 UTC)

**Submission day. The plan calls for submitting by ~18:00 UTC, leaving ~6 hours of buffer before the 23:59 UTC deadline.** No new features today, only finalizing deliverables and pressing the button.

**Hazim:** Final reproduction-doc fixes from cold tester feedback. Backup the demo box. On-call for any submission-time sim issue.
**Kaleel:** Final repo cleanup. Confirm Ollama / model pull instructions work from scratch. On-call for prompt or model issues.
**Qasim:** Final repo cleanup. Confirm EGS launches from the documented command. On-call for EGS issues.
**Ibrahim:** Video final export and upload. Writeup proofread and finalized. **Owns the Kaggle submission form.** Confirms all required fields, links, and attachments. Submits by 18:00 UTC. Posts confirmation to the team.
**Thayyil (paired with Hazim):** Final reproduction validation pass. Backup of repo + assets to a second machine. On-call for sim issues.

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
