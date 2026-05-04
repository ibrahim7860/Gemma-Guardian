#!/bin/bash
#
# stop_demo.sh — graceful shutdown of the FieldAgent demo stack.
#
# Idempotent: running it twice (or when nothing is running) must succeed
# without errors. That's what makes it safe to wire into CI / `trap`.
#
# Redis ownership: only shut down the broker if launch_swarm.sh left a
# sentinel marking it ours. On boxes where Redis is a long-lived system
# service, the sentinel is absent and we leave it running — see anomaly #3
# in docs/sim-live-run-notes.md for the bug this prevents.
#
set -uo pipefail

LOG_DIR="${GG_LOG_DIR:-/tmp/gemma_guardian_logs}"
SENTINEL="$LOG_DIR/.gg_started_redis"

# Kill the tmux session, if any.
if command -v tmux >/dev/null 2>&1; then
  tmux kill-session -t fieldagent 2>/dev/null || true
fi

# Best-effort SIGTERM of named components.
pkill -f "sim/waypoint_runner.py"        2>/dev/null || true
pkill -f "sim/frame_server.py"           2>/dev/null || true
pkill -f "agents/mesh_simulator/main.py" 2>/dev/null || true
pkill -f "agents/egs_agent/main.py"      2>/dev/null || true
pkill -f "agents/drone_agent/main.py"    2>/dev/null || true
pkill -f "frontend/ws_bridge/main.py"    2>/dev/null || true

# Only shut down the Redis we daemonized ourselves (sentinel present).
if [ -f "$SENTINEL" ]; then
  if command -v redis-cli >/dev/null 2>&1 && redis-cli ping >/dev/null 2>&1; then
    redis-cli shutdown nosave 2>/dev/null || true
  fi
  rm -f "$SENTINEL"
fi

echo "FieldAgent stopped."
exit 0
