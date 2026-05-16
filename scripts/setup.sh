#!/usr/bin/env bash
#
# setup.sh — one-command dependency install for a fresh clone.
#
# Closes the `docs/23-submission-checklist.md` Reproducibility line
# ("scripts/setup.sh installs all dependencies") so the README Quick Start
# is genuinely two commands from `git clone`:
#
#   bash scripts/setup.sh         # this script
#   bash scripts/run_full_demo.sh # demo
#
# What it does:
#   1. Verifies prerequisites are on PATH (uv, redis-cli, ollama, tmux).
#      uv is hard-required; the others print actionable warnings but do
#      not block — they're only used at runtime, and some boxes install
#      Redis/Ollama via OS service managers.
#   2. Runs `uv sync --all-extras` so every role's Python deps land in
#      `.venv/` against the committed `uv.lock`. This is the same target
#      docs/sim-reproduction.md §2 documents for cold-start full demos.
#   3. Prints the next-step commands (Redis start, model pull, demo run).
#
# What it does NOT do:
#   - It does not install uv, Redis, Ollama, or tmux for you. Those are
#     OS-package-manager-level installs covered in docs/13-runtime-setup.md
#     per-platform (brew / apt / WSL2 / Windows). Auto-installing them
#     would silently make decisions about your machine; printing the
#     install command is the safer default.
#   - It does not pull Gemma 4 models. That's `scripts/pull_models.sh`
#     (separate script so it's resumable and can run `--dry-run`).
#
# Usage:
#   scripts/setup.sh                  # full install (uv sync --all-extras)
#   scripts/setup.sh --extras=sim     # role-scoped install (sim+mesh+dev)
#   scripts/setup.sh --pull-models    # also run scripts/pull_models.sh
#   scripts/setup.sh --dry-run        # print the planned operations
#
# Exit codes:
#   0  All requested operations succeeded.
#   1  A required step (uv sync) failed.
#   2  Bad CLI args or `uv` binary missing.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

EXTRAS=""        # empty → --all-extras; non-empty → role-scoped install
PULL_MODELS=0
DRY_RUN=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --extras=*)    EXTRAS="${1#--extras=}"; shift ;;
    --pull-models) PULL_MODELS=1;           shift ;;
    --dry-run)     DRY_RUN=1;               shift ;;
    -h|--help)
      sed -n '3,38p' "$0"
      exit 0 ;;
    *)
      echo "[setup] unknown flag: $1" >&2
      exit 2 ;;
  esac
done

warn_missing() {
  # $1: binary, $2: purpose, $3: install hint
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[setup] WARNING: '$1' not on PATH ($2). Install: $3" >&2
    return 1
  fi
  return 0
}

if ! command -v uv >/dev/null 2>&1; then
  echo "[setup] ERROR: 'uv' binary not on PATH." >&2
  echo "        Install: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  echo "        Docs:    https://docs.astral.sh/uv/" >&2
  exit 2
fi

# Soft-checks: warn but don't block. These are used at runtime, not by
# this script directly. docs/13-runtime-setup.md is the source of truth
# for per-platform installs.
warn_missing redis-cli "needed at demo runtime"    "brew install redis | sudo apt install redis-server" || true
warn_missing ollama    "needed to serve Gemma 4"   "https://ollama.com/download" || true
warn_missing tmux      "needed by launch_swarm.sh" "brew install tmux | sudo apt install tmux"          || true

if [ -n "$EXTRAS" ]; then
  IFS=',' read -ra EXTRA_LIST <<<"$EXTRAS"
  SYNC_ARGS=()
  for e in "${EXTRA_LIST[@]}"; do
    SYNC_ARGS+=("--extra" "$e")
  done
  # Always include 'dev' so pytest/ruff land regardless of role-extra.
  case " ${EXTRA_LIST[*]} " in *" dev "*) ;; *) SYNC_ARGS+=("--extra" "dev") ;; esac
else
  SYNC_ARGS=("--all-extras")
fi

if [ "$DRY_RUN" -eq 1 ]; then
  echo "[plan] setup.sh dry-run"
  echo "[plan] REPO_ROOT     = $REPO_ROOT"
  echo "[plan] EXTRAS        = ${EXTRAS:-<all>}"
  echo "[plan] PULL_MODELS   = $PULL_MODELS"
  echo "[plan] step 1: cd $REPO_ROOT && uv sync ${SYNC_ARGS[*]}"
  if [ "$PULL_MODELS" -eq 1 ]; then
    echo "[plan] step 2: bash $REPO_ROOT/scripts/pull_models.sh"
  fi
  echo "[plan] step 3: print next-step commands"
  exit 0
fi

echo "[setup] running: uv sync ${SYNC_ARGS[*]}"
(cd "$REPO_ROOT" && uv sync "${SYNC_ARGS[@]}")

if [ "$PULL_MODELS" -eq 1 ]; then
  echo "[setup] pulling Gemma 4 models via scripts/pull_models.sh ..."
  bash "$REPO_ROOT/scripts/pull_models.sh"
fi

cat <<'EOF'

[setup] OK — Python deps installed into .venv/.

Next steps:
  1. Start Redis if it's not already running:
       brew services start redis            # macOS
       sudo service redis-server start      # WSL2 / Linux without systemd
       sudo systemctl start redis-server    # Linux with systemd
     Verify with: redis-cli ping  → PONG

  2. Pull Gemma 4 models (skip if you passed --pull-models above):
       bash scripts/pull_models.sh

  3. Run the demo:
       bash scripts/run_full_demo.sh disaster_zone_v1 --duration=60

  4. (Optional) Start the Flutter dashboard in a second pane:
       bash scripts/run_dashboard_dev.sh
     Then open http://localhost:8000/?ws=ws://127.0.0.1:9090/

For the full cold-start walkthrough see docs/sim-reproduction.md.
EOF
