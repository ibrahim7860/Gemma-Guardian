#!/usr/bin/env bash
# Runpod GPU pod bootstrap — Gate 3 fine-tune attempt.
#
# Runs on a freshly booted Runpod CUDA pod. Idempotent.
#
# Required env vars (pass to the pod via the create-pod call OR export before running):
#   KAGGLE_USERNAME   — your Kaggle username
#   KAGGLE_KEY        — your Kaggle API key (from kaggle.com/settings/account)
#   GIT_REPO          — defaults to https://github.com/ibrahim7860/Gemma-Guardian.git
#   GIT_REF           — defaults to main
#   PHASE             — "verify" (default, runs only Day-2 gate) | "all" (verify + prep + train) | "prep" | "train"
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/ibrahim7860/Gemma-Guardian/main/scripts/runpod_bootstrap.sh \
#     | KAGGLE_USERNAME=... KAGGLE_KEY=... PHASE=verify bash
#
# Or after cloning the repo:
#   bash scripts/runpod_bootstrap.sh
set -euo pipefail

GIT_REPO="${GIT_REPO:-https://github.com/ibrahim7860/Gemma-Guardian.git}"
GIT_REF="${GIT_REF:-main}"
PHASE="${PHASE:-verify}"
WORK_DIR="${WORK_DIR:-/workspace}"
DATA_DIR="${DATA_DIR:-$WORK_DIR/data}"

log() { printf '[bootstrap %s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

# --- 0. sanity ---
log "phase=$PHASE workdir=$WORK_DIR"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader || {
  echo "FAIL: no nvidia-smi; this script must run on a CUDA pod." >&2
  exit 2
}
mkdir -p "$WORK_DIR" "$DATA_DIR"
cd "$WORK_DIR"

# --- 1. system deps ---
log "apt update + system deps"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git curl wget unzip build-essential libgl1 libglib2.0-0 > /dev/null

# --- 2. clone repo ---
if [ ! -d gemma-guardian/.git ]; then
  log "cloning $GIT_REPO @ $GIT_REF"
  git clone --branch "$GIT_REF" --depth 1 "$GIT_REPO" gemma-guardian
else
  log "repo already present; fetching $GIT_REF"
  (cd gemma-guardian && git fetch --depth 1 origin "$GIT_REF" && git checkout "$GIT_REF" && git reset --hard "origin/$GIT_REF")
fi
cd gemma-guardian

# --- 3. python env ---
log "installing uv"
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
uv --version

log "uv sync --extra ml --extra dev"
uv sync --extra ml --extra dev

# Unsloth + kaggle aren't in the locked extras (Mac-incompatible). Install separately on the GPU box.
log "installing unsloth + trl + bitsandbytes + kaggle (GPU-only)"
uv pip install --upgrade "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git" \
  "trl>=0.11" "bitsandbytes>=0.43" "peft>=0.13" "accelerate>=1.0" "kaggle>=1.6" "datasets>=2.20"

# --- 4. kaggle creds ---
if [ "$PHASE" != "verify" ]; then
  if [ -z "${KAGGLE_USERNAME:-}" ] || [ -z "${KAGGLE_KEY:-}" ]; then
    echo "FAIL: KAGGLE_USERNAME and KAGGLE_KEY required for phase=$PHASE" >&2
    exit 3
  fi
  mkdir -p ~/.kaggle
  printf '{"username":"%s","key":"%s"}\n' "$KAGGLE_USERNAME" "$KAGGLE_KEY" > ~/.kaggle/kaggle.json
  chmod 600 ~/.kaggle/kaggle.json
  log "kaggle creds installed"
fi

# --- 5. phase: verify (docs/12 Day-2 gate) ---
if [ "$PHASE" = "verify" ] || [ "$PHASE" = "all" ]; then
  log "=== Day-2 Unsloth verification gate ==="
  uv run python ml/training/verify_unsloth.py 2>&1 | tee "$WORK_DIR/verify_unsloth.log"
  if [ "${PIPESTATUS[0]}" -ne 0 ]; then
    echo "GATE FAILED — abandon fine-tuning per docs/12." >&2
    exit 1
  fi
  log "Day-2 gate PASSED"
fi

# --- 6. phase: prep (download xBD + crop + split + format) ---
if [ "$PHASE" = "prep" ] || [ "$PHASE" = "all" ]; then
  XBD_RAW="$DATA_DIR/xbd_raw"
  XBD_UNPACKED="$DATA_DIR/xbd"
  PATCHES_DIR="$DATA_DIR/patches"
  MANIFEST="$DATA_DIR/manifest.json"
  GEMMA_DIR="$DATA_DIR/xbd_gemma"

  mkdir -p "$XBD_RAW" "$XBD_UNPACKED"

  log "downloading xBD train+test from Kaggle (tunguz/xview2-challenge-dataset-train-and-test)"
  cd "$XBD_RAW"
  uv run kaggle datasets download -d tunguz/xview2-challenge-dataset-train-and-test --unzip -p .
  log "downloading xBD tier3 from Kaggle (tunguz/xview2-challenge-dataset-tier-3-data)"
  uv run kaggle datasets download -d tunguz/xview2-challenge-dataset-tier-3-data --unzip -p .
  cd "$WORK_DIR/gemma-guardian"

  log "running crop_patches"
  uv run --extra ml python -m ml.data_prep.crop_patches --xbd-root "$XBD_RAW" --out "$PATCHES_DIR"

  log "running split_dataset"
  uv run --extra ml python -m ml.data_prep.split_dataset --patches "$PATCHES_DIR" --out-manifest "$MANIFEST"

  log "running format_for_gemma"
  uv run --extra ml python -m ml.data_prep.format_for_gemma --manifest "$MANIFEST" --out-dir "$GEMMA_DIR"
  log "prep complete; train.jsonl at $GEMMA_DIR/train.jsonl"
fi

# --- 7. phase: train ---
if [ "$PHASE" = "train" ] || [ "$PHASE" = "all" ]; then
  GEMMA_DIR="${GEMMA_DIR:-$DATA_DIR/xbd_gemma}"
  RUN_NAME="${RUN_NAME:-xbd_e2b_lora_$(date -u +%Y%m%d_%H%M)}"
  log "=== LoRA training (docs/12 defaults: rank=32, all-linear, vision_layers=False) ==="
  uv run python ml/training/finetune_lora.py \
    --data-dir "$GEMMA_DIR" \
    --run-name "$RUN_NAME" \
    --epochs "${EPOCHS:-1}" \
    --batch-size "${BATCH_SIZE:-2}" \
    --grad-accum "${GRAD_ACCUM:-4}" \
    --max-hours "${MAX_HOURS:-6}" \
    2>&1 | tee "$WORK_DIR/finetune_${RUN_NAME}.log"
  log "training complete; adapter at ml/adapters/$RUN_NAME/"
fi

log "bootstrap DONE (phase=$PHASE)"
