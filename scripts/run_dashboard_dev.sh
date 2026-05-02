#!/usr/bin/env bash
# Phase 3 dev launcher: starts the FastAPI bridge, fake producers, the
# dev_actions_logger, and the Flutter web dev server in dependent order.
# Single trap teardown so Ctrl-C cleans everything up.
#
# Prereqs:
#   - redis-server already running (brew services start redis / systemctl)
#   - python deps installed (pip install -r frontend/ws_bridge/requirements.txt)
#   - flutter on PATH
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

cleanup() {
  echo "[run_dashboard_dev] tearing down..."
  jobs -p | xargs -r kill 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

# 1. Redis check
if ! redis-cli ping > /dev/null 2>&1; then
  echo "ERROR: redis-server is not running." >&2
  echo "  macOS: brew services start redis" >&2
  echo "  Linux: sudo systemctl start redis" >&2
  exit 1
fi

# 2. Port check
for port in 9090 8000; do
  if lsof -ti:$port > /dev/null 2>&1; then
    echo "ERROR: port $port is busy. Free it before running run_dashboard_dev.sh." >&2
    echo "  Find owner: lsof -i:$port" >&2
    exit 1
  fi
done

echo "[run_dashboard_dev] starting bridge on :9090..."
PYTHONPATH=. python3 -m uvicorn frontend.ws_bridge.main:app --host 127.0.0.1 --port 9090 &

echo "[run_dashboard_dev] starting fake producers..."
PYTHONPATH=. python3 scripts/dev_fake_producers.py --tick-s 1.0 &

echo "[run_dashboard_dev] starting dev_actions_logger..."
PYTHONPATH=. python3 scripts/dev_actions_logger.py &

# Give the bridge a moment to bind before Flutter tries to connect.
sleep 1

echo "[run_dashboard_dev] starting Flutter web on :8000..."
cd frontend/flutter_dashboard
flutter run -d chrome --web-port=8000 --web-hostname=127.0.0.1
