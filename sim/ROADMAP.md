# Person 1 (Sim Lead) — Roadmap

A date-free checklist of what Person 1 owns and what's left. Keep this current; refer back instead of re-deriving from the day plan every standup.

## Done (shipped on `feature/sim-mesh-foundation`)

- `sim/geo.py` — haversine, interpolation, meters↔degrees.
- `sim/scenario.py` — Pydantic `Scenario` + `GroundTruth` loaders.
- `sim/waypoint_runner.py` — publishes `drones.<id>.state` (schema-valid, 2 Hz).
- `sim/frame_server.py` — publishes `drones.<id>.camera` (raw JPEG bytes, 1 Hz).
- `sim/scenarios/disaster_zone_v1.yaml` (3-drone) + `single_drone_smoke.yaml` + ground-truth JSON.
- `sim/fixtures/frames/` — 8 placeholder JPEGs (Person 5 swaps in real xBD imagery).
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

## Done (shipped on `feature/sim-polish`)

- `--redis-url` default on `waypoint_runner` / `frame_server` / `mesh_simulator` derived from `CONFIG.transport.redis_url` (slice A).
- Pydantic `Scenario` cross-validates `scripted_events[].drone_id ⊆ drones[]` at load (slice B).
- `WaypointRunner.main()` fails fast if `CONFIG.mission.drone_count` ≠ `len(scenario.drones)` (slice C).
- `scripts/launch_swarm.sh --drones=auto` (the new default) derives the roster from the scenario YAML via `sim/list_drones.py`. Explicit `--drones=drone1,drone2` still works (slice D).
- `--duration <seconds>` flag on `waypoint_runner` and `frame_server`; propagated through `launch_swarm.sh --duration=N` (slice E).
- Live multi-drone run on real Redis captured in `docs/sim-live-run-notes.md`. Surfaced and fixed a pre-existing tmux duplicate-window bug in `launch_swarm.sh` (slice F).
- Repo-root `README.md` written (slice G).

## Phases ahead (in order, no dates)

### Phase A — Live multi-drone smoke
- ✅ Done as part of slice F (`feature/sim-polish`). 3-drone run against real Redis, sim + mesh streaming cleanly, schema-valid payloads, mesh adjacency full-mesh as expected. Notes: [`docs/sim-live-run-notes.md`](../docs/sim-live-run-notes.md).

### Phase B — Integration session with Person 2 (drone_agent)
- Person 2 subscribes to `drones.<id>.camera` and `drones.<id>.state`, runs Gemma 4 perception, emits findings on `drones.<id>.findings`.
- My job: keep the sim publishing stable while Person 2 iterates. Be ready to re-author scenario YAMLs / scripted events on demand.
- **Blocked on:** Person 5 swapping real xBD JPEGs into `sim/fixtures/frames/`. The filenames stay; only the bytes change.

### Phase C — Gate 2 (single-drone full agentic loop)
- Sim publishes → drone_agent reasons → EGS receives finding on `drones.<id>.findings` → dashboard shows it via `egs.state`.
- I report the gate trajectory at standup.

### Phase D — Mesh dropout live on the swarm
- `agents/mesh_simulator/main.py` already runs against fakeredis in tests. Phase D is wiring it into the integrated stack and tuning `range_meters` / `egs_link_range_meters` in `shared/config.yaml` until resilience scenario 1 (drone_failure → EGS replan) fires correctly.

### Phase E — Gate 4 (multi-drone coordination)
- 2–3 drones coordinating; scripted resilience events fire on schedule; mesh dropout produces the right adjacency dynamics.

### Phase F — Demo capture
- Stable, jitter-free sim runs for video capture. Fix any flakiness Person 4 surfaces during recording.

### Phase G — Lock + reproduction docs
- Co-write `docs/sim-reproduction.md` (or extend `docs/13-runtime-setup.md`) with Person 5. Have an outside tester run cold from scratch on a fresh box; fix everything that breaks the cold run.

### Phase H — Submission
- Final repro-doc fixes from cold-tester feedback. Backup of the demo box. On-call for any submission-time sim issue.

## Ongoing (always-on)

- Redis infrastructure on the demo box.
- Cross-team integration testing — sim is the common substrate everyone hits.
- Standup gate-trajectory reports.

## Currently blocked on others

| Blocker | Owner | What unblocks me |
|---|---|---|
| Real xBD frames in `sim/fixtures/frames/` | Person 5 | Drop real JPEGs in place of placeholders (filenames preserved). |
| `drone_agent` consuming `drones.<id>.camera` + writing merged state | Person 2 | First end-to-end Gemma 4 run on my sim's frames. |
| `egs_agent` consuming `drones.<id>.findings`, issuing `drones.<id>.tasks` | Person 3 | Multi-drone replan exercise. |
| `ws_bridge` cutover from `dev_fake_producers.py` → real sim source | Person 4 | Dashboard renders my sim's live state. |

## Polish queue (unblocked, opportunistic)

All initial polish-queue items shipped on `feature/sim-polish`. Add new
items here as they surface during integration sessions or live-run fallout.

- _Empty — refill as needed._

### Follow-ups surfaced by the live run (low priority, out of Person 1 scope)

- `agents/drone_agent/main.py` ImportError on relative imports when run as a script (`python3 agents/drone_agent/main.py`). Ping Person 2.
- ~~`scripts/stop_demo.sh` shuts down Redis even when it didn't start it.~~ Shipped on `feature/sim-live-run-followups`, slice A.
