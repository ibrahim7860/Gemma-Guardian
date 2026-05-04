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

## Phases ahead (in order, no dates)

### Phase A — Live multi-drone smoke
- Run `scripts/launch_swarm.sh disaster_zone_v1` against real Redis with a 2-drone roster, then a 3-drone roster. Confirm `drones.drone1.state`, `drones.drone2.state`, `drones.drone3.state` all stream cleanly, no cross-talk, no message collisions.
- Capture a sample run's logs under `/tmp/gemma_guardian_logs/` and skim for anomalies (latency drift, dropped publishes, schema-invalid payloads).

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

- Repo-root `README.md` is missing. CLAUDE.md target structure assumes one.
- `shared/config.yaml`'s `mission.drone_count` is set statically — sim could soft-assert it against the scenario YAML (and fail fast on mismatch).
- `sim/waypoint_runner.py` and `sim/frame_server.py` default `--redis-url` to `redis://localhost:6379/0` directly; could read `shared/config.yaml` `transport.redis_url` instead.
- `scripts/launch_swarm.sh` `--drones=` is hardcoded `drone1,drone2,drone3` by default; could derive from the scenario YAML's `drones[].drone_id` list.
- ~~`.github/workflows/sim-tests.yml` for CI on every push (pytest sim/ + agents/mesh_simulator/ + scripts/tests/).~~ Done as the `sim_mesh` job in `.github/workflows/test.yml` on `feature/uv-and-ci`.
- Add `--duration <seconds>` flag to runners so they self-terminate cleanly (useful for scripted demos and CI).
- Pydantic `Scenario` could cross-validate that scripted_events `drone_id` references exist in `drones[]`.
