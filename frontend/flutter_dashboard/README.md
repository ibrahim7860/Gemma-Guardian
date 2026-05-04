# FieldAgent Operator Dashboard

Flutter web app that consumes the FastAPI WebSocket bridge at `ws://localhost:9090`
and renders a live operator surface for the FieldAgent multi-drone simulation.

## Prerequisites

- Flutter SDK (Dart 3.11+)
- Python 3.11+ with bridge deps installed (`uv sync --extra ws_bridge --extra dev`)
- `redis-server` running locally (`brew services start redis` or `sudo systemctl start redis`)

## Run the full stack (one command)

From repo root:

```bash
./scripts/run_dashboard_dev.sh
```

This starts:
- FastAPI bridge on `ws://localhost:9090` (and HTTP health on `/health`)
- Fake Redis producers publishing drone state, EGS state, and findings
- `dev_actions_logger.py` subscribed to `egs.operator_actions` (so you can see operator approvals land on Redis)
- Flutter web dev server on `http://localhost:8000` (auto-launches in Chrome)

Ctrl-C cleans everything up.

## Run tests

Python (bridge + contracts):

```bash
PYTHONPATH=. pytest frontend/ws_bridge/tests/ shared/tests/ -v -m "not e2e"
```

Flutter widget tests:

```bash
cd frontend/flutter_dashboard && flutter test
```

Playwright e2e:

```bash
PYTHONPATH=. pytest frontend/ws_bridge/tests/test_e2e_phase3.py -v -m e2e
```

## Layout

Four panels in a 2×2 grid:
- **Map** — drone positions and findings as markers, equirectangular projection
- **Drone Status** — battery, task, findings count, validation failures
- **Findings** — newest-first list with APPROVE / DISMISS buttons
- **Command** — multilingual command box (DISPATCH stubbed for Phase 4)
