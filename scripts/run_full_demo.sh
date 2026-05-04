#!/bin/bash
#
# run_full_demo.sh — one-command launcher: starts the swarm, tails logs,
# stops cleanly on Ctrl-C.
#
# All arguments are forwarded verbatim to launch_swarm.sh. That includes
# --drones=auto|drone1,...   subset of the scenario roster (default: auto)
# --duration=N               sim runners self-terminate after N seconds
#                            (useful for scripted demos and CI)
# --dry-run                  print plans only; do not start tmux
#
# Usage:
#   scripts/run_full_demo.sh [scenario] [--drones=...] [--duration=N]
#
# Examples:
#   scripts/run_full_demo.sh
#   scripts/run_full_demo.sh disaster_zone_v1 --duration=30
#   scripts/run_full_demo.sh single_drone_smoke --drones=drone1
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
