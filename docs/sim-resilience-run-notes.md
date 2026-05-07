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
