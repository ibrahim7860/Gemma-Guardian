#!/bin/bash
#
# run_beat5_capture.sh — Beat 5 (offline-proof) capture rig orchestrator.
#
# Locked to the resilience_v1 scenario. Boots a fully integrated stack on
# free ephemeral ports, pre-warms Ollama (E2B + E4B), and prints a
# "ready to record" status line plus the exact `sudo ifconfig`/airport
# commands the operator runs at scenario t≈100s to drop wifi (and again
# at t≈190s to bring it back). Mirrors scripts/run_hybrid_demo.sh's
# tmux + env-override style and scripts/launch_swarm.sh's component
# launch order.
#
# Usage:
#   scripts/run_beat5_capture.sh [--dry-run] [--no-prewarm] [--teardown]
#
# Flags:
#   --dry-run     Print the plan; do not start tmux or background procs.
#   --no-prewarm  Skip the Ollama E2B/E4B pre-warm (useful when running
#                 against scripts/ollama_mock_server.py).
#   --teardown    pkill the whole stack from a prior run + redis-cli SHUTDOWN
#                 the captured-rig redis. Idempotent; safe to run twice.
#
# Env overrides (mirror scripts/run_hybrid_demo.sh):
#   GG_NO_TMUX=1     skip the actual tmux invocation; print plans only
#                    (used by tests via `bash -n` and CI smoke).
#   GG_REDIS_URL     overrides the ephemeral redis selection. Rare; only
#                    use if you already have a redis-server listening on a
#                    pinned port.
#   GG_LOG_DIR       defaults to /tmp/gg_beat5_capture
#   GG_OLLAMA_URL    defaults to http://127.0.0.1:11434 (real daemon).
#                    Override to point at scripts/ollama_mock_server.py
#                    for deterministic capture rehearsals.
#
# Operator workflow once "ready to record" prints:
#   1. Open OBS / start screen recording.
#   2. Open the dashboard: http://127.0.0.1:$FLUTTER_PORT/?ws=ws://127.0.0.1:$BRIDGE_PORT/
#   3. Open two terminal panes:
#        - Pane A: command shell to run the wifi commands when the
#          scenario tick log line says t=100.
#        - Pane B: the connectivity-probe loop printed below.
#   4. At scenario t≈100: in pane A, run the "drop wifi" commands.
#   5. At scenario t≈190: in pane A, run the "restore wifi" commands.
#   6. After mission_complete (t=240): run scripts/check_beat5.py to
#      verify the run is good-to-cut.
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${GG_LOG_DIR:-/tmp/gg_beat5_capture}"
OLLAMA_URL="${GG_OLLAMA_URL:-http://127.0.0.1:11434}"
SCENARIO="resilience_v1"
SESSION="beat5_capture"

DRY_RUN=0
PREWARM=1
TEARDOWN=0

for arg in "$@"; do
  case "$arg" in
    --dry-run)    DRY_RUN=1 ;;
    --no-prewarm) PREWARM=0 ;;
    --teardown)   TEARDOWN=1 ;;
    --*)          echo "unknown flag: $arg" >&2; exit 2 ;;
    *)            echo "unknown positional: $arg" >&2; exit 2 ;;
  esac
done

# ---------------------------------------------------------------------------
# Teardown path: pkill the stack then redis-cli SHUTDOWN our broker.
# ---------------------------------------------------------------------------
if [ "$TEARDOWN" -eq 1 ]; then
  echo "[run_beat5_capture] tearing down stack…"
  pkill -f "agents.egs_agent.main"      2>/dev/null || true
  pkill -f "agents.drone_agent"          2>/dev/null || true
  pkill -f "agents.mesh_simulator"       2>/dev/null || true
  pkill -f "sim.waypoint_runner"         2>/dev/null || true
  pkill -f "sim.frame_server"            2>/dev/null || true
  pkill -f "uvicorn frontend.ws_bridge"  2>/dev/null || true
  pkill -f "scripts/ws_recorder.py"      2>/dev/null || true
  pkill -f "http.server.*beat5_capture"  2>/dev/null || true
  if [ -f "$LOG_DIR/ports.env" ]; then
    # shellcheck disable=SC1091
    source "$LOG_DIR/ports.env"
    if [ -n "${REDIS_PORT:-}" ] && command -v redis-cli >/dev/null 2>&1; then
      redis-cli -p "$REDIS_PORT" SHUTDOWN NOSAVE 2>/dev/null || true
    fi
  fi
  if command -v tmux >/dev/null 2>&1; then
    tmux kill-session -t "$SESSION" 2>/dev/null || true
  fi
  echo "[run_beat5_capture] teardown complete"
  exit 0
fi

mkdir -p "$LOG_DIR"

# ---------------------------------------------------------------------------
# 1. Pick free ephemeral ports.
# ---------------------------------------------------------------------------
echo "[run_beat5_capture] picking ephemeral ports…"
python3 - <<'PY' > "$LOG_DIR/ports.env"
import socket
for tag in ("REDIS_PORT", "BRIDGE_PORT", "FLUTTER_PORT"):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    print(f"{tag}={s.getsockname()[1]}")
    s.close()
PY
# shellcheck disable=SC1091
source "$LOG_DIR/ports.env"
REDIS_URL="${GG_REDIS_URL:-redis://127.0.0.1:${REDIS_PORT}/0}"

echo "[run_beat5_capture] log_dir=$LOG_DIR"
echo "[run_beat5_capture] redis_url=$REDIS_URL"
echo "[run_beat5_capture] bridge=ws://127.0.0.1:${BRIDGE_PORT}/"
echo "[run_beat5_capture] flutter=http://127.0.0.1:${FLUTTER_PORT}/"
echo "[run_beat5_capture] ollama=$OLLAMA_URL"

# ---------------------------------------------------------------------------
# 2. Pre-warm Ollama (E2B + E4B). Cold-load is ~16s on E2B / ~99s on E4B
#    on Apple Silicon (see runbook). Skip with --no-prewarm if you're
#    pointing at the mock.
# ---------------------------------------------------------------------------
if [ "$PREWARM" -eq 1 ] && [ "$DRY_RUN" -eq 0 ]; then
  echo "[run_beat5_capture] pre-warming Ollama (E2B + E4B)…"
  for MODEL in "gemma4:e2b" "gemma4:e4b"; do
    if curl -fsS -X POST "$OLLAMA_URL/api/chat" \
         --max-time 180 \
         -H 'content-type: application/json' \
         -d "{\"model\":\"$MODEL\",\"stream\":false,\"messages\":[{\"role\":\"user\",\"content\":\"ok\"}]}" \
         > "$LOG_DIR/prewarm_${MODEL//[:\/]/_}.log" 2>&1; then
      echo "[run_beat5_capture] pre-warm $MODEL OK"
    else
      echo "[run_beat5_capture] WARNING: pre-warm $MODEL failed (see $LOG_DIR/prewarm_${MODEL//[:\/]/_}.log) — continuing"
    fi
  done
else
  echo "[run_beat5_capture] skipping Ollama pre-warm (--no-prewarm or --dry-run)"
fi

# ---------------------------------------------------------------------------
# 3. tmux harness.
# ---------------------------------------------------------------------------
emit() {
  local window="$1"; shift
  echo "[plan] tmux:${window} :: $*"
  if [ "$DRY_RUN" -eq 0 ] && [ "${GG_NO_TMUX:-0}" != "1" ]; then
    tmux new-window -t "$SESSION" -n "$window"
    tmux send-keys -t "${SESSION}:${window}" "$*" Enter
  fi
}

if [ "$DRY_RUN" -eq 0 ] && [ "${GG_NO_TMUX:-0}" != "1" ]; then
  if ! command -v tmux >/dev/null 2>&1; then
    echo "[error] tmux not on PATH; install or use --dry-run" >&2
    exit 1
  fi
  tmux kill-session -t "$SESSION" 2>/dev/null || true
  tmux new-session -d -s "$SESSION" -n placeholder
fi

# ---------------------------------------------------------------------------
# 4. Start ephemeral redis. Always our own broker — never share with the
#    system one to avoid polluting other demos with this run's pubsub.
# ---------------------------------------------------------------------------
if [ "$DRY_RUN" -eq 0 ]; then
  if [ -z "${GG_REDIS_URL:-}" ]; then
    if ! command -v redis-server >/dev/null 2>&1; then
      echo "[error] redis-server not on PATH" >&2
      exit 1
    fi
    redis-server --port "$REDIS_PORT" --save "" --appendonly no \
                 --daemonize yes --logfile "$LOG_DIR/redis.log"
    sleep 0.5
    if ! redis-cli -p "$REDIS_PORT" ping >/dev/null 2>&1; then
      echo "[error] redis on $REDIS_PORT did not come up; see $LOG_DIR/redis.log" >&2
      exit 1
    fi
    echo "[run_beat5_capture] redis up on $REDIS_PORT"
  else
    echo "[run_beat5_capture] using GG_REDIS_URL override: $GG_REDIS_URL"
  fi
fi

# ---------------------------------------------------------------------------
# 5. Component launch order: mesh_sim, EGS (waits for mesh adjacency),
#    sim, drone agents, bridge, flutter http server.
# ---------------------------------------------------------------------------
emit mesh "cd $REPO_ROOT && GG_LOG_DIR=$LOG_DIR python3 -m agents.mesh_simulator --redis-url $REDIS_URL --egs-lat 34.0000 --egs-lon -118.5000 2>&1 | tee $LOG_DIR/mesh.log"

emit egs "cd $REPO_ROOT && GG_LOG_DIR=$LOG_DIR REDIS_URL=$REDIS_URL python3 -m agents.egs_agent.main 2>&1 | tee $LOG_DIR/egs.log"

emit waypoint "cd $REPO_ROOT && GG_LOG_DIR=$LOG_DIR python3 sim/waypoint_runner.py --scenario $SCENARIO --redis-url $REDIS_URL 2>&1 | tee $LOG_DIR/waypoint_runner.log"
emit frames "cd $REPO_ROOT && GG_LOG_DIR=$LOG_DIR python3 sim/frame_server.py --scenario $SCENARIO --redis-url $REDIS_URL 2>&1 | tee $LOG_DIR/frame_server.log"

# Drone roster — locked to resilience_v1 scenario (drone1, drone2, drone3).
# Hard-coded rather than derived via sim/list_drones.py so this script
# doesn't depend on the Python environment having pyyaml on PATH; the
# scenario itself is locked at the top of this script (SCENARIO=...).
DRONE_ARRAY=("drone1" "drone2" "drone3")
for ID in "${DRONE_ARRAY[@]}"; do
  emit "$ID" "cd $REPO_ROOT && GG_LOG_DIR=$LOG_DIR python3 -m agents.drone_agent --drone-id $ID --scenario $SCENARIO --redis-url $REDIS_URL --ollama-endpoint $OLLAMA_URL 2>&1 | tee $LOG_DIR/$ID.log"
done

emit ws_bridge "cd $REPO_ROOT && GG_LOG_DIR=$LOG_DIR REDIS_URL=$REDIS_URL python3 -m uvicorn frontend.ws_bridge.main:app --host 127.0.0.1 --port $BRIDGE_PORT --log-level info 2>&1 | tee $LOG_DIR/ws_bridge.log"

emit ws_recorder "cd $REPO_ROOT && GG_LOG_DIR=$LOG_DIR python3 scripts/ws_recorder.py --bridge-url ws://127.0.0.1:$BRIDGE_PORT --out $LOG_DIR/ws_frames.jsonl --deadline-s 300 2>&1 | tee $LOG_DIR/ws_recorder.log"

emit flutter "cd $REPO_ROOT/frontend/flutter_dashboard/build/web && python3 -m http.server $FLUTTER_PORT --bind 127.0.0.1 2>&1 | tee $LOG_DIR/flutter.log"

if [ "$DRY_RUN" -eq 0 ] && [ "${GG_NO_TMUX:-0}" != "1" ]; then
  tmux kill-window -t "${SESSION}:placeholder" 2>/dev/null || true
fi

# ---------------------------------------------------------------------------
# 6. Scenario-tick pacer. Once per second print "scenario_tick=<N>s" to
#    stdout so the operator knows when to hit the wifi-down command. The
#    pacer launches in the foreground after all components are up and
#    runs until t=240 (mission_complete) or Ctrl-C.
# ---------------------------------------------------------------------------
print_ready_banner() {
  cat <<EOF

==============================================================================
[run_beat5_capture] READY TO RECORD

  Dashboard URL : http://127.0.0.1:${FLUTTER_PORT}/?ws=ws://127.0.0.1:${BRIDGE_PORT}/
  Bridge        : ws://127.0.0.1:${BRIDGE_PORT}/
  Logs          : $LOG_DIR/

  Operator pane A — drop wifi at scenario t≈100, restore at t≈190:

      # macOS (zsh / bash):
      sudo ifconfig en0 down                    # at t≈100
      sudo ifconfig en0 up                      # at t≈190

      # Linux:
      sudo ip link set wlan0 down               # at t≈100
      sudo ip link set wlan0 up                 # at t≈190

  Operator pane B — connectivity probe loop (proves real network is gone):

      while true; do
        printf '%(%H:%M:%S)T  ' -1
        if curl -fsS --max-time 1 https://www.google.com > /dev/null; then
          echo "WAN: up"
        else
          echo "WAN: DOWN"
        fi
        sleep 1
      done

  After t=240 (mission_complete), verify the run with:

      uv run python scripts/check_beat5.py \\
          --bridge-url ws://127.0.0.1:${BRIDGE_PORT} \\
          --validation-log $LOG_DIR/validation_events.jsonl \\
          --deadline-s 30

  On a second machine (or after the stack is torn down), re-verify
  from artifacts alone:

      uv run python scripts/check_beat5.py \\
          --ws-replay-log $LOG_DIR/ws_frames.jsonl \\
          --validation-log $LOG_DIR/validation_events.jsonl

  Tear the stack down (idempotent):

      bash scripts/run_beat5_capture.sh --teardown
==============================================================================
EOF
}

if [ "$DRY_RUN" -eq 0 ] && [ "${GG_NO_TMUX:-0}" != "1" ]; then
  # Give components a couple seconds to settle before declaring ready.
  sleep 3
  print_ready_banner
  START_TS=$(date +%s)
  echo "[run_beat5_capture] scenario tick pacer running (Ctrl-C to stop)…"
  while :; do
    NOW=$(date +%s)
    T=$(( NOW - START_TS ))
    printf "[run_beat5_capture] scenario_tick=%ds\n" "$T"
    if [ "$T" -ge 240 ]; then
      echo "[run_beat5_capture] reached mission_complete (t=240); pacer exiting"
      break
    fi
    sleep 1
  done
else
  echo "[run_beat5_capture] dry-run / no-tmux mode: skipping pacer"
fi
