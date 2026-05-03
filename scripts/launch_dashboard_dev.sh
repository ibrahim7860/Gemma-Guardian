#!/usr/bin/env bash
# Phase 1A development launcher: starts the WebSocket bridge for dashboard work.
# Usage: ./scripts/launch_dashboard_dev.sh
# Prerequisite: pip install -r frontend/ws_bridge/requirements.txt
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="${PYTHONPATH:-.}:."
echo "Starting FastAPI WebSocket bridge on ws://localhost:9090 ..."
echo "Health check: http://localhost:9090/health"
echo "Stop with Ctrl+C."
exec python3 -m uvicorn frontend.ws_bridge.main:app --port 9090 --log-level info
