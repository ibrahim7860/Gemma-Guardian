#!/usr/bin/env bash
#
# pull_models.sh — fetch the Gemma 4 variants FieldAgent uses, via Ollama.
#
# Pulls the upstream tags consumed by `shared/config.yaml` (`drone_model:
# gemma4:e2b`, `egs_model: gemma4:e4b`). Optionally builds the local
# `fieldagent/*` variants from `ollama/Modelfile.*` for deployers who want
# the documented defaults baked into the deployment artifact.
#
# This script is the deployment artifact backing the project's Ollama
# special-prize claim per `docs/23-submission-checklist.md` §Repository
# Checklist and `docs/kaggle-submission-draft.md` §7 Special-prize claims.
#
# Usage:
#   scripts/pull_models.sh                     # pull upstream tags only
#   scripts/pull_models.sh --build-tagged      # also build fieldagent/{e2b,e4b}
#   scripts/pull_models.sh --dry-run           # print the planned operations
#
# Exit codes:
#   0  All requested models present after run.
#   1  An ollama pull/create failed.
#   2  Bad CLI args or `ollama` binary missing.
set -euo pipefail

BUILD_TAGGED=0
DRY_RUN=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --build-tagged) BUILD_TAGGED=1; shift ;;
    --dry-run)      DRY_RUN=1;      shift ;;
    -h|--help)
      sed -n '3,22p' "$0"
      exit 0 ;;
    *)
      echo "[pull_models] unknown flag: $1" >&2
      exit 2 ;;
  esac
done

REPO_ROOT="${REPO_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
E2B_MODELFILE="$REPO_ROOT/ollama/Modelfile.e2b"
E4B_MODELFILE="$REPO_ROOT/ollama/Modelfile.e4b"

if ! command -v ollama >/dev/null 2>&1; then
  echo "[pull_models] ERROR: 'ollama' binary not on PATH. Install from https://ollama.com." >&2
  exit 2
fi

if [ "$DRY_RUN" -eq 1 ]; then
  echo "[plan] pull_models.sh dry-run"
  echo "[plan] REPO_ROOT      = $REPO_ROOT"
  echo "[plan] BUILD_TAGGED   = $BUILD_TAGGED"
  echo "[plan] step 1: ollama pull gemma4:e2b"
  echo "[plan] step 2: ollama pull gemma4:e4b"
  if [ "$BUILD_TAGGED" -eq 1 ]; then
    echo "[plan] step 3: ollama create fieldagent/e2b -f $E2B_MODELFILE"
    echo "[plan] step 4: ollama create fieldagent/e4b -f $E4B_MODELFILE"
  fi
  echo "[plan] step 5: ollama list | grep -E 'gemma4|fieldagent'"
  exit 0
fi

echo "[pull_models] pulling gemma4:e2b ..."
ollama pull gemma4:e2b

echo "[pull_models] pulling gemma4:e4b ..."
ollama pull gemma4:e4b

if [ "$BUILD_TAGGED" -eq 1 ]; then
  if [ ! -r "$E2B_MODELFILE" ] || [ ! -r "$E4B_MODELFILE" ]; then
    echo "[pull_models] ERROR: Modelfiles missing at $E2B_MODELFILE / $E4B_MODELFILE" >&2
    exit 1
  fi
  echo "[pull_models] building fieldagent/e2b from $E2B_MODELFILE ..."
  ollama create fieldagent/e2b -f "$E2B_MODELFILE"
  echo "[pull_models] building fieldagent/e4b from $E4B_MODELFILE ..."
  ollama create fieldagent/e4b -f "$E4B_MODELFILE"
fi

echo "[pull_models] OK — installed:"
ollama list | grep -E "gemma4|fieldagent" || {
  echo "[pull_models] ERROR: expected gemma4:* in 'ollama list' output but none found." >&2
  exit 1
}
