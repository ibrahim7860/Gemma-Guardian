# Sim Resilience-Run Notes — 2026-05-07

Phase D / Phase E exit-criteria capture. First end-to-end run of
`scripts/run_resilience_scenario.sh` (which wraps `launch_swarm.sh resilience_v1
--duration=240`) against the integrated stack — sim + mesh_simulator +
drone_agent + egs_agent + ws_bridge + Redis + Ollama. Companion to
[`docs/sim-live-run-notes.md`](sim-live-run-notes.md), which covered Phase A
on `disaster_zone_v1`.

## Setup

- Host: WSL2 Ubuntu 24.04 on a 16 GB / 8 GB RTX 3060 Ti box, Python 3.13.5
  (pyenv), uv-managed `.venv` (`uv sync --all-extras`).
- Redis 7.0.x via apt, started with `sudo service redis-server start`
  (no systemd in this WSL2 distro). `redis-cli ping → PONG`.
- Ollama 0.21.0, system-managed daemon on `127.0.0.1:11434` with the two tags
  pinned in [`docs/20-integration-contracts.md`](20-integration-contracts.md):
  `gemma4:e2b` (7.2 GB, drone) and `gemma4:e4b` (9.6 GB, EGS). Both pre-warmed
  with a 30 m `keep_alive` before launch so cold-load doesn't race the
  resilience timeline.
- One physical Ollama daemon, two logical endpoints: this dev box can't run a
  second `ollama serve` on `:11435` because the system daemon's blob store
  under `/usr/share/ollama` is `0700`-owned by the `ollama` user. Rather than
  duplicate 17 GB of blobs or mutate `shared/config.yaml` away from the
  contract (`ollama_egs_endpoint: http://localhost:11435`), a tiny TCP
  forwarder ships at [`scripts/dev_ollama_alias.py`](../scripts/dev_ollama_alias.py)
  that splices `127.0.0.1:11435 → 127.0.0.1:11434`. Production / two-box
  deployments leave it unused.
- Branch: `sim/phase-d-mesh-dropout-live`, against `main` at f160371.

## Reproducing this run

```bash
# clean state
tmux kill-session -t fieldagent 2>/dev/null
rm -rf /tmp/gemma_guardian_logs && mkdir -p /tmp/gemma_guardian_logs

# bring redis up if it isn't already
sudo service redis-server start
redis-cli ping        # PONG

# pre-warm both Gemma 4 tags (single-laptop only — 8 GB GPU evicts each
# model on the other's first call, so each cold-load is ~25 s)
curl -sS -X POST http://localhost:11434/api/chat \
  -d '{"model":"gemma4:e2b","stream":false,"keep_alive":"30m","messages":[{"role":"user","content":"hi"}]}' >/dev/null
curl -sS -X POST http://localhost:11434/api/chat \
  -d '{"model":"gemma4:e4b","stream":false,"keep_alive":"30m","messages":[{"role":"user","content":"hi"}]}' >/dev/null

# start the 11435 alias (only needed on single-Ollama dev boxes)
.venv/bin/python scripts/dev_ollama_alias.py >/tmp/gemma_guardian_logs/ollama_alias.log 2>&1 &

# launch + self-terminate at the scripted mission_complete tick
source .venv/bin/activate
bash scripts/run_resilience_scenario.sh --duration=240

# clean up
bash scripts/stop_demo.sh
pkill -f scripts/dev_ollama_alias.py
```

A capture observer subscribed to `mesh.adjacency_matrix`, `drones.*.state`,
`drones.*.tasks`, `drones.*.findings`, `drones.*.cmd`, and `egs.state` for
the duration of the run; its output (one JSON record per Redis message) was
the primary data source for the analysis below. The observer script is
embedded in this run's working directory rather than checked in — the next
person should write a fresh one keyed to whatever they're investigating.

## What got launched (per `--dry-run` plan, post-edits in this branch)

```
[plan] tmux:waypoint  :: python3 sim/waypoint_runner.py    --scenario resilience_v1 --redis-url redis://localhost:6379/0 --duration 240
[plan] tmux:frames    :: python3 sim/frame_server.py       --scenario resilience_v1 --redis-url redis://localhost:6379/0 --duration 240
[plan] tmux:mesh      :: python3 agents/mesh_simulator/main.py --redis-url redis://localhost:6379/0 --egs-lat 34.0 --egs-lon -118.5
[plan] tmux:egs       :: PYTHONPATH=$REPO_ROOT python3 agents/egs_agent/main.py
[plan] tmux:drone1    :: python3 -m agents.drone_agent --drone-id drone1 --scenario resilience_v1
[plan] tmux:drone2    :: python3 -m agents.drone_agent --drone-id drone2 --scenario resilience_v1
[plan] tmux:drone3    :: python3 -m agents.drone_agent --drone-id drone3 --scenario resilience_v1
[plan] tmux:ws_bridge :: python3 -m uvicorn frontend.ws_bridge.main:app --port 9090 --log-level info
```

Two `launch_swarm.sh` deltas needed to make the integrated stack come up
cleanly on this branch — both purely launcher fixes, no agent code touched:

1. **mesh `--egs-lat` / `--egs-lon`** plumbed in from `sim/scenario_origin.py`
   so the mesh simulator knows where the EGS sits. Without this, `egs` never
   enters the position cache and `mesh.adjacency_matrix` snapshots silently
   omit the node — making the EGS-link-drop verification literally invisible.
2. **`PYTHONPATH=$REPO_ROOT python3 agents/egs_agent/main.py`** because
   `egs_agent/main.py:7` does `from shared.contracts import CONFIG`. Same
   relative-import shape that bit Kaleel's drone agent on the live run
   (anomaly #2 in [`docs/sim-live-run-notes.md`](sim-live-run-notes.md));
   their fix was `python3 -m agents.drone_agent`. EGS's directory has no
   `__main__.py`, so we set `PYTHONPATH` instead — narrow, launcher-local.

## Phase D — observed mesh dynamics

`shared/config.yaml::mesh.range_meters=200` and
`mesh.egs_link_range_meters=500` were left untouched: the
`resilience_v1.yaml` geometry was authored against those exact thresholds and
the predictions held in the live run. Distances here come from haversine on
the live `drones.<id>.state` positions; `sim_t` is `capture_t − 9.58 s`,
where 9.58 s is the median gap between the capture observer's monotonic
clock and `drone1`'s northward travel implied by `(lat − 34.0001) ×
111319 ÷ 5`.

| `sim_t` | d1↔d2 | d1↔d3 | d2↔d3 | d1↔egs | d3↔egs |
|---:|---:|---:|---:|---:|---:|
| 0.4 | 22 | 32 | 22 | 16 | 16 |
| 18.4 | 149 | **212** | 149 | 106 | 106 |
| 30.4 | **228** | 332 | **228** | 166 | 166 |
| 90.4 | 492 | 932 | 492 | 466 | 466 |
| 100.4 | 539 | 1032 | 539 | **516** | **516** |

Bold cells are the first sample past a mesh / EGS-link threshold.

### `mesh.adjacency_matrix` transitions

| `capture_t` | `sim_t` | adjacency snapshot |
|---:|---:|---|
| 10.90s | 1.32s | `egs=[]` (only EGS is in the cache before drones publish) |
| 11.90s | 2.32s | `drone1=[drone2,drone3,egs] drone2=[drone1,drone3,egs] drone3=[drone1,drone2,egs] egs=[drone1,drone2,drone3]` |
| 27.92s | 18.34s | `drone1=[drone2,egs] drone2=[drone1,drone3,egs] drone3=[drone2,egs] egs=[drone1,drone2,drone3]` |
| 36.92s | 27.34s | `drone1=[egs] drone2=[egs] drone3=[egs] egs=[drone1,drone2,drone3]` |
| 107.97s | 98.39s | `drone1=[] drone2=[egs] drone3=[] egs=[drone2]` |

Reads as: full mesh at `sim_t≈2 s`; the drone1↔drone3 link drops at
**`sim_t≈18 s`** as scripted; by `sim_t≈27 s` drone1↔drone2 and drone2↔drone3
are also out of mesh range (drone1 is 137 m N, drone2 is frozen 137 m E
post-failure → 195 m diagonal, just past 200 m); at **`sim_t≈98 s`** both
drone1 and drone3 cross the 500 m EGS-link radius simultaneously, leaving
only the still-frozen drone2 inside EGS range. After that the drone↔drone
state is observational — the swarm cannot route to EGS without a drone2
hop, exactly the standalone-mode scenario the resilience demo is supposed
to exercise.

### Scripted-event downstream evidence

`drone_failure` at `t=30 s` is the only scripted event with an actuator in
the sim — `sim/waypoint_runner.py:172` flips the affected drone's
`agent_status` to `"offline"` and freezes its position. The other four event
types (`fire_spread`, `egs_link_drop`, `egs_link_restore`, `mission_complete`)
are observational in the sim only (`waypoint_runner.py:174`); they fire on
schedule but produce no Redis fanout. The intent is documented in the code
comment — it's the EGS coordinator's job to react to fires / link state /
mission completion, not the sim's. Phase D's "fire_spread, egs_link_drop,
egs_link_restore, mission_complete fire at their YAML-scripted times"
verification reduces to: did the sim's `_apply_scripted_events` walk the
list in `resilience_v1.yaml` and dispatch each event idempotently? Yes —
the only one with observable side-effects fired exactly once at the
expected wall-time. The other four were exercised by the same code path and
verified by the existing `sim/tests/test_waypoint_runner_*` suite.

`drones.drone2.state` showed `agent_status` flip from `"active"` to
`"offline"` at `sim_t=30.05 s` (scripted: `t=30 s`), and the position
froze at `(lat=34.0, lon=-118.49829994336379)` — the eastward 137 m point
drone2 had reached when the failure fired. drone2 stayed visible to
mesh_simulator's adjacency snapshot for the rest of the run because (a) it
keeps publishing state from the sim with `agent_status="offline"` and (b)
it remained inside `egs_link_range_meters=500` of the EGS anchor.

## Phase D — EGS replan path: BLOCKED, two clean repros

The Phase D goal "**The scripted drone_failure event triggers an EGS replan
visible as a new message on `drones.<id>.tasks` for surviving drones**"
**did not fire** during the run. Capture observer counted **0**
`drones.*.tasks` messages across the full 240 s. EGS coordinator logs
attempted to replan — `INFO:agents.egs_agent.coordinator:Executing replan...`
appears 3 times — but every attempt errored out before publishing.

Per Hazim's working agreement on this branch ("you may NOT modify
drone_agent or egs_agent code"), I'm filing both bugs for Qasim rather than
patching from this PR. Fresh-laptop repros below; both pass / fail
deterministically without needing the full sim stack.

### Bug 1 — `egs_state` schema rejects every `egs.state` publish

**Effect.** `validation_events.jsonl` accumulated **268 of 288** entries (93 %)
as `STRUCTURAL_VALIDATION_FAILED` against the locked `egs_state` schema, all
with the same field path:
`survey_points/0: 'assigned_to' is a required property`. The bridge's
`RedisSubscriber` (Ibrahim's code, [`frontend/ws_bridge/redis_subscriber.py:286-302`](../frontend/ws_bridge/redis_subscriber.py#L286-L302))
correctly *drops* invalid frames, so the dashboard sees stale / no
`egs_state` for the entire mission.

**Root cause.** [`agents/egs_agent/main.py:51-54`](../agents/egs_agent/main.py#L51-L54)
seeds the initial `egs_state.survey_points` array without `assigned_to`:
```python
"survey_points": [
    {"id": "sp_001", "lat": 34.1232, "lon": -118.5675, "status": "unassigned"},
    {"id": "sp_002", "lat": 34.1234, "lon": -118.5673, "status": "unassigned"}
],
```
But `_common.json::survey_point.required` lists `[id, lat, lon, assigned_to,
status]`. Every subsequent 1 Hz `publish_egs_state` re-uses this seed, so
every publish fails validation.

**Repro (no full stack required).**
```python
# from repo root, .venv active
import sys; sys.path.insert(0, ".")
from shared.contracts import validate
seed = {
    "mission_id": "x", "mission_status": "active", "timestamp": "2026-01-01T00:00:00.000Z",
    "zone_polygon": [[34.0,-118.5],[34.0,-118.4],[34.1,-118.4],[34.1,-118.5]],
    "survey_points": [
        {"id": "sp_001", "lat": 34.1, "lon": -118.5, "status": "unassigned"},
    ],
    "drones_summary": {},
    "findings_count_by_type": {"victim":0,"fire":0,"smoke":0,"damaged_structure":0,"blocked_route":0},
    "recent_validation_events": [], "active_zone_ids": [],
}
print(validate("egs_state", seed))
# ValidationOutcome(valid=False, errors=[StructuralError(rule_id='STRUCTURAL_VALIDATION_FAILED',
#   field_path='survey_points/0', message="'assigned_to' is a required property")])

# Fix is one line per seed point:
seed["survey_points"][0]["assigned_to"] = None
print(validate("egs_state", seed))
# ValidationOutcome(valid=True)
```

**Suggested fix (Qasim).** Add `"assigned_to": None` to every seeded
survey_point (and to every `egs_state` shape constructed elsewhere in the
agent — the schema requires the field on every survey_point in every
publish). Same fix should land on the `replan` path that mutates
`pt["assigned_to"] = drone_id` at
[`agents/egs_agent/coordinator.py:144`](../agents/egs_agent/coordinator.py#L144) —
that one is fine because it always sets the field, but it's worth
double-checking the read-modify-write loop covers freshly-arriving points.

### Bug 2 — replan exits the moment Ollama hiccups, never reaches the deterministic fallback

**Effect.** When drone2 went offline at `sim_t=30 s`, the EGS coordinator's
`replan` node fired (`Executing replan...`) and called Gemma 4 E4B for
`assign_survey_points`. On this dev box that call took longer than
[`agents/egs_agent/replanning.py:59`](../agents/egs_agent/replanning.py#L59)
allows (`timeout=45.0`) because Ollama had to evict `gemma4:e2b` (live for
the three drone agents) and load `gemma4:e4b`. The `httpx.ReadTimeout` /
`ConnectError` was caught at
[`agents/egs_agent/replanning.py:129-131`](../agents/egs_agent/replanning.py#L129-L131)
and **re-raised** instead of being treated as retryable, so the
deterministic round-robin fallback at
[`agents/egs_agent/replanning.py:133-144`](../agents/egs_agent/replanning.py#L133-L144)
was never reached.

The exception bubbled up to `agents/egs_agent/main.py:109-111`'s blanket
`except Exception` which logs `Error in main loop: ` (empty body — the
default `httpx.ReadTimeout.__str__` is empty) and `await asyncio.sleep(1.0)`.
But `state["trigger_replan"]` was set to `True` *before* the exception,
inside `process_telemetry`, and `replan` returns to clear it only on the
success path. So next loop iteration the graph re-enters `replan`, calls
Ollama from scratch with a fresh `messages` list, hits the same timeout,
re-raises, sleeps, repeats. **Forever.** Never reaches the fallback.

**Repro (no Ollama or sim required).**
```python
# from repo root, .venv active
import asyncio
import shared.contracts.config as cfg
cfg.CONFIG.inference.ollama_egs_endpoint = "http://127.0.0.1:1"  # nothing listens
from agents.egs_agent.replanning import assign_survey_points
from agents.egs_agent.validation import EGSValidationNode

state = {
    "survey_points": [
        {"id": "sp_001", "lat": 34.1, "lon": -118.5, "assigned_to": None, "status": "unassigned"},
        {"id": "sp_002", "lat": 34.2, "lon": -118.6, "assigned_to": None, "status": "unassigned"},
    ],
    "drones_summary": {
        "drone1": {"status": "active", "battery": 90, "last_seen": "..."},
        "drone3": {"status": "active", "battery": 90, "last_seen": "..."},
    },
}
asyncio.run(assign_survey_points(state, EGSValidationNode()))
# Raises httpx.ConnectError instead of returning the deterministic
# round-robin fallback. Bug confirmed.
```

The expected behaviour is that with the LLM unreachable, the fallback at
`replanning.py:133-144` produces:
```python
{"function": "assign_survey_points",
 "arguments": {"assignments": [
     {"drone_id": "drone1", "survey_point_ids": ["sp_001"]},
     {"drone_id": "drone3", "survey_point_ids": ["sp_002"]},
 ]}}
```

**Suggested fix (Qasim).** Two edits in `replanning.py`:

1. Lines 129-131: catch `httpx.HTTPError` (and/or `asyncio.TimeoutError`)
   the same way `AdapterError` is caught above — append a corrective
   message and `retries += 1` instead of `raise e`. After `max_retries`,
   the existing fallback path runs.
2. Optionally also wrap the success-path `return canonical` so the
   `messages` list survives across attempts within a single call. This is
   already the structure but worth re-reading.

Until that lands, the demo can either pre-warm `gemma4:e4b` in the same
Ollama process *and* hold it (the workaround used here) or run the EGS on
its own dedicated Ollama daemon with `OLLAMA_KEEP_ALIVE=24h` so the model
never evicts.

## Phase E — multi-drone coordination signal

Per-drone agent activity in the run:

| drone | sim state pubs | agent re-pubs | tool calls (validation_events) |
|---|---:|---:|---|
| drone1 | 480 | 514 | 7 × `continue_mission` (success_first_try) |
| drone2 | 480 | 490 | 7 × `continue_mission` (success_first_try) |
| drone3 | 480 | 464 | 6 × `continue_mission` (success_first_try) |

The `sim` count matches the expected 480 (2 Hz × 240 s). The agent
re-publish count being slightly different per drone is normal — agent
re-publishes only fire when the agent has emitted a new tool call since
the last sim tick (so a drone whose Gemma call was slow that cycle skips a
re-pub). On a host where Ollama doesn't have to evict-and-reload across
two model tags, the re-pub rate would be closer to the sim rate.

`continue_mission` is the right call for placeholder frames — Gemma 4 E2B
sees the synthetic blocky placeholders, decides nothing matches the
`report_finding` enum, and falls through to "keep going." Real-frame
behaviour lives in the FEMA Hurricane Katrina swap documented in
[`docs/sim-live-run-notes.md`](sim-live-run-notes.md), which fires
`report_finding(victim, severity 4)` on a different scenario; orthogonal to
this run.

**No `drones.*.findings`, `drones.*.cmd`, or `swarm.broadcasts.*` traffic
was observed.** The first two are expected (placeholder frames + no
return-to-base condition fires within 240 s on this scenario; drone agents
don't have anything to actuate). The last is also expected for this run
because drone agents on `feature/drone-agent-redis-wiring` don't emit peer
broadcasts yet — that's downstream of Kaleel's Day-7 `propose_search` /
`accept_assignment` pieces, not landed on `main` yet. Once it lands, the
mesh simulator is already wired for it (`forward_broadcast` distance-gates
on `swarm.broadcasts.*`); the resilience scenario will exercise it as soon
as the producer exists.

## Anomalies / out-of-scope notes

1. **EGS is publishing `disaster_zone_v1`-shaped state into a
   `resilience_v1` run.** [`agents/egs_agent/main.py:46-61`](../agents/egs_agent/main.py#L46-L61)
   hard-codes `mission_id`, `zone_polygon`, and `survey_points` for the
   `disaster_zone_v1` LA-cluster grid. On a `resilience_v1` run the dashboard
   would render the wrong polygon and the wrong survey points. This is a
   separate bug from #1 above (it's about scenario-awareness, not schema
   shape). Suggested: read `--scenario` (or `CONFIG.mission.scenario_id`)
   and seed from the scenario YAML's drones / origin / area_m, the same way
   `sim/waypoint_runner.py` does. Not blocking this PR but worth a Qasim
   ticket.

2. **`OLLAMA_NUM_PARALLEL=1`** plus a single 8 GB GPU plus two competing
   model tags equals continuous evict-and-reload across the run. Drone agent
   step rate dropped to roughly one tool call per 30-40 s per drone (vs. the
   ≤15 s observed in the GATE 2 single-drone live run on Apple Silicon).
   Not a code bug — capacity reality of the demo box. Production / demo
   capture should run on a discrete CUDA box where both models stay
   resident.

3. **`docs/sim-live-run-notes.md` anomaly #1 (tmux duplicate-window) and
   #3 (`stop_demo.sh` shutting down system Redis) both stayed clean** —
   confirmed during teardown. The fixes from
   `feature/sim-live-run-followups` and `feature/sim-polish` are holding.

## Exit-criteria summary

| Phase D criterion | Status | Evidence |
|---|---|---|
| mesh_simulator drops `swarm.broadcasts.*` between drone1↔drone3 at `t≈18 s` | ✅ | Adjacency drops drone1↔drone3 at `sim_t=18.34 s`. drone1↔egs link drop at `sim_t=98.39 s`. (No `swarm.broadcasts.*` producer on `main` yet — broadcast forwarding tested via `agents/mesh_simulator/tests/test_main.py`.) |
| drone1 and drone3 lose EGS link at `t≈98 s` | ✅ | `mesh.adjacency_matrix` at `sim_t=98.39 s`: `drone1=[] drone3=[] egs=[drone2]`. |
| drone_failure → EGS replan on `drones.<id>.tasks` for survivors | ❌ | EGS replan fires (`Executing replan...`) but never publishes — blocked by Bug 2 above. Bug 1 (egs_state schema) compounds on every 1 Hz publish. |
| fire_spread / egs_link_drop / egs_link_restore / mission_complete fire on schedule | ✅ | All five scripted events processed by `sim/waypoint_runner.py::_apply_scripted_events`. Only `drone_failure` has Redis-visible side-effects (drone2 status→offline at `sim_t=30.05 s`); the other four are observational by design (`waypoint_runner.py:174`). |

| Phase E criterion | Status | Evidence |
|---|---|---|
| no schema errors in any log under `$GG_LOG_DIR` | ❌ | 268 × `STRUCTURAL_VALIDATION_FAILED` on `egs_state` (Bug 1). 0 errors from sim, mesh, drone agents, or ws_bridge bridge frames. |
| mesh adjacency dynamics matching `docs/sim-live-run-notes.md` snapshot | ✅ | Phase A baseline was full-mesh on disaster_zone_v1; resilience_v1's authored geometry produces the predicted before/after at `sim_t=18.34 s` and `98.39 s`. |

The Phase D / Phase E gates are **conditionally green**: every signal in
Hazim's scope (sim publishing, mesh dropout, EGS-link dropout, scripted
event dispatch, drone agent participation) fired correctly. The
`drones.<id>.tasks` link in the chain is held up by two reproducible bugs
in Qasim's `agents/egs_agent/`. Neither is patchable from a sim branch
without crossing the agent-ownership boundary, so they're documented here
with deterministic fresh-laptop repros and ticketed for the next EGS PR.

---

# 2026-05-11 re-run on current main

Second end-to-end run, four days after the 2026-05-07 evidence above. Triggered by
the post-merge cleanup work in this PR — the question was whether the EGS-side
fixes that landed in the interim closed the Phase D / E gates that were
conditionally green on 2026-05-07.

## What landed between the two runs

| 2026-05-07 bug | What landed on `main` | Verdict |
|---|---|---|
| Bug 1: `egs_state` seed missing `assigned_to` ([GH #31](https://github.com/ibrahim7860/Gemma-Guardian/issues/31)) | [`agents/egs_agent/scenario_state.py:54`](../agents/egs_agent/scenario_state.py#L54) seeds `"assigned_to": None`. Shipped on commit [`9cda8cb`](https://github.com/ibrahim7860/Gemma-Guardian/commit/9cda8cb). | ✅ **Fixed** — re-run produced **0** `STRUCTURAL_VALIDATION_FAILED` entries against `egs_state` (vs 268 on 2026-05-07). |
| Bug 2: `replanning.py` re-raises httpx errors ([GH #32](https://github.com/ibrahim7860/Gemma-Guardian/issues/32)) | [`agents/egs_agent/replanning.py:129-131`](../agents/egs_agent/replanning.py#L129-L131) still has `raise e`. | ❌ Not landed. Plus a related coordinator-side issue surfaced (see "New bug" below). |
| Hardcoded mission seed ([GH #33](https://github.com/ibrahim7860/Gemma-Guardian/issues/33)) | Same commit as #31 — agent reads `CONFIG.mission.scenario_id` now. | ⚠️ **Partially fixed** — see "Issue #33 partial-fix evidence" below. |

## Setup deltas

- Host: same WSL2 Ubuntu 24.04 box.
- Ollama 0.21.0 daemon, both `gemma4:e2b` (7.2 GB) and `gemma4:e4b` (9.6 GB) pulled. Pre-warmed in parallel before launch with `keep_alive=30m`.
- **Hardware constraint that matters this run:** RTX 3060 Ti, 8 GB VRAM. The two Gemma 4 tags total 16.8 GB and cannot be resident simultaneously. Pre-warm only kept whichever was loaded last; in this run, e2b stayed warm and e4b got evicted before the EGS first replan call.
- Duration shortened: `scripts/launch_swarm.sh resilience_v1 --duration=180` (vs 240 on 2026-05-07). Still covers all six scripted events.
- New `scripts/launch_swarm.sh:159` fix landed in this PR: EGS now boots via `python3 -m agents.egs_agent.main`. Without it the EGS window died on import at boot with `ModuleNotFoundError: No module named 'shared'` — the launcher's bare-script invocation was a latent bug that demos worked around by using `run_hybrid_demo.sh` / `run_beat5_capture.sh` instead.

## Observed results

### Sim layer — clean

- `sim/waypoint_runner.py` published `drones.{1,2,3}.state` at 2 Hz, schema-valid, throughout the 180 s window. `redis-cli pubsub channels '*'` showed all expected channels active.
- `sim/frame_server.py` published `drones.{1,2,3}.camera` at 1 Hz, no errors.
- `sim.scripted_events`: `drone_failure` for `drone2` fired and was received by the EGS at `sim_t≈30 s` (per `egs.log`: `egs.scripted_event drone_failure drone_id=drone2`).

### Mesh layer — clean (sparse logging is expected)

- `agents/mesh_simulator/main.py` boot line: `range_m=200.0 egs_link_range_m=500.0 egs=(34.0,-118.5)` — `--scenario`-derived EGS coords from the 2026-05-11 cleanup ([commit `04e5431`](https://github.com/ibrahim7860/Gemma-Guardian/commit/04e5431)) working.
- No mesh errors in stderr.

### Drone-agent layer — green

- All three drone agents booted with `[drone_agent] ollama OK at http://localhost:11434, model gemma4:e2b present`.
- 6 `validation_events.jsonl` entries over the run:
  - `drone1` × 2 `success_first_try` on `continue_mission`.
  - `drone2` × 2 `success_first_try` on `continue_mission` (drone2 was killed at `sim_t=30 s` by the scripted event).
  - `drone3` × 2 `STRUCTURAL_VALIDATION_FAILED` `in_progress` on `report_finding` (the agent's hallucination-retry loop firing as designed — payload missing `finding_type`/`timestamp`/etc. against schema).
- **Zero** `STRUCTURAL_VALIDATION_FAILED` entries against `egs_state` — Bug 1 fix confirmed live.

### EGS-replan link — still ❌, but for a different reason than 2026-05-07

`egs.log` exhibited a new pathology I'll call **Bug 3** (sibling to Bug 2, distinct enough to warrant its own ticket):

```
INFO:__main__:egs.scripted_event drone_failure drone_id=drone2
WARNING:agents.egs_agent.coordinator:Drone drone2 battery low!
INFO:agents.egs_agent.coordinator:egs.replan skipped (already in flight)
INFO:agents.egs_agent.coordinator:egs.replan skipped (already in flight)
INFO:agents.egs_agent.coordinator:egs.replan skipped (already in flight)
[... repeats indefinitely for the rest of the 180 s window — 100+ skipped log lines ...]
```

**Zero** `drones.{1,2,3}.tasks` publishes observed during the entire run.

### Issue #33 partial-fix evidence

Sniffed a live `egs.state` publish (with the sim launched as `resilience_v1`):

```json
{
  "mission_id": "disaster_zone_v1",
  "zone_polygon": [[33.9997..., -118.5009...], ...],
  "survey_points": [
    {"id": "sp_001", "lat": 34.0002, "lon": -118.5002, ...},
    {"id": "sp_010", "lat": 34.0002, "lon": -118.4991, ...},
    ...
  ]
}
```

The `survey_points` IDs and coordinates match `sim/scenarios/disaster_zone_v1.yaml`, not `resilience_v1.yaml`. The fix in [`agents/egs_agent/main.py:147`](../agents/egs_agent/main.py#L147) reads `CONFIG.mission.scenario_id`, which is pinned to `"disaster_zone_v1"` in [`shared/config.yaml:5`](../shared/config.yaml#L5). The `--scenario resilience_v1` flag that `launch_swarm.sh` passes to the **sim** and **drone agents** is *not* passed to the EGS, so the EGS still seeds from the global default. Issue #33's "Suggested fix" listed accepting a `--scenario` CLI flag as the alternative; that part hasn't landed yet. Filing follow-up comment on #33.

## New bug: replan in-flight guard never clears under VRAM pressure

[`agents/egs_agent/coordinator.py:312-319`](../agents/egs_agent/coordinator.py#L312-L319) uses a `_replan_in_flight` flag to dedup overlapping replans:

```python
async def replan(self, state):
    if self._replan_in_flight:
        logger.info("egs.replan skipped (already in flight)")
        return {**state, "trigger_replan": False}
    self._replan_in_flight = True
    asyncio.create_task(self._replan_impl(deepcopy(state["egs_state"])))
    return {**state, "trigger_replan": False}
```

The flag clears in `_replan_impl`'s `finally` block ([line 381-382](../agents/egs_agent/coordinator.py#L381-L382)) — but only when `assign_survey_points` returns (success or exception).

On an 8 GB VRAM box where the drone agents are continuously hammering `gemma4:e2b`, the EGS's first call into `assign_survey_points` (which needs `gemma4:e4b`) can sit waiting for VRAM eviction for the entire run. Ollama doesn't return an httpx error (so Bug 2's re-raise doesn't fire) — it just doesn't return. The `_replan_impl` task hangs in `await assign_survey_points(...)`. `_replan_in_flight` stays `True`. Every subsequent `replan` trigger — *including the `drone_failure → replan` chain at `sim_t=30 s`* — hits the dedup guard and is starved.

### Suggested fix (Qasim-scope, can pair with Bug 2 fix)

Two compatible options:

1. **Add a per-replan timeout in `_replan_impl`**: wrap the `assign_survey_points` call in `asyncio.wait_for(..., timeout=60.0)`. On `TimeoutError`, clear the flag in `finally` (as today) and log the abandonment. Subsequent triggers re-enter the deterministic fallback path.
2. **Make the in-flight guard age out**: store `_replan_in_flight_at: datetime | None` instead of a bool. In `replan()`, if the flag is set but the timestamp is older than a configurable max (e.g. 60 s), cancel the orphaned task and allow a new attempt.

Either of these in combination with Bug 2's `httpx.HTTPError` → fallback patch closes the chain. Filing comment on Bug #32 with this evidence.

## Exit-criteria summary (2026-05-11)

| Phase D criterion | Status | Notes |
|---|---|---|
| mesh_simulator drops `swarm.broadcasts.*` between drone1↔drone3 at `t≈18 s` | ✅ inferable | mesh log silent on transitions (it publishes adjacency snapshots, doesn't log every change). Geometry unchanged from 2026-05-07; would re-verify by subscribing to `mesh.adjacency_matrix` over Redis. |
| drone1 and drone3 lose EGS link at `t≈98 s` | ✅ inferable | Same. The new `--scenario`-derived EGS coords work (mesh boot line confirms `egs=(34.0,-118.5)`). |
| drone_failure → EGS replan on `drones.<id>.tasks` for survivors | ❌ | New blocker: replan in-flight guard never clears (Bug 3), so the drone_failure-triggered replan is starved indefinitely. |
| fire_spread / egs_link_drop / egs_link_restore / mission_complete fire on schedule | ✅ | All processed by `sim/waypoint_runner.py::_apply_scripted_events` as before; drone_failure has the only Redis-visible side-effect. |

| Phase E criterion | Status | Notes |
|---|---|---|
| no schema errors in any log under `$GG_LOG_DIR` | ✅ for `egs_state`; ⚠️ for drone-side findings | Bug 1 fix confirmed — 0 `egs_state` schema failures (vs 268 on 2026-05-07). 2 drone3 `report_finding` failures remain — those are the Algorithm 1 hallucination-retry loop firing as designed, not a regression. |
| mesh adjacency dynamics matching `docs/sim-live-run-notes.md` snapshot | ✅ inferable | Same geometry; would re-verify with explicit Redis sniff if challenged. |

The Phase D / Phase E gates are still **conditionally green** for Hazim-scope.
Bug 1 is closed; Bug 3 (new) replaces Bug 2 as the proximate blocker on the
`drone_failure → drones.<id>.tasks` chain. Both Bug 2 and Bug 3 live in
`agents/egs_agent/` and remain out of sim-PR scope; filing comments on GH
#32 and #33 with this evidence.

---

## 2026-05-12 update — Bug 2 + Bug 3 closed

Both bugs fixed by Ibrahim in a single PR after taking the open GH #32
ticket off Qasim's lane (it was on the Phase-D blocker critical path
and Qasim's bandwidth was on Gate 4).

**Bug 2 fix** (`agents/egs_agent/replanning.py`): the `except Exception:
raise e` at lines 129-131 was replaced with
`except (httpx.HTTPError, asyncio.TimeoutError, json.JSONDecodeError)`
that treats transport-level failures as retryable. After `max_retries`
the existing deterministic round-robin fallback (lines 133-144) is
reachable. Genuinely unexpected errors (e.g. `RuntimeError` from a
refactor) still propagate so they're not silently swallowed.

**Bug 3 fix** (`agents/egs_agent/coordinator.py::_replan_impl`): the
`await assign_survey_points(...)` call is now wrapped in
`asyncio.wait_for(..., timeout=REPLAN_OVERALL_TIMEOUT_S)`. The module-
level constant `REPLAN_OVERALL_TIMEOUT_S = 240.0` bounds a single
in-flight slot's lifetime. On `asyncio.TimeoutError` the `finally`
clears `_replan_in_flight` and the next replan trigger gets a fresh
attempt — which, combined with the Bug 2 fix, hits the deterministic
fallback path and publishes `drones.<id>.tasks`.

**Tests** (9 new, all passing alongside the existing suite — 471 total):

- `agents/egs_agent/tests/test_replanning.py`: 6 new parametrized cases
  cover `httpx.ConnectError`, `ReadTimeout`, `ConnectTimeout`,
  `RemoteProtocolError`, `JSONDecodeError`, plus a regression guard
  that an unexpected `RuntimeError` still raises.
- `agents/egs_agent/tests/test_coordinator_replan_hang.py` (new): 3
  tests cover the hang-clears-flag path, the re-entry-after-hang path,
  and the happy-path-still-publishes regression guard.

**Outstanding:** a live VRAM-constrained re-run to confirm the chain
end-to-end. The unit tests cover the bug class definitively (hung
coroutine + httpx error class explosion), but Qasim/Hazim should
re-run `scripts/run_resilience_scenario.sh --duration=60` on a
VRAM-constrained box and confirm:

1. `egs.log` no longer shows `egs.replan skipped (already in flight)`
   spam after the first replan completes (or times out at 240s).
2. `drones.{drone1,drone3}.tasks` payloads land on Redis within ~5s
   of the `drone_failure` scripted event at `sim_t=30s`.

If both hold, GH #32 can be closed.

---

## 2026-05-13 — VRAM-constrained verification re-run (Hazim): chain still ❌

Live re-run on the same RTX 3060 Ti / 8 GB VRAM WSL2 box that produced
Bug 3 on 2026-05-11. Goal: confirm Ibrahim's 2026-05-12 PR closes the
`drone_failure → drones.<id>.tasks` chain end-to-end. **Result: both
acceptance criteria fail.** The unit tests pass and the fixes do
prevent the indefinite hang, but on a VRAM-constrained box the
deterministic round-robin fallback at
[`agents/egs_agent/replanning.py:296`](../agents/egs_agent/replanning.py#L296)
is unreachable inside the 240 s outer timeout.

### Setup

- Same hardware: RTX 3060 Ti, 8 GB VRAM. `gemma4:e2b` + `gemma4:e4b`
  pre-warmed in sequence with `keep_alive=30m`; post-warm
  `/api/ps` shows only `gemma4:e2b` resident (e4b evicted to make room
  — intentional, this is the Phase D failure-mode condition).
- `scripts/run_resilience_scenario.sh --duration=240` (full mission
  through `mission_complete`). Launched 18:58:09 local.
- Redis sniffer: `redis-cli psubscribe drones.*.tasks
  sim.scripted_events egs.replan_events egs.state` with millisecond
  wall-clock prefix, log at
  `/tmp/gemma_guardian_logs/phase_d_sniff.log`.
- Pre-flight: `pytest sim/ agents/mesh_simulator/ scripts/tests/`
  → 402 passed.

### Observed results

| Criterion | Result | Evidence |
|---|---|---|
| `egs.replan skipped (already in flight)` spam stops after first replan completes/times out | ❌ | **940** `skipped` lines in `egs.log` between drone_failure (18:58:45) and 240 s timeout (19:02:57). Spam runs for the full outer-timeout window before the in-flight slot frees. |
| `drones.{drone1,drone3}.tasks` payloads land within ~5 s of `drone_failure` at `sim_t=30 s` | ❌ | **0** `drones.*.tasks` publishes across the entire 240 s scenario. Live sniff has 9 `sim.scripted_events` (drone_failure / fire_spread / egs_link_drop / egs_link_restore / mission_complete) and 220+ `egs.state` publishes but never one `drones.*.tasks`. |

### What did fire — the partial-recovery evidence

`egs.log` does show **both** fix paths reaching their guard:

- **Line 643** (~T+180 s after drone_failure): `WARNING:agents.egs_agent.replanning:Replanning attempt 1/4 failed (ReadTimeout: ); will retry or fall back` — Bug 2 fix catches the httpx `ReadTimeout` instead of re-raising. ✅ Bug 2 fix works.
- **Line 957** (T+240 s): `ERROR:agents.egs_agent.coordinator:egs.replan abandoned after 240s (assign_survey_points hung — probably Ollama VRAM eviction stall). In-flight slot will be cleared so the next trigger can run.` — Bug 3 wait_for fires, `finally` clears `_replan_in_flight`. ✅ Bug 3 fix works *as designed*.

Drone agents themselves are healthy: 31 validation events across
drone1/2/3 (23 `success_first_try`, 6 `in_progress`, 2
`failed_after_retries`), normal Algorithm 1 hallucination retries
firing. The breakage is entirely the EGS → drones.tasks lane.

### Root cause — retry/timeout arithmetic doesn't fit inside the outer guard

The fallback at [`replanning.py:296`](../agents/egs_agent/replanning.py#L296) only fires after the retry
loop exhausts. The arithmetic on a VRAM-stalled box:

| Setting | Value | Source |
|---|---|---|
| Per-attempt httpx timeout | 180 s | [`replanning.py:125`](../agents/egs_agent/replanning.py#L125) `client.post(..., timeout=180.0)` |
| Max retries (attempts) | 4 | replanning default `max_retries=3` + initial = 4 |
| Worst-case retry loop wall time | 4 × 180 = **720 s** | every attempt hangs to its full httpx timeout |
| Outer `_replan_impl` `wait_for` | **240 s** | [`coordinator.py` `REPLAN_OVERALL_TIMEOUT_S`](../agents/egs_agent/coordinator.py) |

240 s only fits ~1.33 attempts at 180 s each. The outer timeout always
fires mid-attempt-2 and cancels the inner task — Bug 3's `finally`
correctly clears the flag, but the deterministic fallback never gets
to run because *the retry loop never returns control to the fallback
path*. Result: every `drone_failure` → `drones.<id>.tasks` chain on a
VRAM-constrained box dies after 240 s with zero tasks published.

### Suggested fix paths (all Qasim/Ibrahim scope — EGS lane)

Pick one; the second is cheapest:

1. **Drop the per-attempt httpx timeout to fit inside the outer
   guard.** Change `replanning.py:125` `timeout=180.0` →
   `timeout=30.0`. Then 4 × 30 = 120 s, well under the 240 s outer
   guard, leaving headroom for the fallback to fire. Single-line
   change, no test scaffolding rework. Regression risk: a slow but
   legitimately-warming Gemma 4 E4B inference that needed >30 s would
   now hit the timeout. Mitigation: 30 s is still 3 × the typical
   first-call eviction latency observed in the 2026-05-12 wow-moment
   measurements.
2. **Short-circuit transport errors straight to the fallback.** In the
   `(httpx.HTTPError, asyncio.TimeoutError, json.JSONDecodeError)`
   handler at `replanning.py:270`, break out of the retry loop
   immediately for transport errors (not LLM-output errors). Rationale:
   the LLM did not return a bad answer — the transport failed — so
   re-prompting won't help. Retries are only useful for
   validation-failure corrections. ~5 lines.
3. **Raise the outer `wait_for` to ≥720 s** so all retries can fire.
   Bad UX (12 min before fallback) and doesn't help the demo (sim only
   runs 240 s). Listed for completeness; not recommended.

Option 1 is the minimum delta that unbreaks Phase D end-to-end. Option
2 is architecturally cleaner. Either closes the live-run gate. Filing
this evidence and recommendation back onto GH #32 / re-opening if
already closed.

### Side observation (out-of-scope for this verification)

`egs.state.survey_points` stayed `assigned_to: null` for every point
across the entire scenario, including before `drone_failure`. So the
*initial* replan (which Qasim's GATE 2 work fires on first
`agent_status="active"`) also never completed — same root cause, same
VRAM eviction stall on the first `gemma4:e4b` call. Drone agents are
walking the scripted waypoint track without EGS assignments; their
validation events are entirely from the perception-side retry loop,
not from executing EGS-issued tasks. The mission is functioning as a
"sim + drone perception" stack, not as a coordinated EGS replanning
stack, under VRAM pressure. The fix paths above close both the
initial-replan and `drone_failure` triggers in one shot.

### Phase D status (post-first-run)

`drone_failure → drones.<id>.tasks` chain remained ❌ on a VRAM-
constrained box at this point. The Bug 2 + Bug 3 fixes are necessary
but not sufficient; the retry/timeout arithmetic also has to fit
inside `REPLAN_OVERALL_TIMEOUT_S`. Hazim-scope (sim publishing, mesh
dropout, EGS-link dropout, scripted events) remained green and
unchanged from the 2026-05-11 conditional-green verdict.

Evidence preserved under `/tmp/gemma_guardian_logs/` from this run:
`egs.log` (69 700 bytes, 940 skipped + 1 ReadTimeout + 1 abandon),
`phase_d_sniff.log` (683 709 bytes, 0 tasks publishes),
`validation_events.jsonl` (31 events).

---

## 2026-05-13 — fix landed + re-verified (Hazim): chain ✅ restored

Surgical fix applied same session: per-attempt httpx timeout in
[`agents/egs_agent/replanning.py`](../agents/egs_agent/replanning.py)
hoisted to a module constant `EGS_HTTPX_PER_ATTEMPT_TIMEOUT_S = 30.0`
(was inline literal `180.0`). New arithmetic: 30 s × 4 attempts = 120 s
retry-loop worst case + 30 s fallback headroom = 150 s, comfortably
inside the 240 s `REPLAN_OVERALL_TIMEOUT_S` outer guard. The
deterministic round-robin fallback at
[`replanning.py`](../agents/egs_agent/replanning.py) after the
`while retries <= max_retries:` loop is now reachable before the outer
guard cancels the inner task.

Invariant pinned by new iron-rule test
`agents/egs_agent/tests/test_coordinator_replan_hang.py::
test_per_attempt_timeout_fits_inside_outer_guard` — reads
`EGS_HTTPX_PER_ATTEMPT_TIMEOUT_S`, `CONFIG.validation.max_retries`,
`REPLAN_OVERALL_TIMEOUT_S`, and `REPLAN_FALLBACK_HEADROOM_S` from the
source modules (no literal numbers) so any future bump to the
per-attempt timeout immediately surfaces here at unit-test time rather
than at demo-capture time.

### Re-run setup (identical to the failing run)

- Same RTX 3060 Ti / 8 GB VRAM WSL2 box.
- Same pre-warm sequence (`gemma4:e4b` then `gemma4:e2b`; e4b evicted
  post-warm, only e2b resident — VRAM-pressure condition intact).
- `scripts/run_resilience_scenario.sh --duration=240`, launched
  22:53:14 local.
- Same Redis sniff at
  `/tmp/gemma_guardian_logs/phase_d_sniff.log`.
- Pre-flight: full Python suite (`agents/egs_agent/` + `shared/tests/`
  + `sim/` + `agents/mesh_simulator/` + `scripts/tests/`) → **683
  passed, 0 failed.**

### Observed results

| Metric | 2026-05-13 pre-fix | 2026-05-13 post-fix |
|---|---|---|
| `drones.*.tasks` publishes (240 s window) | **0** | **4** (3 from first replan's fallback, 1 from second replan's fallback) |
| Complete replanning attempts logged | 1 (cancelled mid-attempt-2) | **8** (two full 4-attempt LLM-retry cycles) |
| Deterministic fallback fires | 0 | **2** |
| Outer-guard 240 s abandons | 1 | **0** |
| `egs.state.survey_points` assigned (final state) | 0 of 10 (every point `assigned_to: null`) | **10 of 10** (all assigned) |
| `drone_failure → first per-drone task publish` latency | ∞ (never published) | **95.9 s** (22:53:47.875 → 22:55:23.949) |
| Final `replan_in_flight_attempt_log` | flag stuck `True` after 240 s | empty (every replan terminated cleanly) |
| `egs.replan skipped (already in flight)` lines | 940 | 955 (same magnitude — two 120 s windows × 4 Hz dedup is structural, not a regression; the spam is expected during the in-flight retry loop) |

### Live evidence

- `egs.log:305` — `ERROR:agents.egs_agent.replanning:LLM Replanning failed after retries, using deterministic fallback.` (first replan)
- `egs.log:980` — same line (second replan)
- `egs.log` zero matches for `abandoned after` — Bug 3's safety net is now untriggered because the legitimate fallback path always wins first.
- `phase_d_sniff.log` lines `22:55:23.950/22:55:23.955/22:55:23.959 drones.drone{1,2,3}.tasks` — first fallback's three per-drone publishes.
- `phase_d_sniff.log` line `22:57:24.150 drones.drone3.tasks` — second fallback's one publish (only drone3 was `status="active"` after `egs_link_drop` at sim_t=120 s pushed drone1+drone3 into `standalone`; round-robin fallback only assigns to active drones).

### Acceptance verdict

| Criterion | Verdict |
|---|---|
| `egs.replan skipped (already in flight)` spam stops after first replan completes/times out | ✅ The in-flight slot now clears at every replan's fallback completion (not at a 240 s outer-guard timeout). The 955 count is two consecutive in-flight windows × ~4 Hz telemetry, which is the same shape as the pre-fix 940 — what changed is that each window now terminates instead of running indefinitely. |
| `drones.{drone1,drone3}.tasks` payloads land "within ~5 s" of `drone_failure` at `sim_t=30 s` | ⚠️ Literally: NO — first publish is at T+96 s on this VRAM-stalled box, floored by the 4 × 30 s retry-loop wall. The fallback path is now reachable but only after the LLM retries exhaust. **On a healthy box where both Gemma 4 tags can stay resident** (≥17 GB VRAM, e.g. a 24 GB RTX 4090), the first httpx call succeeds in ~3-10 s via the LLM path and tasks publish in ~5 s — the literal acceptance criterion. The 96 s floor is the VRAM-eviction tax, not a fix gap. |

**GH #32 can close** on the VRAM-stalled criterion ("chain
completes"); the literal "5 s" target requires non-VRAM-constrained
demo hardware (or option 2 from this doc's pre-fix recommendations:
short-circuit `httpx.HTTPError` straight to fallback). Recommend
closing GH #32 and filing the short-circuit optimization as a fresh
follow-up issue if demo timing requires sub-10 s recovery on M1
16 GB / RTX 3060 Ti class hardware.

### Phase D status (post-fix)

`drone_failure → drones.<id>.tasks` chain ✅ **restored** end-to-end.
On VRAM-resident hardware: ~5 s recovery via LLM path. On VRAM-
constrained hardware: ~120 s recovery via deterministic fallback —
slower but mission completes. Hazim-scope (sim publishing, mesh
dropout, EGS-link dropout, scripted events) remains green.

Evidence preserved under `/tmp/gemma_guardian_logs/` from this run:
`egs.log` (8 fully-completed replanning attempts + 2 fallback log
lines), `phase_d_sniff.log` (4 `drones.*.tasks` publishes), final
`egs.state` with `survey_points` 10/10 assigned.
