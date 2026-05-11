# Hazim (Sim Lead) — Roadmap

A date-free checklist of what Hazim owns and what's left. Keep this current; refer back instead of re-deriving from the day plan every standup.

## Done (shipped on `feature/sim-mesh-foundation`)

- `sim/geo.py` — haversine, interpolation, meters↔degrees.
- `sim/scenario.py` — Pydantic `Scenario` + `GroundTruth` loaders.
- `sim/waypoint_runner.py` — publishes `drones.<id>.state` (schema-valid, 2 Hz).
- `sim/frame_server.py` — publishes `drones.<id>.camera` (raw JPEG bytes, 1 Hz).
- `sim/scenarios/disaster_zone_v1.yaml` (3-drone) + `single_drone_smoke.yaml` + ground-truth JSON.
- `sim/fixtures/frames/` — 8 placeholder JPEGs (Thayyil swaps in real xBD imagery).
- `agents/mesh_simulator/range_filter.py` + `agents/mesh_simulator/main.py` — Euclidean range dropout, EGS link, adjacency snapshot.
- `scripts/launch_swarm.sh` + `stop_demo.sh` + `run_full_demo.sh` — tmux orchestration with `--dry-run`, `--drones=`, missing-component tolerance.
- 73 new pytest cases (sim + mesh + scripts).
- Docs aligned: `docs/13-runtime-setup.md` covers WSL2 / 24.04 / PEP 668; `docs/15-multi-drone-spawning.md` points at the real scripts.

## Done (shipped on `feature/uv-and-ci`)

- `pyproject.toml` + `uv.lock` at repo root — single source of truth for Python deps via role-scoped extras (`sim`, `mesh`, `drone`, `egs`, `ws_bridge`, `ml`, `dev`).
- All seven per-role `requirements.txt` files deleted; install is now `uv sync --extra <role> --extra dev`.
- `.github/workflows/test.yml` — migrated to `astral-sh/setup-uv@v3` + `uv sync --frozen`; new `sim_mesh` CI job covers `pytest sim/ agents/mesh_simulator/ scripts/tests/`. `bridge`, `flutter`, `bridge_e2e` jobs intact.
- Docs updated for the uv switch: `docs/13-runtime-setup.md` (uv primary, pip fallback), `docs/23-submission-checklist.md`, `frontend/flutter_dashboard/README.md`, `scripts/launch_dashboard_dev.sh`, `scripts/run_dashboard_dev.sh`, `frontend/ws_bridge/tests/conftest.py`, `TODOS.md`, and the entry-point `CLAUDE.md` so other collaborators' Claude Code picks up the change.

## Done (shipped on `feature/sim-live-run-followups`)

- `launch_swarm.sh` writes a `$LOG_DIR/.gg_started_redis` sentinel only when it daemonizes its own Redis; `stop_demo.sh` only `redis-cli shutdown nosave`s when that sentinel exists, then removes it. Fixes anomaly #3 from `docs/sim-live-run-notes.md` — system-managed Redis is no longer interrupted by `stop_demo.sh` (slice A).
- `scripts/run_full_demo.sh` `--duration=N` forwarding documented in the script header and in `docs/15-multi-drone-spawning.md`, with a regression test that pins the propagation through to the sim runners (slice B).
- `scripts/launch_swarm.sh --drones=<csv>` validates every requested id is in the scenario YAML (via `sim/list_drones.py`); unknown ids exit non-zero with the offending id and the scenario's available roster, instead of silently launching a ghost drone agent (slice C).

## Done (shipped on `feature/sim-polish`)

- `--redis-url` default on `waypoint_runner` / `frame_server` / `mesh_simulator` derived from `CONFIG.transport.redis_url` (slice A).
- Pydantic `Scenario` cross-validates `scripted_events[].drone_id ⊆ drones[]` at load (slice B).
- `WaypointRunner.main()` fails fast if `CONFIG.mission.drone_count` ≠ `len(scenario.drones)` (slice C).
- `scripts/launch_swarm.sh --drones=auto` (the new default) derives the roster from the scenario YAML via `sim/list_drones.py`. Explicit `--drones=drone1,drone2` still works (slice D).
- `--duration <seconds>` flag on `waypoint_runner` and `frame_server`; propagated through `launch_swarm.sh --duration=N` (slice E).
- Live multi-drone run on real Redis captured in `docs/sim-live-run-notes.md`. Surfaced and fixed a pre-existing tmux duplicate-window bug in `launch_swarm.sh` (slice F).
- Repo-root `README.md` written (slice G).

## Done (shipped on `feature/sim-resilience-and-pilot`)

- `sim/scenarios/resilience_v1.yaml` + `_groundtruth.json` — Phase D / E rehearsal substrate. 3 drones start in-mesh (~25m apart), fan radially outward at 5 m/s. By t≈18s the drone1↔drone3 pair drops out of the 200m mesh range, and by t≈98s both drone1 and drone3 exit the 500m EGS link. Scripted events exercise drone_failure, fire_spread, egs_link_drop, egs_link_restore, mission_complete in one run. Reuses only existing `sim/fixtures/frames/` placeholders so Thayyil's xBD swap stays orthogonal. `scripts/run_resilience_scenario.sh` wraps `launch_swarm.sh resilience_v1` with a sensible `--duration=240` default (slice A).
- `sim/tests/test_frames_directory.py` extended with per-file JPEG sanity assertions: non-zero size, 3-byte JPEG SOI prefix, Pillow `Image.verify()` succeeds, parsed dimensions ≥ 64×64. When Thayyil swaps in real xBD JPEGs, a corrupt or empty file fails CI loudly rather than at demo time (slice B).
- `sim/manual_pilot.py` — interactive single-drone REPL stand-in for the per-drone agent. Subscribes to `drones.<id>.state`, `drones.<id>.camera`, and `swarm.<id>.visible_to.<id>`; lets a human emit findings, broadcasts, and function calls into a live sim. Schema-only validation floor via `shared/contracts/schemas.validate` (semantic rules belong to Kaleel's `agents/drone_agent/validation.py` — TODO marker in the source). `docs/15-multi-drone-spawning.md` documents the side-by-side workflow with `launch_swarm.sh --drones=drone2,drone3` (slice C).

## Phases ahead (in order, no dates)

### Phase A — Live multi-drone smoke
- ✅ Done as part of slice F (`feature/sim-polish`). 3-drone run against real Redis, sim + mesh streaming cleanly, schema-valid payloads, mesh adjacency full-mesh as expected. Notes: [`docs/sim-live-run-notes.md`](../docs/sim-live-run-notes.md).

### Phase B — Integration session with Kaleel (drone_agent)
- Kaleel subscribes to `drones.<id>.camera` and `drones.<id>.state`, runs Gemma 4 perception, emits findings on `drones.<id>.findings`.
- My job: keep the sim publishing stable while Kaleel iterates. Be ready to re-author scenario YAMLs / scripted events on demand.
- **Blocked on:** Thayyil swapping real xBD JPEGs into `sim/fixtures/frames/`. The filenames stay; only the bytes change.

### Phase C — Gate 2 (single-drone full agentic loop)
- Sim publishes → drone_agent reasons → EGS receives finding on `drones.<id>.findings` → dashboard shows it via `egs.state`.
- I report the gate trajectory at standup.

### Phase D — Mesh dropout live on the swarm
- **Sim-side: ✅ green** as of 2026-05-11. `agents/mesh_simulator/main.py` running in the integrated stack on `resilience_v1`; mesh adjacency dynamics match the scenario's authored geometry without tuning (`range_meters=200`, `egs_link_range_meters=500`). 180s end-to-end run captured in [`docs/sim-resilience-run-notes.md`](../docs/sim-resilience-run-notes.md) "2026-05-11 re-run" section.
- **`drone_failure → drones.<id>.tasks` chain: ❌ still blocked**, now on a *new* EGS-side bug (in-flight replan guard never clears under VRAM pressure; see notes-doc "Bug 3" and GH #32 comment). The original Bug 1 (egs_state schema seed) closed via PR #34/#45 commit `9cda8cb` — verified live (0 schema errors vs 268 on 2026-05-07).

### Phase E — Gate 4 (multi-drone coordination)
- **Sim-side: ✅ green** as of 2026-05-11. 2–3 drones coordinating; scripted resilience events (drone_failure, fire_spread, egs_link_drop, egs_link_restore, mission_complete) fire on schedule; mesh dropout produces the right adjacency dynamics. `drone_agent` GATE 2 wiring (PR #25) + EGS GATE 4 wiring (PR #45) both consume the sim's output cleanly.
- **EGS-side replan publishing: ❌** — same blocker as Phase D's last criterion. Not Hazim-scope to fix.

### Phase F — Demo capture
- Stable, jitter-free sim runs for video capture. Fix any flakiness Ibrahim surfaces during recording.

### Phase G — Lock + reproduction docs
- v1 draft of [`docs/sim-reproduction.md`](../docs/sim-reproduction.md) shipped on `sim/phase-g-reproduction-docs` (cross-platform prereqs, uv install, `pytest sim/ agents/mesh_simulator/ scripts/tests/`, the three escalating one-command demos, per-layer health checks, common-failures section drawn from `sim-live-run-notes.md` + `scripts/tests/`). Linked from `docs/13-runtime-setup.md`.
- Remaining: co-write follow-ups with Thayyil, then have an outside tester run cold from scratch on a fresh box and fix everything that breaks the cold run.

### Phase H — Submission
- Final repro-doc fixes from cold-tester feedback. Backup of the demo box. On-call for any submission-time sim issue.

## Ongoing (always-on)

- Redis infrastructure on the demo box.
- Cross-team integration testing — sim is the common substrate everyone hits.
- Standup gate-trajectory reports.

## Currently blocked on others

| Blocker | Owner | What unblocks me |
|---|---|---|
| ~~Real xBD frames in `sim/fixtures/frames/`~~ | ~~Thayyil~~ | **Closed 2026-05-08 (PR #35)** — real public-domain FEMA/USFWS aerials swapped in via `scripts/fetch_disaster_fixtures.py`. |
| ~~`drone_agent` consuming `drones.<id>.camera` + writing merged state~~ | ~~Kaleel~~ | **Closed 2026-05-06 (PR #25)** — drone agent subscribes/publishes per Contract 4, 11. Live-verified on the 2026-05-11 resilience run. |
| ~~`egs_agent` consuming `drones.<id>.findings`, issuing `drones.<id>.tasks`~~ | ~~Qasim~~ | **Partially closed 2026-05-09–11 (PRs #34, #45)** — EGS subscribes to findings, scripted-event drone_failure handling, schema-aligned `egs_state` publishes. Outstanding: `drones.<id>.tasks` not yet published end-to-end because the EGS coordinator's `_replan_in_flight` guard never clears when Ollama is slow under 8GB-VRAM eviction pressure (see GH #32 comment + `docs/sim-resilience-run-notes.md` "Bug 3"). |

Nothing on this table currently blocks Hazim from advancing Phase F (demo capture). The remaining `drone_failure → drones.<id>.tasks` link is Qasim-scope.

## Polish queue (unblocked, opportunistic)

All initial polish-queue items shipped on `feature/sim-polish`. Add new
items here as they surface during integration sessions or live-run fallout.

- ~~`sim/manual_pilot.py` schema-only validation floor — layer Kaleel's
  `agents/drone_agent/validation.py` semantic rules (battery, GPS,
  duplicate-finding, severity↔confidence, coverage-monotonic) on top so the
  REPL surfaces the same retry-loop feedback the real drone agent does.~~
  Shipped on `sim/manual-pilot-semantic-validation`. ValidationNode is
  reused in-place — no second source of truth — and the REPL takes an
  optional `--scenario` to enable the GPS_OUTSIDE_ZONE check.

### Follow-ups surfaced by the live run (low priority, out of Hazim scope)

- `agents/drone_agent/main.py` ImportError on relative imports when run as a script (`python3 agents/drone_agent/main.py`). Ping Kaleel.
- ~~`scripts/stop_demo.sh` shuts down Redis even when it didn't start it.~~ Shipped on `feature/sim-live-run-followups`, slice A.
- ~~`ws_bridge` cutover from `dev_fake_producers.py` → real sim source~~ Shipped on `feature/bridge-cutover-hybrid` (PR #20). Run `scripts/run_hybrid_demo.sh disaster_zone_v1` and the dashboard renders the sim's live drone state. Fakes still cover `egs.state` and `drones.<id>.findings` until Qasim/Kaleel ship; opt out via `--no-fake-egs` / `--no-fake-findings`.
- ~~`scripts/launch_swarm.sh` invokes the bridge as `python3 frontend/ws_bridge/main.py`, which only constructs the FastAPI app and exits (no server).~~ Shipped on `feature/launch-swarm-uvicorn-fix` — bridge now launches via `python3 -m uvicorn frontend.ws_bridge.main:app --port 9090`, matching `run_hybrid_demo.sh` and `launch_dashboard_dev.sh`. Regression test: `test_launch_swarm_bridge_invocation_uses_uvicorn`.
