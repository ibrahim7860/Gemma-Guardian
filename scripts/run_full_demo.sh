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

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
  esac
done

cleanup() {
  echo ""
  echo "[run_full_demo] received signal, stopping…"
  bash "$REPO_ROOT/scripts/stop_demo.sh" || true
}
# In --dry-run mode launch_swarm.sh prints its plan and exits cleanly; no
# processes were started, so the cleanup trap (which calls stop_demo.sh)
# is unnecessary and the tail loop would hang forever waiting on a log
# that never appears. Skip both for the dry-run path.
if [ "$DRY_RUN" -eq 0 ]; then
  trap cleanup INT TERM EXIT
fi

bash "$REPO_ROOT/scripts/launch_swarm.sh" "$@"

if [ "$DRY_RUN" -eq 1 ]; then
  echo "[run_full_demo] dry-run complete (no tmux session started)."
  exit 0
fi

echo "[run_full_demo] tailing $LOG_DIR/waypoint_runner.log (Ctrl-C to stop)…"
mkdir -p "$LOG_DIR"
touch "$LOG_DIR/waypoint_runner.log"
tail -F "$LOG_DIR/waypoint_runner.log"
