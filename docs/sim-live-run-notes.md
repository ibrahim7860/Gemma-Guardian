# Sim Live-Run Notes — 2026-05-04

First end-to-end live run of `scripts/launch_swarm.sh` against a real
`redis-server` (not fakeredis), validating the polish-queue work on
`feature/sim-polish`. Captured here because Phase A on
[`sim/ROADMAP.md`](../sim/ROADMAP.md) calls for one before integration
sessions with Persons 2/3/4.

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

### Sim + mesh (Person 1 surface)

All three Person 1 components started cleanly, published on the contract
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
   on every drone-agent window. Out of Person 1's scope (agent
   ownership = Person 2); flagged for them to fix at the next handoff.
3. **`stop_demo.sh` shuts down Redis even when it didn't start it.**
   The script unconditionally runs `redis-cli shutdown nosave` if any
   Redis is running. On boxes where Redis is a long-lived system
   service (Person 1's WSL2 setup uses `sudo service redis-server start`),
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
