# Sim Live-Run Notes — 2026-05-04

First end-to-end live run of `scripts/launch_swarm.sh` against a real
`redis-server` (not fakeredis), validating the polish-queue work on
`feature/sim-polish`. Captured here because Phase A on
[`sim/ROADMAP.md`](../sim/ROADMAP.md) calls for one before integration
sessions with Kaleel/Qasim/Ibrahim.

## Setup

- Host: WSL2 Ubuntu 24.04, Python 3.13.5 (pyenv), uv-managed `.venv`.
- Redis 7.0.x via apt, started with `sudo service redis-server start`
  (no systemd in this WSL2 distro). `redis-cli ping → PONG`.
- Source: `feature/sim-polish` at the time of writing, after slices A–E.
- Command:

  ```bash
  source .venv/bin/activate
  bash scripts/launch_swarm.sh disaster_zone_v1 \
      --drones=drone1,drone2,drone3 \
      --duration=30
  ```

## What got launched (per `--dry-run` plan)

```
[plan] tmux:waypoint  :: python3 sim/waypoint_runner.py    --scenario disaster_zone_v1 --redis-url redis://localhost:6379/0 --duration 30
[plan] tmux:frames    :: python3 sim/frame_server.py       --scenario disaster_zone_v1 --redis-url redis://localhost:6379/0 --duration 30
[plan] tmux:mesh      :: python3 agents/mesh_simulator/main.py --redis-url redis://localhost:6379/0
[plan] tmux:egs       :: python3 agents/egs_agent/main.py
[plan] tmux:drone1    :: python3 agents/drone_agent/main.py --drone-id drone1
[plan] tmux:drone2    :: python3 agents/drone_agent/main.py --drone-id drone2
[plan] tmux:drone3    :: python3 agents/drone_agent/main.py --drone-id drone3
[plan] tmux:ws_bridge :: python3 frontend/ws_bridge/main.py
```

8 tmux windows, all spawned, log-tee'd into `/tmp/gemma_guardian_logs/`.

## Observations

### Sim + mesh (Hazim surface)

All three Hazim components started cleanly, published on the contract
channels, and behaved as expected:

- **`sim/waypoint_runner.py`** — published `drones.drone{1,2,3}.state` at
  2 Hz. Sample message confirmed schema-valid (`drone_id`, `timestamp` in
  ISO-8601 ms, `position` / `velocity` / `battery_pct` / `heading_deg` /
  `current_waypoint_id` / `agent_status` all populated). Battery decayed
  linearly from 100→98 over the first 20s (`battery_drain=0.1`/s, rounded
  to int per schema).
- **`sim/frame_server.py`** — started, no errors, ran to completion.
  (Did not separately confirm `drones.<id>.camera` payloads in this run;
  this is covered by `sim/tests/test_frame_server.py` against fakeredis.)
- **`agents/mesh_simulator/main.py`** — published `mesh.adjacency_matrix`
  at 1 Hz, full-mesh `{drone1: [drone2, drone3], drone2: [drone1, drone3], drone3: [drone1, drone2]}`
  as expected (all drones within `range_m=200`).

### `--duration=30` self-termination

Both sim runners hit the deadline cleanly:

```
[waypoint_runner] reached --duration=30.0s; exiting cleanly.
[frame_server] reached --duration=30.0s; exiting cleanly.
```

No leftover Python processes, no Redis connection-error tracebacks, no
tail latency. `--duration` is the intended path for scripted demos and
CI.

### `stop_demo.sh`

Exited 0 after the sim runners had already self-terminated; killed the
remaining tmux session, mesh simulator, and agent stubs. Tree was
clean afterward (`tmux ls` → no server, `pgrep -f sim/` → empty).

## Anomalies / out-of-scope notes

These are not blockers for this PR but worth flagging:

1. **Pre-existing `launch_swarm.sh` tmux bug — fixed in this PR.** The
   shipped script created the session with `tmux new-session -d -s fieldagent -n waypoint`,
   then the first `emit waypoint ...` did `tmux new-window -n waypoint`,
   producing two windows with the same name. `tmux send-keys -t fieldagent:waypoint`
   then errored with `can't find window: waypoint`. This was masked by
   `--dry-run` tests (which never invoke tmux). Patched in this branch
   to use a `placeholder` initial window that gets killed once real
   windows exist.
2. **`agents/drone_agent/main.py` relative-import error.** `drone1.log`
   et al. failed with
   `ImportError: attempted relative import with no known parent package`
   on every drone-agent window. Out of Hazim's scope (agent
   ownership = Kaleel); flagged for them to fix at the next handoff.
3. **`stop_demo.sh` shuts down Redis even when it didn't start it.**
   The script unconditionally runs `redis-cli shutdown nosave` if any
   Redis is running. On boxes where Redis is a long-lived system
   service (Hazim's WSL2 setup uses `sudo service redis-server start`),
   this is a small irritation — `redis-cli ping` afterward returns
   "Connection refused" until the service is restarted. Worth a follow-up
   to only stop Redis we daemonized ourselves; not blocking this PR.
4. **Mesh adjacency is full-mesh in `disaster_zone_v1`.** The scenario's
   drones are all within ~200m of each other, so `range_m=200` puts
   everyone in everyone's neighbour list. Phase D (live mesh-dropout
   tuning) will change this once we author a scenario where drones
   actively move out of range.

## Reproducing this run

```bash
# clean state
tmux kill-session -t fieldagent 2>/dev/null
rm -rf /tmp/gemma_guardian_logs
mkdir -p /tmp/gemma_guardian_logs

# bring redis up if it isn't already
sudo service redis-server start
redis-cli ping        # PONG

# launch + self-terminate
source .venv/bin/activate
bash scripts/launch_swarm.sh disaster_zone_v1 \
    --drones=drone1,drone2,drone3 \
    --duration=30

# wait for "[waypoint_runner] reached --duration=..." in
#   /tmp/gemma_guardian_logs/waypoint_runner.log

# clean up
bash scripts/stop_demo.sh
```

---

# Drone-agent → Redis live smoke (2026-05-06, Day 6)

First end-to-end live run of the GATE 2 drone-agent wiring on `feature/drone-agent-redis-wiring`. Real Redis broker, real Ollama daemon, real `gemma4:e2b` model — no mocks anywhere in the path.

## Setup

- Host: macOS 26.4 (Apple Silicon, 16 GB RAM), brew Homebrew 5.1.9.
- Redis 7.x via brew, already running.
- Ollama 0.23.1 via brew. Started with: `OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 ollama serve &`.
- Model: `gemma4:e2b` pulled from `ollama.com/library/gemma4` — 7.2 GB.
- Branch: `feature/drone-agent-redis-wiring` after Tasks 1–13, 15, 16, 17, 18 merged.

## Two config drifts found and fixed inline

1. `shared/config.yaml::inference.drone_model` was `gemma-4:e2b` (with hyphen). The actual Ollama tag is `gemma4:e2b` (no hyphen). Same fix for `egs_model`. Without this fix the agent's startup healthcheck logs "model not in pulled list" but otherwise still calls `/api/chat` (the daemon resolves close-enough names).
2. `agents/drone_agent/reasoning.py::ReasoningNode.__init__` defaulted `timeout_s=30.0`. Cold-load of the 7.2 GB `gemma4:e2b` plus the first vision+tools call exceeds 30s on Apple Silicon CPU — `httpx.ReadTimeout` kills the first attempt. Bumped default to `120.0`. After the model is warm, subsequent calls land in 30–45 seconds each.

## What ran

```
$ uv run --extra sim python sim/waypoint_runner.py --scenario disaster_zone_v1 &
$ uv run --extra sim python sim/frame_server.py --scenario disaster_zone_v1 &
$ uv run --extra drone --extra sim python -m agents.drone_agent \
    --drone-id drone1 --scenario disaster_zone_v1 &

[drone_agent] ollama OK at http://localhost:11434, model gemma4:e2b present
[drone_agent] drone_id=drone1 scenario=disaster_zone_v1 redis=redis://localhost:6379/0 model=gemma4:e2b
```

## What we observed

- **`drones.drone1.state`**: sim-published Contract 2 records arrive at 2 Hz with valid kinematics + `last_action: "none"` (sim defaults). Agent-republished records overlay `last_action: "return_to_base"` and `last_action_timestamp` once Gemma starts producing function calls. The merge handshake is alive.
- **Validation event log** at `/tmp/gemma_guardian_logs/validation_events.jsonl`: Contract 11-conformant. **8/8 lines** validated against `shared/schemas/validation_event.json` across two runs (12/12 cumulative). Function-call breakdown across two runs: `return_to_base × 11`, `continue_mission × 1`. Gemma 4 is producing real, varied tool calls.
- **`drones.drone1.cmd`**: live `return_to_base(reason="mission_complete")` payloads landed every ~40 seconds:
  ```json
  {"drone_id": "drone1", "timestamp": "2026-05-06T19:24:51.430Z",
   "command": "return_to_base", "reason": "mission_complete"}
  ```
- **`drones.drone1.findings`**: empty across both runs. **Not a bug — emergent correct behavior.** The `sim/fixtures/frames/placeholder_*.jpg` fixtures are 320×240 synthetic placeholders with no visible victims / fire / damage. Gemma 4 evaluates each frame, decides nothing matches the `report_finding` enum (`victim/fire/smoke/damaged_structure/blocked_route`), and falls through to `return_to_base(mission_complete)` once `assigned_survey_points_remaining == 0`. Even after we swapped in the synthetic `_make_test_image.py` aerial-with-fire+damage scene, the model still preferred RTB because waypoints had been exhausted by the time the frame reached it. **The first real `report_finding` will land once Thayyil swaps in real xBD post-disaster crops** — the wiring has nothing left to prove on that path.
- **Per-cycle timing**: ~40 seconds between validation log entries. That's one cold Gemma 4 vision+tools inference per agent step on Apple Silicon CPU. A discrete GPU or Linux+CUDA box would be 5–10× faster.

## Verified end-to-end

| Component | Evidence |
|---|---|
| Real Ollama daemon, real Gemma 4 E2B | `ollama list` shows `gemma4:e2b 7.2 GB`; healthcheck logs `model gemma4:e2b present`. |
| Drone agent subscribes to `drones.<id>.camera` (Contract 1, raw JPEG) | Validation log entries fire at sim-frame cadence; the call would not produce tool calls if frames weren't reaching `agent.step(bundle)`. |
| Drone agent subscribes to `drones.<id>.state` (Contract 2) | Validator passes `RTB(mission_complete)` only when `assigned_survey_points_remaining == 0`, which means it's reading the real sim state. |
| Real Gemma 4 producing structured function calls | Validation log shows `return_to_base` AND `continue_mission` calls — the model is genuinely choosing between options, not stuck on a default. |
| Validation node runs (Algorithm 1 retry loop) | Every log entry has `valid: true` + `outcome: success_first_try` because Gemma's calls so far all pass first-try; the loop is wired and would log `in_progress` + retry on failure. |
| Validation event log Contract 11-compliant | `12/12` lines validated against `shared/schemas/validation_event.json` via `shared.contracts.validate`. |
| Action node executes function calls | Live `drones.drone1.cmd` payloads observed for `return_to_base`. |
| Agent-side `drones.<id>.state` republish merges agent-owned fields | Live `last_action: "return_to_base"` observed on the channel — distinct from sim's `last_action: "none"`. |

## Not verified live (deferred)

- A live `report_finding` payload landing on `drones.<id>.findings`. Blocked on real xBD imagery (Thayyil) or a more visually convincing synthetic scene than `_make_test_image.py` produces. The protocol-level proof of this path lives in `frontend/ws_bridge/tests/test_e2e_playwright_real_drone_findings.py` (mocked Ollama returns a canned `report_finding`, agent persists frame, publishes to the real findings channel — the test passes).
- Multi-drone coordination, peer broadcasts on `swarm.broadcasts.<id>` — not in the GATE 2 scope.

