# STATUS — Day 7 / May 7, 2026

Living snapshot of where each person stands against the plan. Updated at standup. Source of truth for "are we on track for the next gate?"

**Plan:** [`19-day-by-day-plan.md`](19-day-by-day-plan.md) · **Roles:** [`18-team-roles.md`](18-team-roles.md) · **Gates:** [`17-feasibility-and-gates.md`](17-feasibility-and-gates.md)

## Where we are

- **Today:** Day 7 (Wednesday May 7) — **GATE 2 evaluation day** (single-drone full agentic loop)
- **GATE 2 status:** 5 of 7 criteria GREEN (Kaleel + Ibrahim + Hazim done); 2 owned by Qasim (EGS subscribes to real findings + reflects into `egs.state`; align `zone_polygon` to active scenario)
- **Next gate:** GATE 3 — Day 10 (Monday May 12) — fine-tuning go/no-go (Kaleel)
- **Days remaining to submission:** 11 (deadline Sunday May 18 23:59 UTC)

## Per-person status

### Hazim — Simulation Lead

**Done:** Sim foundation (`sim/waypoint_runner.py`, `sim/frame_server.py`, `agents/mesh_simulator/main.py`), scenarios (`disaster_zone_v1`, `single_drone_smoke`, `resilience_v1`), launch infra (`scripts/launch_swarm.sh`, `run_full_demo.sh`, `run_resilience_scenario.sh`, `stop_demo.sh`), uv migration with role-scoped extras + `sim_mesh` CI job, `sim/manual_pilot.py` REPL with `agents/drone_agent/validation.ValidationNode` semantic rules layered onto the JSON-Schema floor (battery / GPS-in-zone / duplicate-finding / severity↔confidence / coverage-monotonic — no second source of truth), JPEG sanity tests on every fixture frame, Phase G v1 cold-start reproduction guide at [`docs/sim-reproduction.md`](sim-reproduction.md) linked from `docs/13-runtime-setup.md`. Roadmap: [`sim/ROADMAP.md`](../sim/ROADMAP.md). PRs: #11, #12, #13, #14, #17, #18, #26, #27.

**Left:** Phase B integration with Kaleel (sim publishing stable while Kaleel iterates on Gemma 4 perception); Phase D mesh-dropout tuning live on the swarm; Phase F demo capture stability; Phase G outside-tester cold run of `docs/sim-reproduction.md` (with Thayyil) and follow-up fixes; Phase H submission on-call.

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

**Done:** WS bridge (`frontend/ws_bridge/`) with typed Redis publish; Flutter dashboard (`frontend/flutter_dashboard/lib/`) with two-stage UI, a11y, map markers, multi-drone aggregation; bridge cutover hybrid mode + multi-drone Playwright e2e; writeup draft `docs/22-writeup-draft.md`; storyboard pass `docs/21-demo-storyboard.md`. GATE 2 demo-capture: stable a11y hooks on FindingTile (`Semantics(identifier: 'finding-tile-<id>')`); `?ws=` query-param override in `main.dart`; new pytest fixtures `flutter_web_build_dir` + `flutter_static_server` in `frontend/ws_bridge/tests/conftest.py`; e2e DOM-render test `frontend/ws_bridge/tests/test_e2e_playwright_dom_render.py`; one-shot MCP capture at `docs_assets/dashboard-finding-rendered.png` per new runbook `docs/runbooks/mcp-dom-verification.md`. Live Gemma `report_finding` verified on real CC0 FEMA Katrina image (commit `30577e7`); see `docs/sim-live-run-notes.md` 2026-05-06 appendices. **Beat 4 dashboard pre-flight (2026-05-07):** Apache-2.0 `LICENSE` at repo root; `EgsLinkSeveredBanner` (top of `main.dart`'s body) keyed off `egs.state` heartbeat staleness >5s while WS connected; `_StandaloneBadge` per-drone in `drone_status_panel.dart` keyed off `agent_status == "standalone"`; both with stable `Semantics(identifier: ...)` hooks; 6 widget tests in `test/standalone_mode_test.dart`; Playwright e2e against synthetic-WS harness in `test_e2e_playwright_standalone_mode.py`; MCP capture at `docs_assets/dashboard-egs-severed.png` with Beat 4 capture path appended to the runbook. PRs: #2, #3, #5, #8, #9, #10, #15, #16, #20, #21, #22, #23, #24, #28, #29.

**Left (Days 14–16):** Beat 5 offline proof; demo video capture + edit; writeup final pass; README finalization; Kaggle submission form; two-machine backup with Thayyil.

**Blocked:** findings approval flow polish (depends on Qasim's `egs.operator_actions` subscriber); static aerial base image for map panel (depends on Thayyil's xBD frame swap).

### Thayyil — Simulation Co-Pilot (paired with Hazim)

**Done:** Co-author on sim PRs #11, #13, #14, #17, #18. Placeholder frames in `sim/fixtures/frames/`.

**Left (Kaleel-blocking, Days 6–9):** Swap placeholder JPEGs for real xBD post-disaster crops (filenames preserved); ground-truth manifest expansion.

**Left (Days 10–13):** Resilience scenario polish; integration testing prep harness for Hazim.

**Left (Days 15–16):** Reproduction docs cold-tested from a fresh machine; on-call for sim issues during submission.

## Risk register (Day 7)

| Risk | Likelihood | Impact | Owner | Mitigation |
|---|---|---|---|---|
| **GATE 2 slips today (Qasim's EGS not consuming real findings + reflecting into `egs.state`)** | **Medium** | High — descope to single-drone-only demo | Qasim | `manual_pilot.py` drives Kaleel's flow as fallback for the demo loop; Qasim aligns `zone_polygon` today |
| GATE 3 NO-GO (fine-tuning fails) | Documented | Low — fall back to base Gemma 4 + heavy prompts | Kaleel | Decision Day 10 May 12 |
| xBD frames not in `sim/fixtures/frames/` by Day 9 (TODAY = Day 7) | Medium | Medium — Kaleel iterates on placeholders, vision quality drops before fine-tune | Thayyil | Swap is one commit; filenames preserved. Escalate at standup if not landed by Day 8 |
| ~~Beat 3b unfilmable: live Gemma `report_finding` not verified end-to-end through dashboard~~ | ~~closed~~ | — | Ibrahim | **CLOSED 2026-05-06.** Live `report_finding` on CC0 FEMA Katrina image verified 5× (`docs/sim-live-run-notes.md` Gap #2); DOM render verified by `test_e2e_playwright_dom_render.py` + MCP capture at `docs_assets/dashboard-finding-rendered.png`. |
| ~~Storyboard Beat 4 unfilmable (no STANDALONE UI)~~ | ~~closed~~ | — | Ibrahim | **CLOSED 2026-05-07.** Banner + badge shipped (#28); Playwright e2e + MCP capture verified (#29); `docs_assets/dashboard-egs-severed.png` is the reference asset. Awaits Kaleel's runtime `agent_status` flips for full live light-up (TODOS.md). |

## How to update this doc

At each daily standup, the person with new shipped work edits their section. Risk register reviewed at every gate. New gates surface new risks — add them.
