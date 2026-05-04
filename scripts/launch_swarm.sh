#!/bin/bash
#
# launch_swarm.sh — start the full FieldAgent demo stack in a tmux session.
#
# Modeled on docs/15-multi-drone-spawning.md, this script tolerates missing
# agent processes so Person 1 (sim lead) can run a partial stack while
# Persons 2/3/4 are still building. Components that don't exist yet are
# logged as "skipping" rather than blocking the launch.
#
# Usage:
#   scripts/launch_swarm.sh [scenario] [--dry-run] [--drones=auto|drone1,drone2,...]
#
# --drones default is "auto" — the roster is derived from the scenario YAML's
# drones[].drone_id list via sim/list_drones.py. Pass --drones=drone1,drone2
# explicitly to launch a subset.
#
# Env overrides:
#   GG_NO_TMUX=1   — skip the actual tmux invocation; just print plans (used by --dry-run and tests)
#   GG_REDIS_URL   — defaults to redis://localhost:6379/0
#   GG_LOG_DIR     — defaults to /tmp/gemma_guardian_logs
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${GG_LOG_DIR:-/tmp/gemma_guardian_logs}"
REDIS_URL="${GG_REDIS_URL:-redis://localhost:6379/0}"

DRY_RUN=0
SCENARIO="disaster_zone_v1"
DRONES="auto"

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --drones=*) DRONES="${arg#--drones=}" ;;
    --*) echo "unknown flag: $arg" >&2; exit 2 ;;
    *)   SCENARIO="$arg" ;;
  esac
done

if [ "$DRONES" = "auto" ]; then
  if ! DRONES="$(PYTHONPATH="$REPO_ROOT" python3 "$REPO_ROOT/sim/list_drones.py" "$SCENARIO")"; then
    echo "[error] failed to derive drone roster from scenario '$SCENARIO'" >&2
    exit 1
  fi
fi

# Helper: in dry-run, just print the command. Else, send-keys into tmux.
emit() {
  local window="$1"; shift
  echo "[plan] tmux:${window} :: $*"
  if [ "$DRY_RUN" -eq 0 ] && [ "${GG_NO_TMUX:-0}" != "1" ]; then
    tmux new-window -t fieldagent -n "$window"
    tmux send-keys -t "fieldagent:${window}" "$*" Enter
  fi
}

emit_if_exists() {
  local window="$1"; local file="$2"; shift 2
  if [ -f "$REPO_ROOT/$file" ]; then
    emit "$window" "$@"
  else
    echo "[skip] ${window} — ${file} not present yet (waiting on team-mate)"
  fi
}

mkdir -p "$LOG_DIR"

# --- Redis -------------------------------------------------------------------
if [ "$DRY_RUN" -eq 1 ] || [ "${GG_NO_TMUX:-0}" = "1" ]; then
  echo "[plan] redis-server (or skip if already running)"
else
  if command -v redis-cli >/dev/null 2>&1 && redis-cli ping >/dev/null 2>&1; then
    echo "[ok] redis-server already running"
  elif command -v redis-server >/dev/null 2>&1; then
    redis-server --daemonize yes --logfile "$LOG_DIR/redis.log"
    echo "[ok] redis-server started, log: $LOG_DIR/redis.log"
  else
    echo "[error] redis-server not found on PATH" >&2
    exit 1
  fi
fi

# --- tmux session ------------------------------------------------------------
if [ "$DRY_RUN" -eq 0 ] && [ "${GG_NO_TMUX:-0}" != "1" ]; then
  if ! command -v tmux >/dev/null 2>&1; then
    echo "[error] tmux not on PATH; install or use --dry-run" >&2
    exit 1
  fi
  tmux kill-session -t fieldagent 2>/dev/null || true
  tmux new-session -d -s fieldagent -n waypoint
fi

# --- Sim components (Person 1 — always present) ------------------------------
emit waypoint "cd $REPO_ROOT && python3 sim/waypoint_runner.py --scenario $SCENARIO --redis-url $REDIS_URL 2>&1 | tee $LOG_DIR/waypoint_runner.log"
emit frames   "cd $REPO_ROOT && python3 sim/frame_server.py    --scenario $SCENARIO --redis-url $REDIS_URL 2>&1 | tee $LOG_DIR/frame_server.log"
emit_if_exists mesh "agents/mesh_simulator/main.py" \
  "cd $REPO_ROOT && python3 agents/mesh_simulator/main.py --redis-url $REDIS_URL 2>&1 | tee $LOG_DIR/mesh.log"

# --- EGS (Person 3) ----------------------------------------------------------
emit_if_exists egs "agents/egs_agent/main.py" \
  "cd $REPO_ROOT && python3 agents/egs_agent/main.py 2>&1 | tee $LOG_DIR/egs.log"

# --- Drone agents (Person 2) -------------------------------------------------
IFS=',' read -ra DRONE_ARRAY <<< "$DRONES"
for ID in "${DRONE_ARRAY[@]}"; do
  emit_if_exists "$ID" "agents/drone_agent/main.py" \
    "cd $REPO_ROOT && python3 agents/drone_agent/main.py --drone-id $ID 2>&1 | tee $LOG_DIR/$ID.log"
done

# --- WebSocket bridge (Person 4) ---------------------------------------------
emit_if_exists ws_bridge "frontend/ws_bridge/main.py" \
  "cd $REPO_ROOT && python3 frontend/ws_bridge/main.py 2>&1 | tee $LOG_DIR/ws_bridge.log"

if [ "$DRY_RUN" -eq 0 ] && [ "${GG_NO_TMUX:-0}" != "1" ]; then
  echo ""
  echo "FieldAgent swarm running in tmux session 'fieldagent'."
  echo "Attach with: tmux attach -t fieldagent"
  echo "Logs at: $LOG_DIR/"
  echo "Stop with: scripts/stop_demo.sh"
fi
