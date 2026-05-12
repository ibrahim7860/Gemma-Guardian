#!/bin/bash
#
# launch_swarm.sh — start the full FieldAgent demo stack in a tmux session.
#
# Modeled on docs/15-multi-drone-spawning.md, this script tolerates missing
# agent processes so Hazim (sim lead) can run a partial stack while
# Kaleel/Qasim/Ibrahim are still building. Components that don't exist yet are
# logged as "skipping" rather than blocking the launch.
#
# Usage:
#   scripts/launch_swarm.sh [scenario] [--dry-run] [--drones=auto|drone1,...] [--duration=N]
#
# --drones default is "auto" — the roster is derived from the scenario YAML's
# drones[].drone_id list via sim/list_drones.py. Pass --drones=drone1,drone2
# explicitly to launch a subset.
#
# --duration=N propagates to sim/waypoint_runner.py and sim/frame_server.py
# so they self-terminate after N seconds. Useful for scripted demos and CI.
# Drone agents and EGS do not accept --duration; the flag is omitted on those
# invocations.
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

# F4 (Phase G cold-run 2026-05-12): tmux `new-window` spawns a fresh shell that
# doesn't inherit VIRTUAL_ENV from the caller, so every emit'd `python3 ...`
# resolves to *system* python in the tmux pane — which lacks the project's
# deps and crashes with ModuleNotFoundError. Compute an ACTIVATE prefix here
# and prepend it to every emit'd command. Also source it into this script's
# own shell so the list_drones.py call below uses the venv python too.
# Regression guard: scripts/tests/test_launch_scripts.py::
# test_launch_swarm_emits_venv_activation_when_present.
ACTIVATE=""
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.venv/bin/activate"
  # Quote the path so it survives REPO_ROOTs that contain spaces (e.g.
  # "/Users/.../CS Work/Repos/Gemma-Guardian"). Without quoting, `source`
  # only reads the first word and fails with "is a directory". Caught
  # during F4 fix verification on a dev clone with a space in the path.
  ACTIVATE="source \"$REPO_ROOT/.venv/bin/activate\" && "
fi

DRY_RUN=0
SCENARIO="disaster_zone_v1"
DRONES="auto"
DURATION=""

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --drones=*) DRONES="${arg#--drones=}" ;;
    --duration=*) DURATION="${arg#--duration=}" ;;
    --*) echo "unknown flag: $arg" >&2; exit 2 ;;
    *)   SCENARIO="$arg" ;;
  esac
done

# Build the optional --duration argument fragment that gets appended to
# sim/waypoint_runner.py and sim/frame_server.py invocations. Drone agents
# and EGS do not accept --duration, so only the sim runners receive it.
DURATION_ARG=""
if [ -n "$DURATION" ]; then
  DURATION_ARG="--duration $DURATION"
fi

if [ "$DRONES" = "auto" ]; then
  if ! DRONES="$(PYTHONPATH="$REPO_ROOT" python3 "$REPO_ROOT/sim/list_drones.py" "$SCENARIO")"; then
    echo "[error] failed to derive drone roster from scenario '$SCENARIO'" >&2
    exit 1
  fi
else
  # Explicit subset: every requested id must be declared in the scenario YAML.
  # Catching this here is cheap and prevents launching a ghost drone agent
  # whose --drone-id isn't actually in the sim's publish set, which would
  # otherwise look like the agent is silently broken.
  if ! SCENARIO_DRONES="$(PYTHONPATH="$REPO_ROOT" python3 "$REPO_ROOT/sim/list_drones.py" "$SCENARIO")"; then
    echo "[error] failed to read scenario '$SCENARIO' for --drones validation" >&2
    exit 1
  fi
  IFS=',' read -ra _REQUESTED <<< "$DRONES"
  IFS=',' read -ra _AVAILABLE <<< "$SCENARIO_DRONES"
  for _r in "${_REQUESTED[@]}"; do
    _found=0
    for _a in "${_AVAILABLE[@]}"; do
      if [ "$_r" = "$_a" ]; then _found=1; break; fi
    done
    if [ "$_found" -eq 0 ]; then
      echo "[error] requested drone '$_r' is not in scenario '$SCENARIO' (available: $SCENARIO_DRONES)" >&2
      exit 2
    fi
  done
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
# Ownership sentinel: we only `redis-cli shutdown nosave` (in stop_demo.sh) the
# brokers we daemonized ourselves. Writing $LOG_DIR/.gg_started_redis here
# tells stop_demo.sh "this one is safe to take down". When Redis was already
# running (e.g. system-managed via `service redis-server start`), the sentinel
# is *not* written, so stop_demo.sh leaves the broker alone.
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

# --- tmux session ------------------------------------------------------------
# We create the session without a named first window. emit() then creates one
# new-window per process, so all windows have unique names. The auto-named
# placeholder (window 0) is killed once at least one named window exists,
# leaving a tidy session.
if [ "$DRY_RUN" -eq 0 ] && [ "${GG_NO_TMUX:-0}" != "1" ]; then
  if ! command -v tmux >/dev/null 2>&1; then
    echo "[error] tmux not on PATH; install or use --dry-run" >&2
    exit 1
  fi
  tmux kill-session -t fieldagent 2>/dev/null || true
  tmux new-session -d -s fieldagent -n placeholder
fi

# --- Sim components (Hazim — always present) ------------------------------
emit waypoint "cd \"$REPO_ROOT\" && ${ACTIVATE}python3 sim/waypoint_runner.py --scenario $SCENARIO --redis-url $REDIS_URL $DURATION_ARG 2>&1 | tee $LOG_DIR/waypoint_runner.log"
emit frames   "cd \"$REPO_ROOT\" && ${ACTIVATE}python3 sim/frame_server.py    --scenario $SCENARIO --redis-url $REDIS_URL $DURATION_ARG 2>&1 | tee $LOG_DIR/frame_server.log"
# EGS position is derived from the active scenario's `origin` via --scenario
# (single source of truth — `agents/mesh_simulator/main.py` calls
# `sim.scenario.resolve_scenario_path` and reads `origin.lat/.lon`).
# Without an EGS position, `MeshSimulator.forward_finding` silently drops every
# payload because `egs_pos is None`, which would blank the dashboard during
# demo capture (PR #41 made the mesh sim the required gateway for the bridge's
# `.findings.delivered` path). The mesh sim now exits 2 with a clear error if
# neither --scenario nor both --egs-lat/--egs-lon are passed, so this trap
# cannot regress silently.
emit_if_exists mesh "agents/mesh_simulator/main.py" \
  "cd \"$REPO_ROOT\" && ${ACTIVATE}python3 agents/mesh_simulator/main.py --redis-url $REDIS_URL --scenario $SCENARIO 2>&1 | tee $LOG_DIR/mesh.log"

# --- EGS (Qasim) ----------------------------------------------------------
# Module-mode invocation: agents/egs_agent/main.py uses absolute imports
# (`from agents.egs_agent.validation import ...`) which fail with
# ModuleNotFoundError under the bare-script form. Mirrors the drone agent's
# `python3 -m agents.drone_agent` pattern on line 165 and the working EGS
# invocation in scripts/run_beat5_capture.sh.
emit_if_exists egs "agents/egs_agent/main.py" \
  "cd \"$REPO_ROOT\" && ${ACTIVATE}python3 -m agents.egs_agent.main 2>&1 | tee $LOG_DIR/egs.log"

# --- Drone agents (Kaleel) -------------------------------------------------
IFS=',' read -ra DRONE_ARRAY <<< "$DRONES"
for ID in "${DRONE_ARRAY[@]}"; do
  emit_if_exists "$ID" "agents/drone_agent/__main__.py" \
    "cd \"$REPO_ROOT\" && ${ACTIVATE}python3 -m agents.drone_agent --drone-id $ID --scenario $SCENARIO 2>&1 | tee $LOG_DIR/$ID.log"
done

# --- WebSocket bridge (Ibrahim) ---------------------------------------------
# Launch via uvicorn — frontend/ws_bridge/main.py only constructs the FastAPI
# app and exits if invoked as a script (no embedded server). Same form used by
# scripts/run_hybrid_demo.sh and scripts/launch_dashboard_dev.sh.
emit_if_exists ws_bridge "frontend/ws_bridge/main.py" \
  "cd \"$REPO_ROOT\" && ${ACTIVATE}python3 -m uvicorn frontend.ws_bridge.main:app --port 9090 --log-level info 2>&1 | tee $LOG_DIR/ws_bridge.log"

if [ "$DRY_RUN" -eq 0 ] && [ "${GG_NO_TMUX:-0}" != "1" ]; then
  # Drop the placeholder window now that real ones exist.
  tmux kill-window -t fieldagent:placeholder 2>/dev/null || true
  echo ""
  echo "FieldAgent swarm running in tmux session 'fieldagent'."
  echo "Attach with: tmux attach -t fieldagent"
  echo "Logs at: $LOG_DIR/"
  echo "Stop with: scripts/stop_demo.sh"
fi
