#!/bin/bash
#
# run_resilience_scenario.sh — launch the resilience_v1 scenario with a
# sensible default --duration matching the scripted mission_complete event
# (T+240s). Thin wrapper around scripts/launch_swarm.sh.
#
# Why a dedicated script: docs/20-integration-contracts.md and the project
# CLAUDE.md both list this script in the target file-system layout. Person 3
# (EGS) reaches for it during Phase D / E rehearsals to exercise the mesh-
# dropout + EGS-link-loss + replan loop without remembering scenario flags.
#
# Usage:
#   scripts/run_resilience_scenario.sh [--duration=N] [--drones=...] [--dry-run]
#
# All flags are forwarded verbatim to launch_swarm.sh. If the caller does NOT
# supply --duration, we inject --duration=240 so the sim runners self-terminate
# at the scripted mission_complete tick. Any explicit --duration wins.
#
# Examples:
#   scripts/run_resilience_scenario.sh
#   scripts/run_resilience_scenario.sh --duration=60        # short rehearsal
#   scripts/run_resilience_scenario.sh --drones=drone2,drone3 \
#       # leaves drone1 free for sim/manual_pilot.py in another pane
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Default duration tracks the scripted mission_complete event in
# sim/scenarios/resilience_v1.yaml. Keep these in sync if the scenario
# timeline shifts.
DEFAULT_DURATION=240

HAS_DURATION=0
for arg in "$@"; do
  case "$arg" in
    --duration=*) HAS_DURATION=1 ;;
  esac
done

ARGS=()
if [ "$HAS_DURATION" -eq 0 ]; then
  ARGS+=("--duration=$DEFAULT_DURATION")
fi
ARGS+=("$@")

exec bash "$REPO_ROOT/scripts/launch_swarm.sh" resilience_v1 "${ARGS[@]}"
