# Runbook: MCP browser verification of finding DOM render

**Purpose:** drive the running FieldAgent stack via Playwright MCP, capture
a screenshot of a real finding rendered in the Flutter dashboard. Used for
demo-video capture and as a sanity check before any submission.

**Last verified:** 2026-05-06. Reference asset: `docs_assets/dashboard-finding-rendered.png`.

## Prerequisites

- Playwright MCP installed and connected (verify: `mcp__playwright__browser_navigate` tool available in your Claude Code session).
- Ollama daemon running on `http://127.0.0.1:11434` with `gemma4:e2b` pulled (only required for the LIVE Gemma path; the MOCK path skips this).
- `redis-server` available (`brew install redis` on macOS).
- Flutter web bundle already built: `cd frontend/flutter_dashboard && /path/to/flutter build web --release`. The bundle output goes to `frontend/flutter_dashboard/build/web/` (gitignored).
- The dashboard's `main.dart` must be the version that accepts `?ws=` query overrides (commit `471605a` or later — check `_wsBridgeUrl()` is present in `frontend/flutter_dashboard/lib/main.dart`).

## Two paths — pick one

- **MOCK path (default for the demo recording):** uses `scripts/ollama_mock_server.py`. The first call to `/api/chat` returns a canned `report_finding` (type=victim, severity=4, conf=0.78); subsequent calls return `continue_mission`. Deterministic; ~1 second from agent start to finding visible. Use this for the demo video.
- **LIVE path (truthful but slower):** uses real `gemma4:e2b` via Ollama. Pre-warm with `curl http://127.0.0.1:11434/api/chat -d '{"model":"gemma4:e2b","stream":false,"messages":[{"role":"user","content":"hi"}]}'` (~16 s cold load), then drone1 fires `report_finding` consistently during ticks 61–90 of `disaster_zone_v1` (≈30–45 s into the run). See `docs/sim-live-run-notes.md` for the empirical data (5 successful firings, 2026-05-06).

## Procedure

### 1. Pick free ports + log dir

```bash
DEMO_DIR=/tmp/gg_demo_$(date +%s)
mkdir -p "$DEMO_DIR"
# Pick a free port for each component
python3 -c "
import socket
for tag in ['REDIS', 'OLLAMA', 'BRIDGE', 'FLUTTER']:
    s = socket.socket(); s.bind(('127.0.0.1', 0))
    print(f'{tag}={s.getsockname()[1]}'); s.close()
" > "$DEMO_DIR/ports.env"
source "$DEMO_DIR/ports.env"
```

### 2. Start redis (daemonized)

```bash
redis-server --port $REDIS --save "" --appendonly no \
             --daemonize yes --logfile "$DEMO_DIR/redis.log"
redis-cli -p $REDIS ping  # expect PONG
```

### 3. Start mock Ollama (skip for LIVE path; use real Ollama on 11434 instead)

```bash
nohup uv run python scripts/ollama_mock_server.py --port $OLLAMA \
      > "$DEMO_DIR/ollama.log" 2>&1 &
sleep 1
curl -s "http://127.0.0.1:$OLLAMA/api/tags"  # expect {"models":[...]}
```

For LIVE path instead: keep your real Ollama daemon on 11434, set `OLLAMA=11434` in `$DEMO_DIR/ports.env`.

### 4. Start sim + drone agent + bridge + flutter http server

```bash
cd /path/to/Gemma-Guardian

# Sim (waypoint + frame)
nohup uv run python -m sim.waypoint_runner --scenario disaster_zone_v1 \
      --redis-url redis://127.0.0.1:$REDIS/0 > "$DEMO_DIR/waypoint.log" 2>&1 &
nohup uv run python -m sim.frame_server --scenario disaster_zone_v1 \
      --redis-url redis://127.0.0.1:$REDIS/0 > "$DEMO_DIR/frame.log" 2>&1 &

# Drone agent (uses our chosen ollama endpoint — mock or real)
nohup uv run python -m agents.drone_agent --drone-id drone1 \
      --scenario disaster_zone_v1 \
      --redis-url redis://127.0.0.1:$REDIS/0 \
      --ollama-endpoint http://127.0.0.1:$OLLAMA \
      > "$DEMO_DIR/agent.log" 2>&1 &

# Bridge
REDIS_URL="redis://127.0.0.1:$REDIS/0" nohup uv run python -m uvicorn \
      frontend.ws_bridge.main:app --host 127.0.0.1 --port $BRIDGE \
      > "$DEMO_DIR/bridge.log" 2>&1 &

# Static-serve the built Flutter bundle
( cd frontend/flutter_dashboard/build/web && \
  nohup python3 -m http.server $FLUTTER --bind 127.0.0.1 \
        > "$DEMO_DIR/flutter.log" 2>&1 ) &

sleep 5  # let everything boot
```

### 5. Drive Playwright MCP from a Claude Code session

In a Claude session, run these MCP tool calls in order:

1. `mcp__playwright__browser_navigate` → `http://127.0.0.1:<FLUTTER>/?ws=ws://127.0.0.1:<BRIDGE>/`
2. `mcp__playwright__browser_wait_for` → `time: 5` (let the dashboard connect to the bridge and receive its initial `state_update` envelope)
3. `mcp__playwright__browser_snapshot` → confirm the accessibility tree contains a `group "VICTIM ..."` entry inside the `Findings` panel
4. `mcp__playwright__browser_take_screenshot` → save to `docs_assets/dashboard-finding-rendered.png`

Substitute `<FLUTTER>` and `<BRIDGE>` with the actual port numbers from `$DEMO_DIR/ports.env`.

### 6. Verify the screenshot shows

- A finding tile in the Findings panel labeled `VICTIM (severity 4, conf 0.78)`.
- A timestamp + visual description below the title (`person prone in rubble, partial cover` for the mock path).
- `APPROVE` (green) and `DISMISS` (outlined) buttons on the right of the tile.
- Top-right header reads `v<contract-version> · connected`.
- Map panel shows three drones positioned in the area (drone1 in upper-left, drone2/drone3 to the right).

### 7. Tear down

```bash
# Kill the children we started
for pidline in $(cat "$DEMO_DIR/pids.txt" 2>/dev/null); do
  kill -TERM "${pidline##*=}" 2>/dev/null
done
# Or by name (if pids.txt wasn't tracked)
pkill -f "agents.drone_agent"
pkill -f "sim.waypoint_runner"
pkill -f "sim.frame_server"
pkill -f "ollama_mock_server"
pkill -f "uvicorn frontend.ws_bridge"
# Stop our redis
redis-cli -p $REDIS SHUTDOWN NOSAVE
```

## Recovering from common failures

- **`mcp__playwright__browser_navigate` hangs:** Flutter `build/web/` may not exist, or `http.server` is on the wrong port. Curl the URL first: `curl -I http://127.0.0.1:$FLUTTER/`.
- **No finding tile appears (Findings panel says "no findings yet"):**
  - With MOCK Ollama: the agent must still be running. Check `tail -10 $DEMO_DIR/agent.log` for the boot message; check `tail -5 /tmp/gemma_guardian_logs/validation_events.jsonl` for tool calls. If the first event is `report_finding` but the dashboard shows nothing, the bridge may not be psubscribing — check `bridge.log` for "WebSocket / accepted".
  - With LIVE Ollama: remember Gemma needs ~16 s cold-load; the disaster image window is only 15 s wide. Pre-warm Ollama before starting the agent.
- **Dashboard shows a connection-status `reconnecting in Ns` instead of `connected`:** the dashboard is hitting the wrong WS URL. Verify the `?ws=ws://127.0.0.1:<BRIDGE>/` query parameter matches the running bridge port.
- **Screenshot shows blank canvas:** Flutter is rendering, but the page is in a degenerate state. Run `mcp__playwright__browser_console_messages` to inspect the JS console — most often a WS connection error.
- **Findings panel shows the tile but APPROVE/DISMISS aren't visible:** browser viewport too narrow. Default Playwright viewport is 1280×720; widen via `mcp__playwright__browser_resize` if needed.