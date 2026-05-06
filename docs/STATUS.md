# STATUS — Day 6 / May 6, 2026

Living snapshot of where each person stands against the plan. Updated at standup. Source of truth for "are we on track for the next gate?"

**Plan:** [`19-day-by-day-plan.md`](19-day-by-day-plan.md) · **Roles:** [`18-team-roles.md`](18-team-roles.md) · **Gates:** [`17-feasibility-and-gates.md`](17-feasibility-and-gates.md)

## Where we are

- **Today:** Day 6 (Tuesday May 6) — second integration session per the plan
- **Next gate:** GATE 2 — Day 7 (Wednesday May 7) — single-drone full agentic loop
- **Days remaining to submission:** 12 (deadline Sunday May 18 23:59 UTC)

## Per-person status

### Hazim — Simulation Lead

**Done:** Sim foundation (`sim/waypoint_runner.py`, `sim/frame_server.py`, `agents/mesh_simulator/main.py`), scenarios (`disaster_zone_v1`, `single_drone_smoke`, `resilience_v1`), launch infra (`scripts/launch_swarm.sh`, `run_full_demo.sh`, `run_resilience_scenario.sh`, `stop_demo.sh`), uv migration with role-scoped extras + `sim_mesh` CI job, `sim/manual_pilot.py` REPL, JPEG sanity tests on every fixture frame. Roadmap: [`sim/ROADMAP.md`](../sim/ROADMAP.md). PRs: #11, #12, #13, #14, #17, #18.

**Left:** Phase B integration with Kaleel (sim publishing stable while Kaleel iterates on Gemma 4 perception); Phase D mesh-dropout tuning live on the swarm; Phase F demo capture stability; Phase G reproduction docs (cold-tested with Thayyil); Phase H submission on-call.

**Blocked on:** Kaleel publishing real findings on `drones.<id>.findings`; Qasim consuming them; Thayyil swapping real xBD JPEGs into `sim/fixtures/frames/`.

### Kaleel — Per-Drone Agent + ML

**Done:** Drone LangGraph nodes scaffolded — `agents/drone_agent/{perception,reasoning,validation,action,memory,main}.py` with `standalone_test.py`. ML pipeline scripts under `ml/data_prep/` and `ml/training/`: `download_xbd.py`, `crop_patches.py`, `format_for_gemma.py`, `split_dataset.py`, `verify_unsloth.py`, `finetune_lora.py`. Recent: configurable model, CPU/text-only fallbacks, synthetic test image, absolute-imports fix. Commits: `88b16d5`, `6081d92`, `8af12fc`, `eaf8fa5`.

**Done (GATE 2 — feature/drone-agent-redis-wiring):** drone agent subscribes to `drones.<id>.camera` + `drones.<id>.state` from Redis (CameraSubscriber + StateSubscriber in `agents/drone_agent/redis_io.py`); publishes Contract-4 findings on `drones.<id>.findings` with persisted `image_path` (action node + RedisPublisher); peer broadcasts on `swarm.broadcasts.<id>`; merged `drones.<id>.state` republishes carry agent-owned fields (`last_action`, `findings_count`, `validation_failures_total`); validation event log migrated to Contract 11 format at `/tmp/gemma_guardian_logs/validation_events.jsonl`. Entry point `python -m agents.drone_agent --drone-id drone1 --scenario disaster_zone_v1`. 51 drone-agent tests passing.

**Left (GATE 3 critical, Day 10 / May 12):** xBD preprocessing complete; LoRA training on the recipe in [`docs/12-fine-tuning-plan.md`](12-fine-tuning-plan.md) (rank 32, target_modules="all-linear", finetune_vision_layers=False to start); fine-tuning gate decision (GO/NO-GO).

**Left (GATE 4 critical, Day 13 / May 15):** Peer-broadcast handling in reasoning prompt; cross-drone awareness; adapter integration if Day 10 GO.

### Qasim — EGS / Coordination

**Done:** EGS process scaffolded — `agents/egs_agent/{main,coordinator,validation,replanning,command_translator}.py`. Phase 4 command-translation path with finding allowlist + CI gate. PRs: #4, #5.

**Left (GATE 2 critical, today/tomorrow):** EGS subscribes to `drones.<id>.findings` from real drone agents (not fake producers); reflects findings into `egs.state` for the dashboard; **align hardcoded `zone_polygon` in `agents/egs_agent/main.py` with the active scenario YAML** (still ships the demo LA bbox). Spec: [`docs/06-edge-ground-station.md`](06-edge-ground-station.md).

**Left (GATE 4 critical, Day 13 / May 15):** Replanning logic triggered by drone failure (TODOS marker), multilingual command path producing real `preview_text_in_operator_language` via Gemma 4 E4B (TODOS Phase 5+ stub today), standalone-mode tolerance when EGS goes offline, EGS-side subscriber for `egs.operator_actions` (TODOS open). The "wow moment" demo trigger (hallucination catch in survey-point assignment) per [`docs/10-validation-and-retry-loop.md`](10-validation-and-retry-loop.md) Approach 1.

### Ibrahim — Frontend + Demo + Comms (project lead)

**Done:** WS bridge (`frontend/ws_bridge/`) with typed Redis publish; Flutter dashboard (`frontend/flutter_dashboard/lib/`) with two-stage UI, a11y, map markers, multi-drone aggregation; bridge cutover hybrid mode + multi-drone Playwright e2e; writeup draft `docs/22-writeup-draft.md`; storyboard pass `docs/21-demo-storyboard.md`. PRs: #2, #3, #5, #8, #9, #10, #15, #16, #20, #21, #22, #23, #24.

**Left (storyboard-blocking, before demo capture Day 14):** `STANDALONE MODE ACTIVE` rendering in dashboard (Beat 4); `LICENSE` file at repo root (Beat 5 caveat); EGS-link-severed card; findings approval flow polish; static aerial base image for map panel (TODOS, depends on Thayyil).

**Left (Days 14–16):** Demo video capture + edit; writeup final pass; README finalization; Kaggle submission form; two-machine backup with Thayyil.

### Thayyil — Simulation Co-Pilot (paired with Hazim)

**Done:** Co-author on sim PRs #11, #13, #14, #17, #18. Placeholder frames in `sim/fixtures/frames/`.

**Left (Kaleel-blocking, Days 6–9):** Swap placeholder JPEGs for real xBD post-disaster crops (filenames preserved); ground-truth manifest expansion.

**Left (Days 10–13):** Resilience scenario polish; integration testing prep harness for Hazim.

**Left (Days 15–16):** Reproduction docs cold-tested from a fresh machine; on-call for sim issues during submission.

## Risk register (Day 6)

| Risk | Likelihood | Impact | Owner | Mitigation |
|---|---|---|---|---|
| GATE 2 slips (drone agent + EGS not wired end-to-end by EOD May 7) | Medium | High — descope to single-drone-only demo | Kaleel + Qasim | Use `manual_pilot.py` to drive Kaleel's flow; Qasim aligns `zone_polygon` today |
| GATE 3 NO-GO (fine-tuning fails) | Documented | Low — fall back to base Gemma 4 + heavy prompts | Kaleel | Decision Day 10 May 12 |
| Storyboard Beat 4 unfilmable (no STANDALONE UI) | Medium | Medium — fall back to Backup Beat 4 (GPS-failure replan) | Ibrahim | Build standalone UI Days 7–13 OR use backup |
| xBD frames not in `sim/fixtures/frames/` by Day 9 | Low | Medium — Kaleel iterates on placeholders, vision quality drops | Thayyil | Swap is one commit; filenames preserved |

## How to update this doc

At each daily standup, the person with new shipped work edits their section. Risk register reviewed at every gate. New gates surface new risks — add them.
