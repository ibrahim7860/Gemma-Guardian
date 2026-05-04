#!/bin/bash
#
# run_full_demo.sh — one-command launcher: starts the swarm, tails logs,
# stops cleanly on Ctrl-C.
#
# Usage:
#   scripts/run_full_demo.sh [scenario]
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${GG_LOG_DIR:-/tmp/gemma_guardian_logs}"

cleanup() {
  echo ""
  echo "[run_full_demo] received signal, stopping…"
  bash "$REPO_ROOT/scripts/stop_demo.sh" || true
}
trap cleanup INT TERM EXIT

bash "$REPO_ROOT/scripts/launch_swarm.sh" "$@"
echo "[run_full_demo] tailing $LOG_DIR/waypoint_runner.log (Ctrl-C to stop)…"
mkdir -p "$LOG_DIR"
touch "$LOG_DIR/waypoint_runner.log"
tail -F "$LOG_DIR/waypoint_runner.log"
