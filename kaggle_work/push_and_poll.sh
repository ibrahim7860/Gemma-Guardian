#!/usr/bin/env bash
# Push the Kaggle kernel, poll status every 60s, pull output when done.
#
# Usage:
#   bash kaggle_work/push_and_poll.sh                     # uses kaggle_work/ as kernel folder
#   bash kaggle_work/push_and_poll.sh ./other_folder      # override
#
# Exit codes:
#   0  kernel completed successfully, output pulled into kaggle_out/
#   1  push failed (auth, dataset attach, metadata)
#   2  kernel ran but reported error in logs
#   3  poll timed out after 13 hours (12-hr kernel cap + 1 hr buffer)

set -euo pipefail

FOLDER="${1:-kaggle_work}"
META="$FOLDER/kernel-metadata.json"

if [[ ! -f "$META" ]]; then
    echo "ERROR: $META not found." >&2
    exit 1
fi

# Pull kernel slug from metadata.
SLUG=$(python3 -c "import json; print(json.load(open('$META'))['id'])")
echo "Kernel slug: $SLUG"
echo "Folder:      $FOLDER"
echo "Pushing..."

if ! uv run kaggle kernels push -p "$FOLDER" 2>&1 | tee /tmp/kaggle_push.log; then
    echo "ERROR: kernel push failed. See /tmp/kaggle_push.log" >&2
    exit 1
fi

echo
echo "Polling status every 60s (Ctrl-C to detach; kernel keeps running)..."
START_TS=$(date +%s)
DEADLINE=$((START_TS + 13 * 3600))

while true; do
    NOW=$(date +%s)
    if (( NOW > DEADLINE )); then
        echo "ERROR: poll deadline exceeded (13h). Kernel may still be running on Kaggle." >&2
        exit 3
    fi

    STATUS_OUT=$(uv run kaggle kernels status "$SLUG" 2>&1 || true)
    echo "[$(date +%H:%M:%S)] $STATUS_OUT"

    # kaggle CLI prints e.g. 'has status "complete"' or 'has status "error"'.
    case "$STATUS_OUT" in
        *'"complete"'*|*'has status complete'*)
            echo "Kernel complete. Pulling output..."
            mkdir -p kaggle_out
            uv run kaggle kernels output "$SLUG" -p ./kaggle_out
            echo "Output in ./kaggle_out/"
            exit 0
            ;;
        *'"error"'*|*'has status error'*|*'"failed"'*)
            echo "Kernel reported error. Pulling logs anyway..." >&2
            mkdir -p kaggle_out
            uv run kaggle kernels output "$SLUG" -p ./kaggle_out 2>&1 || true
            exit 2
            ;;
        *'"queued"'*|*'"running"'*|*'has status running'*|*'has status queued'*)
            sleep 60
            ;;
        *)
            # Unknown status string; back off and retry.
            sleep 60
            ;;
    esac
done
