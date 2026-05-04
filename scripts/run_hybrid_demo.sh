#!/bin/bash
#
# run_hybrid_demo.sh — bridge cutover hybrid mode launcher.
#
# Runs the real sim for drones.<id>.state and dev_fake_producers.py for the
# remaining channels (egs.state, drones.<id>.findings) until Qasim and
# Kaleel ship real publishers. Mirrors launch_swarm.sh's tmux style and
# DRY-RUN semantics.
#
# Usage:
#   scripts/run_hybrid_demo.sh [scenario] [flags]
#
# Flags:
#   --dry-run           Print the plan, do not start tmux.
#   --duration=N        Forwarded to sim runners (they self-terminate).
#                       Fake producers ignore --duration and must be killed
#                       via stop_demo.sh or tmux kill.
#   --no-fake-egs       Suppress the fake egs.state producer. Use this once
#                       Qasim's agents/egs_agent/main.py aligns zone_polygon
#                       to the scenario YAML.
#   --no-fake-findings  Suppress the per-drone fake findings producers. Use
#                       this once Kaleel's drone agent publishes to Redis.
#
# Scenario default: disaster_zone_v1.
#
# Env overrides:
#   GG_NO_TMUX=1   — skip tmux invocation; just print plans (used by tests)
#   GG_REDIS_URL   — defaults to redis://localhost:6379/0
#   GG_LOG_DIR     — defaults to /tmp/gemma_guardian_logs
#
# Migration path: edit a wrapper script (or pass the flag at the CLI) to
# add --no-fake-egs / --no-fake-findings as the real producers ship. No
# source edits to this file required, no risk of dangling fake processes.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${GG_LOG_DIR:-/tmp/gemma_guardian_logs}"
REDIS_URL="${GG_REDIS_URL:-redis://localhost:6379/0}"

DRY_RUN=0
SCENARIO="disaster_zone_v1"
DURATION=""
FAKE_EGS=1
FAKE_FINDINGS=1

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --duration=*) DURATION="${arg#--duration=}" ;;
    --no-fake-egs) FAKE_EGS=0 ;;
    --no-fake-findings) FAKE_FINDINGS=0 ;;
    --*) echo "unknown flag: $arg" >&2; exit 2 ;;
    *)   SCENARIO="$arg" ;;
  esac
done

DURATION_ARG=""
if [ -n "$DURATION" ]; then
  DURATION_ARG="--duration $DURATION"
fi

# Resolve drone roster from the scenario YAML.
if ! DRONES="$(PYTHONPATH="$REPO_ROOT" python3 "$REPO_ROOT/sim/list_drones.py" "$SCENARIO")"; then
  echo "[error] failed to derive drone roster from scenario '$SCENARIO'" >&2
  exit 1
fi

emit() {
  local window="$1"; shift
  echo "[plan] tmux:${window} :: $*"
  if [ "$DRY_RUN" -eq 0 ] && [ "${GG_NO_TMUX:-0}" != "1" ]; then
    tmux new-window -t hybrid_demo -n "$window"
    tmux send-keys -t "hybrid_demo:${window}" "$*" Enter
  fi
}

mkdir -p "$LOG_DIR"

# --- Redis (mirror of launch_swarm.sh's sentinel logic) --------------------
SENTINEL="$LOG_DIR/.gg_started_redis"
if [ "$DRY_RUN" -eq 1 ]; then
  echo "[plan] redis-server (or skip if already running)"
else
  if command -v redis-cli >/dev/null 2>&1 && redis-cli ping >/dev/null 2>&1; then
    echo "[ok] redis-server already running (will not be stopped by stop_demo.sh)"
    rm -f "$SENTINEL"
  elif command -v redis-server >/dev/null 2>&1; then
    redis-server --daemonize yes --logfile "$LOG_DIR/redis.log"
    : > "$SENTINEL"
    echo "[ok] redis-server started, log: $LOG_DIR/redis.log"
  else
    echo "[error] redis-server not found on PATH" >&2
    exit 1
  fi
fi

# --- tmux session ---------------------------------------------------------
if [ "$DRY_RUN" -eq 0 ] && [ "${GG_NO_TMUX:-0}" != "1" ]; then
  if ! command -v tmux >/dev/null 2>&1; then
    echo "[error] tmux not on PATH; install or use --dry-run" >&2
    exit 1
  fi
  tmux kill-session -t hybrid_demo 2>/dev/null || true
  tmux new-session -d -s hybrid_demo -n placeholder
fi

# --- Real sim (Hazim) — owns drones.<id>.state -----------------------------
emit waypoint "cd $REPO_ROOT && python3 sim/waypoint_runner.py --scenario $SCENARIO --redis-url $REDIS_URL $DURATION_ARG 2>&1 | tee $LOG_DIR/waypoint_runner.log"
emit frames   "cd $REPO_ROOT && python3 sim/frame_server.py    --scenario $SCENARIO --redis-url $REDIS_URL $DURATION_ARG 2>&1 | tee $LOG_DIR/frame_server.log"

# --- Fake EGS state (default ON; pass --no-fake-egs once Qasim ships) ----
if [ "$FAKE_EGS" -eq 1 ]; then
  emit egs_fake "cd $REPO_ROOT && python3 scripts/dev_fake_producers.py --emit=egs --redis-url $REDIS_URL 2>&1 | tee $LOG_DIR/egs_fake.log"
else
  echo "[skip] egs_fake — --no-fake-egs set (Qasim's EGS owns egs.state)"
fi

# --- Fake findings (default ON; pass --no-fake-findings once Kaleel ships) -
if [ "$FAKE_FINDINGS" -eq 1 ]; then
  IFS=',' read -ra DRONE_ARRAY <<< "$DRONES"
  for ID in "${DRONE_ARRAY[@]}"; do
    emit "findings_$ID" "cd $REPO_ROOT && python3 scripts/dev_fake_producers.py --emit=findings --drone-id $ID --redis-url $REDIS_URL 2>&1 | tee $LOG_DIR/findings_${ID}_fake.log"
  done
else
  echo "[skip] findings_* — --no-fake-findings set (drone agent owns drones.<id>.findings)"
fi

# --- WebSocket bridge (Ibrahim) -------------------------------------------
# Uvicorn is required: `python frontend/ws_bridge/main.py` only constructs the
# FastAPI app and exits (the module's `app = create_app()` returns immediately
# with no server attached). `launch_swarm.sh` has the same bug; flagged as a
# follow-up. The hybrid orchestrator gets the right invocation directly.
emit ws_bridge "cd $REPO_ROOT && python3 -m uvicorn frontend.ws_bridge.main:app --port 9090 --log-level info 2>&1 | tee $LOG_DIR/ws_bridge.log"

if [ "$DRY_RUN" -eq 0 ] && [ "${GG_NO_TMUX:-0}" != "1" ]; then
  tmux kill-window -t hybrid_demo:placeholder 2>/dev/null || true
  echo ""
  echo "Hybrid demo running in tmux session 'hybrid_demo'."
  echo "Attach with: tmux attach -t hybrid_demo"
  echo "Logs at: $LOG_DIR/"
  echo "Stop with: scripts/stop_demo.sh hybrid_demo  (or: tmux kill-session -t hybrid_demo)"
fi
