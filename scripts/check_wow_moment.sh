#!/bin/bash
#
# check_wow_moment.sh — pre-capture gate for the Beat 3c "wow moment" demo clip.
#
# Mirrors scripts/check_beat5.py's role for resilience_v1: launches the full
# stack against the wow_moment_v1 scenario, waits for an ASSIGNMENT_TOTAL_MISMATCH
# validation event to land in validation_events.jsonl, and snapshots the bridge
# WebSocket to confirm the dashboard banner data is flowing. Exit 0 means the
# wow moment is camera-ready; exit 1 means abort the capture session and
# investigate (do not burn wall-clock filming a broken stack).
#
# Usage:
#   scripts/check_wow_moment.sh [--dry-run] [--timeout N]
#
# Flags:
#   --dry-run    Print the planned operations and exit 0 without launching
#                anything. Used by unit tests and for human review.
#   --timeout N  Wall-clock budget in seconds for the validation-event wait
#                phase (default 90). The WS snapshot adds a separate 5s window.
#
# Env overrides:
#   GG_LOG_DIR        Where validation_events.jsonl lives (default
#                     /tmp/gemma_guardian_logs).
#   GG_BRIDGE_URL     WebSocket URL of the bridge (default
#                     ws://127.0.0.1:9090; matches shared/config.yaml).
#   GG_LAUNCH_SCRIPT  Path to launch_swarm.sh (default
#                     $REPO_ROOT/scripts/launch_swarm.sh).
#
# Exit codes:
#   0  Wow-moment is camera-ready.
#   1  Validation-event or WS check failed; abort capture.
#   2  Bad CLI args / missing prerequisites.
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
LOG_DIR="${GG_LOG_DIR:-/tmp/gemma_guardian_logs}"
BRIDGE_URL="${GG_BRIDGE_URL:-ws://127.0.0.1:9090}"
LAUNCH_SCRIPT="${GG_LAUNCH_SCRIPT:-$REPO_ROOT/scripts/launch_swarm.sh}"
SCENARIO="wow_moment_v1"
VALIDATION_LOG="$LOG_DIR/validation_events.jsonl"
TIMEOUT_S=240
DRY_RUN=0
INJECT_OVERCOUNT_ONCE=0

# ---- argparse --------------------------------------------------------------

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1; shift ;;
    --timeout)
      if [ "$#" -lt 2 ]; then
        echo "[check_wow_moment] --timeout requires a value" >&2
        exit 2
      fi
      TIMEOUT_S="$2"; shift 2 ;;
    --timeout=*)
      TIMEOUT_S="${1#--timeout=}"; shift ;;
    --inject-overcount-once)
      INJECT_OVERCOUNT_ONCE=1; shift ;;
    -h|--help)
      sed -n '3,28p' "$0"
      exit 0 ;;
    *)
      echo "[check_wow_moment] unknown flag: $1" >&2
      exit 2 ;;
  esac
done

# ---- dry-run path ----------------------------------------------------------
# Project convention (see scripts/check_beat5.py and scripts/launch_swarm.sh):
# --dry-run prints the planned operations and exits 0 without side-effects.

if [ "$DRY_RUN" -eq 1 ]; then
  echo "[plan] check_wow_moment.sh dry-run"
  echo "[plan] REPO_ROOT      = $REPO_ROOT"
  echo "[plan] LOG_DIR        = $LOG_DIR"
  echo "[plan] BRIDGE_URL     = $BRIDGE_URL"
  echo "[plan] LAUNCH_SCRIPT  = $LAUNCH_SCRIPT"
  echo "[plan] SCENARIO       = $SCENARIO"
  echo "[plan] VALIDATION_LOG = $VALIDATION_LOG"
  echo "[plan] TIMEOUT_S      = $TIMEOUT_S"
  echo "[plan] step 1: bash $LAUNCH_SCRIPT $SCENARIO"
  echo "[plan] step 2: tail $VALIDATION_LOG for agent_id=egs rule_id=ASSIGNMENT_TOTAL_MISMATCH (deadline ${TIMEOUT_S}s)"
  echo "[plan] step 3: uv run python scripts/_check_wow_moment_ws.py --bridge-url $BRIDGE_URL --window-s 5.0"
  echo "[plan] step 4: exit 0 iff both checks pass; else exit 1"
  exit 0
fi

# ---- prerequisites ---------------------------------------------------------

if [ ! -x "$LAUNCH_SCRIPT" ] && [ ! -r "$LAUNCH_SCRIPT" ]; then
  echo "[check_wow_moment] launch script not found: $LAUNCH_SCRIPT" >&2
  exit 2
fi

mkdir -p "$LOG_DIR"

# ---- step 1: launch the stack ---------------------------------------------
# launch_swarm.sh manages its own tmux session, daemonized redis-server, and
# component windows. It returns once everything is spawned (does NOT block
# until mission-complete) — perfect for "fire and then poll" gating.

LAUNCH_ARGS="$SCENARIO"
if [ "$INJECT_OVERCOUNT_ONCE" -eq 1 ]; then
  LAUNCH_ARGS="$LAUNCH_ARGS --inject-overcount-once"
fi

echo "[check_wow_moment] launching swarm against $SCENARIO..."
bash "$LAUNCH_SCRIPT" $LAUNCH_ARGS

# ---- step 2: tail validation_events.jsonl ---------------------------------
# Block until either an ASSIGNMENT_TOTAL_MISMATCH from agent_id=egs appears
# or the timeout fires. Re-reads the file every second so it absorbs slow
# Ollama warm-up without spinning the CPU.

echo "[check_wow_moment] waiting up to ${TIMEOUT_S}s for an EGS ASSIGNMENT_TOTAL_MISMATCH event in $VALIDATION_LOG..."
deadline=$((SECONDS + TIMEOUT_S))
found_event=0
while [ "$SECONDS" -lt "$deadline" ]; do
  if [ -r "$VALIDATION_LOG" ] && grep -q '"agent_id"[[:space:]]*:[[:space:]]*"egs"' "$VALIDATION_LOG" 2>/dev/null && grep -q '"rule_id"[[:space:]]*:[[:space:]]*"ASSIGNMENT_TOTAL_MISMATCH"' "$VALIDATION_LOG" 2>/dev/null; then
    found_event=1
    break
  fi
  sleep 1
done

if [ "$found_event" -ne 1 ]; then
  echo "[check_wow_moment] FAIL — no agent_id=egs rule_id=ASSIGNMENT_TOTAL_MISMATCH event in $VALIDATION_LOG after ${TIMEOUT_S}s" >&2
  echo "[check_wow_moment] Diagnostic: gemma 4 E4B may not have hallucinated an overcount this run. Either rerun (LLMs are stochastic), or fall back to the Phase 3c --inject-overcount-once flag documented in docs/plans/2026-05-12-gate4-wow-moment.md." >&2
  exit 1
fi
echo "[check_wow_moment] OK — observed EGS ASSIGNMENT_TOTAL_MISMATCH event"

# ---- step 3: WS snapshot ---------------------------------------------------
# Connect to the bridge and confirm at least one state_update envelope
# carries a non-empty replan_in_flight_attempt_log. This proves the wire
# path from the EGS retry sink → coordinator → Redis → bridge → WebSocket
# is live, which is the exact path the dashboard banner renders from.

echo "[check_wow_moment] snapshotting WS envelopes from $BRIDGE_URL (5s window)..."
if uv run python "$REPO_ROOT/scripts/_check_wow_moment_ws.py" \
    --bridge-url "$BRIDGE_URL" --window-s 5.0; then
  echo "[check_wow_moment] PASS — wow moment is camera-ready"
  exit 0
else
  ws_rc=$?
  echo "[check_wow_moment] FAIL — WS envelope check failed (rc=$ws_rc)" >&2
  echo "[check_wow_moment] Diagnostic: validation event was logged (so the EGS produced the overcount) but the dashboard didn't receive a populated replan_in_flight_attempt_log. Either the coordinator's _append_replan_attempt sink wiring broke, the bridge subscriber dropped the envelope, or the emit-loop didn't tick inside the 5s window." >&2
  exit 1
fi
