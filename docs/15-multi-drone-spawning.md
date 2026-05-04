# 15 — Multi-Drone Spawning

## Goal

Run 2-3 drone agent processes simultaneously, each subscribing to and publishing on the shared Redis broker. One waypoint runner and one frame server feed simulated state to all drone agents. One EGS process coordinates the swarm.

## Process Layout

For a 3-drone swarm, launch these processes (each in its own terminal or tmux pane):

| # | Process | Command |
|---|---|---|
| 1 | Redis broker | `redis-server` (or already running as a system service) |
| 2 | Waypoint runner | `python sim/waypoint_runner.py --scenario disaster_zone_v1` |
| 3 | Frame server | `python sim/frame_server.py --scenario disaster_zone_v1` |
| 4 | EGS agent | `python agents/egs_agent/main.py` |
| 5 | Drone agent 1 | `python agents/drone_agent/main.py --drone-id drone1` |
| 6 | Drone agent 2 | `python agents/drone_agent/main.py --drone-id drone2` |
| 7 | Drone agent 3 | `python agents/drone_agent/main.py --drone-id drone3` |
| 8 | Mesh simulator | `python agents/mesh_simulator/main.py` |
| 9 | WebSocket bridge | `python frontend/ws_bridge/main.py` |

**Waypoint runner** reads the scenario YAML and publishes `drones.<id>.state` (JSON, 2 Hz) for every drone listed in the scenario, with simulated position, heading, altitude, and battery decay.

**Frame server** reads the scenario's `frames` mapping and publishes `drones.<id>.camera` (raw JPEG bytes, not JSON) to Redis at the configured frame rate. Each drone agent subscribes to its own camera channel and passes frames to Gemma 4.

**Mesh simulator** pattern-subscribes to `swarm.broadcasts.*`, filters messages by Euclidean distance using live drone state, and republishes accepted messages to `swarm.<receiver_id>.visible_to.<receiver_id>`. See Contract 9 in `docs/20-integration-contracts.md` for the full channel registry.

**WebSocket bridge** subscribes to `egs.state`, `drones.*.state`, and `drones.*.findings`, then forwards a merged envelope to all connected Flutter dashboard clients at 1 Hz. Operator commands flow back through the same WebSocket.

## Launch Script

The shipped script is [`scripts/launch_swarm.sh`](../scripts/launch_swarm.sh). It starts the full stack in a tmux session — one window per process — and writes per-process logs to `/tmp/gemma_guardian_logs/<process>.log` (override with `GG_LOG_DIR`).

```bash
# default: 3-drone disaster_zone_v1 scenario; --drones=auto derives the roster
# from the scenario YAML's drones[].drone_id list (via sim/list_drones.py).
scripts/launch_swarm.sh

# pick a scenario; the roster automatically follows.
scripts/launch_swarm.sh single_drone_smoke

# pick a custom drone roster explicitly (must be a subset of scenario's drone_ids)
scripts/launch_swarm.sh disaster_zone_v1 --drones=drone1,drone2

# rehearse what would launch without actually starting tmux
scripts/launch_swarm.sh --dry-run

# self-terminate the sim runners after N seconds (CI / scripted demos).
# --duration is forwarded to sim/waypoint_runner.py and sim/frame_server.py
# only — drone agents and EGS do not accept it. run_full_demo.sh forwards
# every flag verbatim, so the same shape works there:
scripts/launch_swarm.sh disaster_zone_v1 --duration=30
scripts/run_full_demo.sh disaster_zone_v1 --duration=30
```

Behaviour notes worth knowing before you run it:

- **Missing-component tolerance.** The script guards every agent invocation with `[ -f <path> ]`. Components that haven't been built yet (e.g. `agents/drone_agent/main.py` in the early sim-only phase) are logged as `[skip]` rather than failing the launch. This is what lets Person 1 run sim + mesh end-to-end before Persons 2/3/4 ship.
- **Redis startup.** If `redis-cli ping` already responds, the script reuses the running broker. Otherwise it daemonizes its own `redis-server` and logs to `$LOG_DIR/redis.log`.
- **`--dry-run` and `GG_NO_TMUX=1`.** Both modes print `[plan] tmux:<window> :: <command>` lines instead of executing. Useful for CI verification — see `scripts/tests/test_launch_scripts.py`.

If you prefer `honcho` or `overmind` over tmux, define a `Procfile` at the repo root mirroring the same process list. The only constraint is that each process writes its stdout/stderr to its own log file under `/tmp/gemma_guardian_logs/`.

## Stopping

```bash
scripts/stop_demo.sh
```

The shipped script ([`scripts/stop_demo.sh`](../scripts/stop_demo.sh)) is **idempotent** — running it when nothing is up still exits 0. It kills the `fieldagent` tmux session, then sends SIGTERM to each named process by path (`sim/waypoint_runner.py`, `sim/frame_server.py`, `agents/mesh_simulator/main.py`, `agents/egs_agent/main.py`, `agents/drone_agent/main.py`, `frontend/ws_bridge/main.py`), then asks `redis-cli shutdown nosave` if any Redis is running. Each step is best-effort and tolerant of a no-op.

For a one-command run that launches the swarm, tails the waypoint log, and stops cleanly on Ctrl-C, use [`scripts/run_full_demo.sh`](../scripts/run_full_demo.sh) — it wraps `launch_swarm.sh` with a `trap` that calls `stop_demo.sh` on exit.

## Scaling 2 to 3 Drones

No new installs required. Two edits:

1. In `shared/config.yaml`, set `mission.drone_count: 3`.
2. In `sim/scenarios/disaster_zone_v1.yaml`, add the third drone under `drones:` with its `home`, `waypoints`, and `speed_mps`. Then add a `frame_mappings.<drone_id>` entry mapping `tick_range`s to JPEGs under `sim/fixtures/frames/`. See `sim/scenario.py` for the Pydantic schema.

Restart the swarm. The waypoint runner and frame server pick up the new drone automatically, and `--drones=auto` (the default) reads the new roster from the YAML. To launch a subset, pass `--drones=drone1,drone2` explicitly; the default `auto` always expands to the full scenario roster.

To drop back to 2 drones for the demo, edit `sim/scenarios/disaster_zone_v1.yaml` to remove the third drone, set `mission.drone_count: 2` in `shared/config.yaml`, and re-run `launch_swarm.sh` (the default `--drones=auto` picks up the new roster).

## Failure Modes

**Redis is down.** All pub/sub calls raise `redis.exceptions.ConnectionError`. Fix: confirm `redis-cli ping` returns PONG. If you used `--daemonize yes`, check `$LOG_DIR/redis.log`. Restart with `redis-server --daemonize yes`.

**Ollama is down or the model isn't pulled.** The drone agent and EGS agent fail on their first Gemma 4 call with a connection refused or 404. Fix: `ollama serve` in a separate terminal and confirm `ollama list` shows the pinned model tags from `docs/20-integration-contracts.md`. Pull if missing: `ollama pull gemma4:e2b`.

**Scenario YAML is malformed.** The waypoint runner exits immediately with a YAML parse error printed to stdout. Fix: validate the file with `python -c "import yaml, sys; yaml.safe_load(open(sys.argv[1]))" sim/scenarios/disaster_zone_v1.yaml`. Check indentation, missing colons, or non-ASCII characters in paths.

**Port conflict on 9090 (WebSocket bridge).** The FastAPI process fails to bind. Fix: `lsof -i :9090` to find the conflicting process, kill it, or override the port with `WS_BRIDGE_PORT=9091 python frontend/ws_bridge/main.py` and update the Flutter dashboard's WebSocket URL accordingly.

## Manual pilot — interactive drone-agent stand-in

When Person 2 is iterating on the real drone agent and you need a fast loop
to drive findings / broadcasts into a live sim by hand,
[`sim/manual_pilot.py`](../sim/manual_pilot.py) is the REPL.

Recipe:

```bash
# Pane 1 — sim with two drones running the resilience scenario (drone1 stays
# unattended so manual_pilot can take its seat).
scripts/launch_swarm.sh resilience_v1 --drones=drone2,drone3

# Pane 2 — REPL bound to drone1, talking to the same Redis broker.
uv run python sim/manual_pilot.py --drone-id drone1
```

Inside the REPL: `help` lists every command. `state` / `frame` / `peers`
inspect what the listener has cached from `drones.<id>.state`,
`drones.<id>.camera`, and `swarm.<id>.visible_to.<id>`. `finding ...` builds
a Contract 4 finding payload, validates it against `shared/schemas/finding.json`
(same loader the real validator uses), and publishes on
`drones.<id>.findings` on success. `broadcast ...` publishes a `task_complete`
broadcast on `swarm.broadcasts.<id>`. `explored / assist / rtb / continue`
build the matching `drone_function_calls.json` envelopes and validate them
without republishing — the agent contract has no canonical wire channel for
raw function calls.

The validation floor is JSON-Schema only. Semantic checks (battery actually
low, GPS-in-zone, duplicate-finding, severity↔confidence) live in
`agents/drone_agent/validation.py` and are Person 2's territory — see the
`SchemaValidationError` TODO in `sim/manual_pilot.py`.

`--frames-out-dir` (default `/tmp`) is where `frame` writes the latest JPEG
so you can open it in your viewer of choice; the saved file is named
`manual_pilot_<drone_id>.jpg`.

## Cross-References

- Dev environment setup: [`docs/13-runtime-setup.md`](13-runtime-setup.md)
- Scenario YAML format and disaster scene layout: [`docs/14-disaster-scene-design.md`](14-disaster-scene-design.md)
- Redis channel names and JSON schemas: [`docs/20-integration-contracts.md`](20-integration-contracts.md) Contract 9
- Function-call schemas the REPL emits: [`docs/09-function-calling-schema.md`](09-function-calling-schema.md)
