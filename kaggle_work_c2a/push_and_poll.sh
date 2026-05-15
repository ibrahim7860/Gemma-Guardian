#!/usr/bin/env bash
# Push the C2A victim-detection kernel, poll until complete, pull output.
set -euo pipefail

FOLDER="${1:-kaggle_work_c2a}"
META="$FOLDER/kernel-metadata.json"
[ -f "$META" ] || { echo "ERROR: $META not found" >&2; exit 1; }

SLUG=$(python3 -c "import json; print(json.load(open('$META'))['id'])")
echo "Kernel slug: $SLUG"
echo "Folder:      $FOLDER"
echo "Pushing..."

if ! uv run kaggle kernels push -p "$FOLDER" --accelerator NvidiaTeslaT4 2>&1 | tee /tmp/kaggle_push_c2a.log; then
    echo "ERROR: kernel push failed" >&2
    exit 1
fi

echo
echo "Polling..."
START=$(date +%s); DEADLINE=$((START + 13*3600))
while true; do
    NOW=$(date +%s); (( NOW > DEADLINE )) && { echo "TIMEOUT"; exit 3; }
    OUT=$(uv run kaggle kernels status "$SLUG" 2>&1 || true)
    echo "[$(date +%H:%M:%S)] $OUT"
    case "$OUT" in
        *COMPLETE*|*'"complete"'*)
            mkdir -p kaggle_out_c2a
            uv run kaggle kernels output "$SLUG" -p ./kaggle_out_c2a
            exit 0 ;;
        *ERROR*|*'"error"'*|*FAILED*)
            mkdir -p kaggle_out_c2a
            uv run kaggle kernels output "$SLUG" -p ./kaggle_out_c2a 2>&1 || true
            exit 2 ;;
    esac
    sleep 60
done
