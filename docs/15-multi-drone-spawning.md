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

`scripts/launch_swarm.sh` starts the full stack in a tmux session, one pane per process. Each process logs to `/tmp/gemma_guardian_logs/<process>.log`.

```bash
#!/bin/bash
# scripts/launch_swarm.sh
# Requires: tmux, redis-server on PATH, python in .venv or system

set -e
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="/tmp/gemma_guardian_logs"
mkdir -p "$LOG_DIR"

SCENARIO="${1:-disaster_zone_v1}"

# Start redis-server only if not already running
if ! redis-cli ping > /dev/null 2>&1; then
  redis-server --daemonize yes --logfile "$LOG_DIR/redis.log"
  echo "Started redis-server"
else
  echo "redis-server already running — skipping"
fi

tmux new-session -d -s fieldagent -n waypoint
tmux send-keys -t fieldagent:waypoint \
  "cd $REPO_ROOT && python sim/waypoint_runner.py --scenario $SCENARIO 2>&1 | tee $LOG_DIR/waypoint_runner.log" Enter

tmux new-window -t fieldagent -n frames
tmux send-keys -t fieldagent:frames \
  "cd $REPO_ROOT && python sim/frame_server.py --scenario $SCENARIO 2>&1 | tee $LOG_DIR/frame_server.log" Enter

tmux new-window -t fieldagent -n egs
tmux send-keys -t fieldagent:egs \
  "cd $REPO_ROOT && python agents/egs_agent/main.py 2>&1 | tee $LOG_DIR/egs.log" Enter

# Launch one drone agent per ID in the scenario (default: drone1, drone2, drone3)
for ID in drone1 drone2 drone3; do
  tmux new-window -t fieldagent -n "$ID"
  tmux send-keys -t "fieldagent:$ID" \
    "cd $REPO_ROOT && python agents/drone_agent/main.py --drone-id $ID 2>&1 | tee $LOG_DIR/$ID.log" Enter
done

tmux new-window -t fieldagent -n mesh
tmux send-keys -t fieldagent:mesh \
  "cd $REPO_ROOT && python agents/mesh_simulator/main.py 2>&1 | tee $LOG_DIR/mesh.log" Enter

tmux new-window -t fieldagent -n ws_bridge
tmux send-keys -t fieldagent:ws_bridge \
  "cd $REPO_ROOT && python frontend/ws_bridge/main.py 2>&1 | tee $LOG_DIR/ws_bridge.log" Enter

echo ""
echo "FieldAgent swarm running in tmux session 'fieldagent'."
echo "Attach with: tmux attach -t fieldagent"
echo "Logs at: $LOG_DIR/"
echo "Flutter dashboard connects to: ws://localhost:9090"
```

If you prefer `honcho` or `overmind` over tmux, define a `Procfile` at the repo root mirroring the same process list. The only constraint is that each process writes its stdout/stderr to its own log file under `/tmp/gemma_guardian_logs/`.

## Stopping

```bash
# scripts/stop_demo.sh
#!/bin/bash
tmux kill-session -t fieldagent 2>/dev/null || true

# Kill any stray processes by name
pkill -f "waypoint_runner.py" || true
pkill -f "frame_server.py"    || true
pkill -f "egs_agent/main.py"  || true
pkill -f "drone_agent/main.py" || true
pkill -f "mesh_simulator"     || true
pkill -f "ws_bridge/main.py"  || true

# Only stop redis-server if we started it (don't kill a system service)
# Check whether it was launched by our user's daemonize call above:
if redis-cli config get daemonize 2>/dev/null | grep -q yes; then
  redis-cli shutdown nosave 2>/dev/null || true
fi

echo "FieldAgent stopped."
```

## Scaling 2 to 3 Drones

No new installs required. Two edits:

1. In `shared/config.yaml`, set `mission.drone_count: 3`.
2. In `sim/scenarios/disaster_zone_v1.yaml`, add the third drone's `home_position`, `waypoint_track`, and `frames` entries.

Restart the swarm. The waypoint runner and frame server auto-read `drone_count` from the scenario file; the extra `agents/drone_agent/main.py --drone-id drone3` process in the launch script is already present.

To drop back to 2 drones for the demo, set `mission.drone_count: 2` and remove or comment out the `drone3` pane from the launch script.

## Failure Modes

**Redis is down.** All pub/sub calls raise `redis.exceptions.ConnectionError`. Fix: confirm `redis-cli ping` returns PONG. If you used `--daemonize yes`, check `$LOG_DIR/redis.log`. Restart with `redis-server --daemonize yes`.

**Ollama is down or the model isn't pulled.** The drone agent and EGS agent fail on their first Gemma 4 call with a connection refused or 404. Fix: `ollama serve` in a separate terminal and confirm `ollama list` shows the pinned model tags from `docs/20-integration-contracts.md`. Pull if missing: `ollama pull gemma4:e2b`.

**Scenario YAML is malformed.** The waypoint runner exits immediately with a YAML parse error printed to stdout. Fix: validate the file with `python -c "import yaml, sys; yaml.safe_load(open(sys.argv[1]))" sim/scenarios/disaster_zone_v1.yaml`. Check indentation, missing colons, or non-ASCII characters in paths.

**Port conflict on 9090 (WebSocket bridge).** The FastAPI process fails to bind. Fix: `lsof -i :9090` to find the conflicting process, kill it, or override the port with `WS_BRIDGE_PORT=9091 python frontend/ws_bridge/main.py` and update the Flutter dashboard's WebSocket URL accordingly.

## Cross-References

- Dev environment setup: [`docs/13-runtime-setup.md`](13-runtime-setup.md)
- Scenario YAML format and disaster scene layout: [`docs/14-disaster-scene-design.md`](14-disaster-scene-design.md)
- Redis channel names and JSON schemas: [`docs/20-integration-contracts.md`](20-integration-contracts.md) Contract 9
