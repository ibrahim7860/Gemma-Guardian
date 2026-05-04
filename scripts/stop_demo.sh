#!/bin/bash
#
# stop_demo.sh — graceful shutdown of the FieldAgent demo stack.
#
# Idempotent: running it twice (or when nothing is running) must succeed
# without errors. That's what makes it safe to wire into CI / `trap`.
#
set -uo pipefail

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

# Shut down any redis-server we daemonized.
if command -v redis-cli >/dev/null 2>&1; then
  if redis-cli ping >/dev/null 2>&1; then
    redis-cli shutdown nosave 2>/dev/null || true
  fi
fi

echo "FieldAgent stopped."
exit 0
