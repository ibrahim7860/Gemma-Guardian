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

### 4. Start EGS + sim + drone agent + bridge + flutter http server

The EGS is what publishes `egs.state` (Contract 3), including the
optional `base_image_path` + `base_image_extents` that the post-PR-#36
`map_panel.dart` needs in order to render the FEMA aerial overlay
(`docs/plans/2026-05-08-thayyil-fixtures-swap.md` Task 8). Without
EGS in this stack the map renders grid-only via the `errorBuilder`
fallback — visually indistinguishable from the aerial-loaded state in a
thumbnail, but a wrong demo capture. Always start EGS first so its
1 Hz publisher is live before the dashboard connects.

The EGS reads `transport.redis_url` from `shared/config.yaml`, but
honors the `REDIS_URL` env override (added 2026-05-08, see
`shared/tests/test_config.py::test_redis_url_env_override`). Pass the
override on the EGS launch line — without it the EGS lands on
`localhost:6379` regardless of `$REDIS`, splitting the bus from the
producers/bridge below.

```bash
cd /path/to/Gemma-Guardian

# EGS — publishes egs.state at 1Hz; required for the aerial overlay.
REDIS_URL="redis://127.0.0.1:$REDIS/0" nohup uv run python -m agents.egs_agent.main \
      > "$DEMO_DIR/egs.log" 2>&1 &
sleep 3  # let EGS attach to redis + start the 1Hz publisher

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

**Sanity probe before driving Playwright:** confirm the bridge sees
the EGS-published aerial path so the map_panel will actually request
the asset:

```bash
uv run python -c "
import asyncio, websockets, json
async def probe():
    async with websockets.connect('ws://127.0.0.1:$BRIDGE/') as ws:
        d = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        egs = d.get('egs_state', {})
        assert egs.get('base_image_path'), \\
            f'EGS not publishing base_image_path; map will render grid-only. got={egs!r}'
        print('OK: base_image_path =', egs['base_image_path'])
asyncio.run(probe())
"
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
pkill -f "agents.egs_agent"
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
- **Findings panel shows the tile but APPROVE/DISMISS aren't visible:** browser viewport too narrow. Default Playwright MCP viewport is around 1440×673 in current builds; widen via `mcp__playwright__browser_resize` if your local default is narrower.
- **Map panel renders grid-only, no aerial visible (post-PR-#36):** the bridge is forwarding `egs_state.base_image_path = null`, which fires `map_panel.dart`'s `errorBuilder` fallback. Two known causes:
  1. **No EGS in the stack:** Procedure §4 above lists EGS first for a reason. Without it, no process publishes `egs.state`, so the field is null. Confirm the §4 sanity probe passed.
  2. **EGS connected to the wrong redis:** the EGS reads `transport.redis_url` from `shared/config.yaml` (defaults to `localhost:6379`). For ephemeral-redis paths, you MUST set `REDIS_URL=redis://127.0.0.1:$REDIS/0` on the EGS launch line. Without the env override the EGS publishes on `localhost:6379` while the bridge listens on `$REDIS` — split bus, no aerial. (Fix added 2026-05-08; see `shared/contracts/config.py` env-override docstring.)
- **Ollama returns HTTP 500 `model failed to load, resource limitations` after a Mac crash / hard reboot:** despite the message, this is usually NOT a memory problem — the macOS Metal compiler service is in a stuck state from the abnormal shutdown. Symptom: Console shows `Unable to reach MTLCompilerService ... Reentrancy avoided`; `ollama list` displays the models correctly; `ollama run <tag>` hangs or 500s on first chat call. The following did NOT work in our 2026-05-09 incident (Apple Silicon M1, macOS 26.4.1, Ollama 0.23.1): clearing `/var/folders/.../com.apple.metal/` shader cache, `pkill -f MTLCompilerService`, `brew services restart ollama`. The fix that did work, without needing another reboot:
  ```bash
  brew services stop ollama
  brew reinstall ollama          # pulls a fresh binary with a clean precompiled Metal library
  brew services start ollama
  # Pre-warm to confirm:
  curl -X POST http://127.0.0.1:11434/api/chat \
       -d '{"model":"gemma4:e4b","stream":false,"messages":[{"role":"user","content":"ok"}]}'
  ```
  Cold-load on Apple Silicon: ~99 s for E4B, ~16 s for E2B post-reinstall — both within our 120 s default `ReasoningNode.timeout_s`. If the reinstall still 500s, only then suspect actual memory pressure (E2B 7.2 GB + E4B 9.6 GB = 16.8 GB, borderline on a 16 GB Mac with both loaded simultaneously) and run only one at a time.

## Beat 4 capture path — `EGS LINK SEVERED` + `STANDALONE MODE ACTIVE`

**Last verified:** 2026-05-07. Reference asset: `docs_assets/dashboard-egs-severed.png`.

The Beat 4 dashboard signals (banner + badge) need a stack that publishes `egs_state` exactly once and then stops. The full integrated stack republishes at 1 Hz, so we use a tiny synthetic WebSocket server in lieu of redis + sim + bridge for capture-only purposes. This is the same pattern as `frontend/ws_bridge/tests/test_e2e_playwright_standalone_mode.py`.

### 1. Pick free ports + log dir

```bash
DEMO_DIR=/tmp/gg_beat4_capture
mkdir -p "$DEMO_DIR"
python3 -c "
import socket
for tag in ['WS', 'FLUTTER']:
    s = socket.socket(); s.bind(('127.0.0.1', 0))
    print(f'{tag}={s.getsockname()[1]}'); s.close()
" > "$DEMO_DIR/ports.env"
source "$DEMO_DIR/ports.env"
```

### 2. Drop the synthetic WS server

Save this to `$DEMO_DIR/synth_ws.py` — sends one `state_update` envelope with `egs_state` populated and `drone3` in `agent_status="standalone"`, then holds open without further publishes:

```python
import asyncio, json, sys
import websockets

PORT = int(sys.argv[1])
ENVELOPE = {
    "type": "state_update",
    "timestamp": "2026-05-07T10:00:00.000Z",
    "contract_version": "1.0.0",
    "egs_state": {
        "mission_id": "beat4_demo", "mission_status": "active",
        "timestamp": "2026-05-07T10:00:00.000Z",
        "zone_polygon": [[34.123, -118.568], [34.124, -118.568],
                          [34.124, -118.567], [34.123, -118.567]],
        "survey_points": [], "drones_summary": {},
        "findings_count_by_type": {"victim": 0, "fire": 0, "smoke": 0,
                                    "damaged_structure": 0, "blocked_route": 0},
        "recent_validation_events": [], "active_zone_ids": [],
    },
    "active_findings": [],
    "active_drones": [
        {"drone_id": "drone1", "agent_status": "active",     "battery_pct": 88, "current_task": "survey", "findings_count": 0, "validation_failures_total": 0},
        {"drone_id": "drone2", "agent_status": "returning",  "battery_pct": 71, "current_task": "rtb",    "findings_count": 2, "validation_failures_total": 1},
        {"drone_id": "drone3", "agent_status": "standalone", "battery_pct": 62, "current_task": "survey", "findings_count": 1, "validation_failures_total": 0},
    ],
}

async def handler(ws):
    await ws.send(json.dumps(ENVELOPE))
    try:
        async for _ in ws: pass
    except Exception: return

async def main():
    async with websockets.serve(handler, "127.0.0.1", PORT):
        await asyncio.Future()

asyncio.run(main())
```

### 3. Boot synth WS + Flutter static server

```bash
cd /path/to/Gemma-Guardian
# Pre-build the dashboard (if you haven't)
cd frontend/flutter_dashboard && flutter build web --release && cd -

nohup uv run python "$DEMO_DIR/synth_ws.py" $WS > "$DEMO_DIR/synth_ws.log" 2>&1 &
( cd frontend/flutter_dashboard/build/web && \
  nohup python3 -m http.server $FLUTTER --bind 127.0.0.1 \
        > "$DEMO_DIR/flutter.log" 2>&1 ) &
sleep 2
curl -sI "http://127.0.0.1:$FLUTTER/" | head -1   # expect 200
```

### 4. Drive Playwright MCP from a Claude session

1. `mcp__playwright__browser_navigate` → `http://127.0.0.1:<FLUTTER>/?ws=ws://127.0.0.1:<WS>/`
2. `mcp__playwright__browser_wait_for` → `time: 8` (5 s heartbeat staleness window + 1 Hz Timer slack + a generous CanvasKit boot margin)
3. `mcp__playwright__browser_take_screenshot` → save to `docs_assets/dashboard-egs-severed.png` with `fullPage: true`

### 5. Verify the screenshot shows

- A red `EGS LINK SEVERED — drones operating in standalone mode` banner pinned to the top of the body, below the AppBar.
- The Drone Status panel listing all three drones, with `drone3 — standalone` carrying the orange `STANDALONE` badge on the right side of its title row.
- The header still reading `v<contract-version> · connected` — the WS itself is up; only the EGS heartbeat went stale.

### 6. Tear down

```bash
pkill -f "synth_ws.py"
pkill -f "http.server $FLUTTER"
```

## Beat 3 EGS-findings-count capture — `findings_count_by_type` lit by live drone

**Last verified:** stub — manual capture pending. Reference asset
(target): `docs_assets/dashboard-egs-state-counts.png`.

**Purpose:** capture a screenshot of the dashboard's findings-count chips
lit up by a live drone-agent finding (or, as a stand-in, by
`scripts/dev_fake_producers.py --emit=findings`) flowing through the real
EGS process into `egs.state.findings_count_by_type`. This is the GATE 2
acceptance asset for Qasim's EGS path: the polygon is scenario-derived,
the counts are real, the dashboard reflects what the EGS published.

The fully-automated equivalent (sans screenshot save) lives at
`frontend/ws_bridge/tests/test_e2e_playwright_egs_findings.py`; this
runbook section is the manual MCP-driven version used for the demo asset.

### 1. Pick free ports + log dir

```bash
DEMO_DIR=/tmp/gg_beat3_capture
mkdir -p "$DEMO_DIR"
python3 -c "
import socket
for tag in ['BRIDGE', 'FLUTTER']:
    s = socket.socket(); s.bind(('127.0.0.1', 0))
    print(f'{tag}={s.getsockname()[1]}'); s.close()
" > "$DEMO_DIR/ports.env"
source "$DEMO_DIR/ports.env"
```

### 2. Boot order

System Redis must already be running and own port 6379 (the EGS,
drone agent, and bridge all default to it):

```bash
redis-cli ping  # expect PONG; if not, brew services start redis (or apt/systemctl)
```

Then start the rest in order — EGS first so it's subscribed before any
finding lands:

```bash
cd /path/to/Gemma-Guardian

# 1) EGS — owns egs.state publishes + findings aggregation.
nohup uv run python -m agents.egs_agent.main \
      > "$DEMO_DIR/egs.log" 2>&1 &
sleep 2  # let the subscriber attach before findings arrive

# 2a) Live path: real drone agent (requires Ollama up with gemma4:e2b).
nohup uv run python -m agents.drone_agent --drone-id drone1 \
      --scenario disaster_zone_v1 \
      > "$DEMO_DIR/agent.log" 2>&1 &
# 2b) Stand-in path: dev_fake_producers emits one Contract-4 finding.
#     Use this if Ollama isn't pre-warmed or you want a deterministic
#     capture window.
# nohup uv run python scripts/dev_fake_producers.py --emit=findings \
#       --drone-id drone1 > "$DEMO_DIR/fake.log" 2>&1 &

# 3) Bridge.
nohup uv run python -m uvicorn frontend.ws_bridge.main:app \
      --host 127.0.0.1 --port $BRIDGE \
      > "$DEMO_DIR/bridge.log" 2>&1 &

# 4) Flutter static server (pre-built bundle).
( cd frontend/flutter_dashboard/build/web && \
  nohup python3 -m http.server $FLUTTER --bind 127.0.0.1 \
        > "$DEMO_DIR/flutter.log" 2>&1 ) &

sleep 5
```

Confirm the EGS actually consumed the finding before screenshotting:

```bash
tail -F "$DEMO_DIR/egs.log" | grep "egs.findings accepted"
```

### 3. Drive Playwright MCP from a Claude session

1. `mcp__playwright__browser_navigate` → `http://127.0.0.1:<FLUTTER>/?ws=ws://127.0.0.1:<BRIDGE>/`
2. `mcp__playwright__browser_wait_for` → `time: 6` (let `egs.state` arrive on the next 1 Hz publish + Flutter render)
3. `mcp__playwright__browser_snapshot` → confirm the accessibility tree exposes the count chips
4. `mcp__playwright__browser_take_screenshot` → save to `docs_assets/dashboard-egs-state-counts.png` with `fullPage: true`

### 4. Verify the rendered DOM contains

- At least one `[flt-semantics-identifier^="finding-tile-"]` node (proves the
  Findings panel rendered the bridge's forwarded Contract-4 envelope).
- A `[flt-semantics-identifier="findings-count-victim"]` node (or whichever
  type the rotation produced — `findings-count-fire`, `findings-count-smoke`,
  `findings-count-damaged_structure`, `findings-count-blocked_route`)
  with a numeric value `>= 1`.
- Header reads `v<contract-version> · connected`.
- Map panel polygon outline encloses the drone marker(s) — the
  scenario-derived bbox at work.

### 5. Tear down

```bash
pkill -f "agents.egs_agent.main"
pkill -f "agents.drone_agent"
pkill -f "dev_fake_producers"
pkill -f "uvicorn frontend.ws_bridge"
pkill -f "http.server $FLUTTER"
```

The screenshot file `docs_assets/dashboard-egs-state-counts.png` is
captured manually by Ibrahim or Qasim during a demo-prep pass; it is
not yet committed.

## Beat 5 offline-proof capture path — disconnection-tolerant findings

**Last verified:** stub — capture pending Day 12 demo-prep pass.
Reference asset (target): `docs_assets/beat5-offline-proof.mp4`.

**Purpose:** capture a screen recording of the storyboard's Beat 5
mechanics table (`docs/21-demo-storyboard.md`, Beat 5 frame-by-frame)
running against the real integrated stack — sim, mesh sim, EGS, three
drone agents, bridge, dashboard — with a 60 s window during which
drone3 is severed from the EGS, produces a `report_finding` while
standalone, and on reconnect replays that finding into the EGS where
it ticks the `findings_count_by_type.victim` chip exactly once. The
final screen capture must include both the in-stack `egs_link_drop`
event (which severs drone3 → EGS findings delivery in the wire-level
sense — see `agents/mesh_simulator/main.py` `apply_scripted_event`)
AND a real WAN-down moment driven by the operator (the
"airplane-mode" tile of the offline proof).

The fully automated equivalents — minus the screen recording — live
at:
- `frontend/ws_bridge/tests/test_e2e_playwright_beat5_offline_recovery.py` (synth-WS-driven; verifies the dashboard renders banner → badge → finding tile across the timeline with stable Semantics identifiers)
- `agents/egs_agent/tests/test_e2e_link_drop_replay.py` (real-redis e2e against an ephemeral `fakeredis` broker; verifies the wire-level buffer-and-replay invariants)

Both must be green before scheduling a capture pass. This runbook is
the manual MCP-driven version used to produce the demo asset.

### 1. Pick free ports + log dir

The capture-rig orchestrator does this for you, but the manual path
mirrors the Beat 3 / Beat 4 sections above:

```bash
DEMO_DIR=/tmp/gg_beat5_capture
mkdir -p "$DEMO_DIR"
python3 -c "
import socket
for tag in ['REDIS', 'BRIDGE', 'FLUTTER']:
    s = socket.socket(); s.bind(('127.0.0.1', 0))
    print(f'{tag}_PORT={s.getsockname()[1]}'); s.close()
" > "$DEMO_DIR/ports.env"
source "$DEMO_DIR/ports.env"
```

### 2. Pre-warm Ollama

The Beat 5 take is long (240 s of scripted timeline) and the cold-load
penalty for E4B (~99 s on Apple Silicon — see this runbook's
"Recovering from common failures" section) bleeds into the
ofline-proof window if the EGS is the first caller. Pre-warm both
models BEFORE you hit record:

```bash
for MODEL in "gemma4:e2b" "gemma4:e4b"; do
  curl -fsS -X POST http://127.0.0.1:11434/api/chat \
       --max-time 180 \
       -H 'content-type: application/json' \
       -d "{\"model\":\"$MODEL\",\"stream\":false,\"messages\":[{\"role\":\"user\",\"content\":\"ok\"}]}" \
       > "$DEMO_DIR/prewarm_${MODEL//:/}.log"
done
```

### 3. Boot order

The capture rig encapsulates the orchestration; the one-liner is:

```bash
bash scripts/run_beat5_capture.sh
```

This script:
1. Picks free ports for `REDIS_PORT`, `BRIDGE_PORT`, `FLUTTER_PORT` and writes them to `$DEMO_DIR/ports.env`.
2. Pre-warms Ollama (E2B + E4B) — skip with `--no-prewarm` if pointing at `scripts/ollama_mock_server.py`.
3. Starts an ephemeral `redis-server` on the chosen port.
4. Launches `agents/mesh_simulator` (with `--egs-lat 34.0000 --egs-lon -118.5000` so the geometric gate is meaningful), `agents/egs_agent.main`, `sim/waypoint_runner.py`, `sim/frame_server.py`, three drone agents (drone1, drone2, drone3), the WS bridge, and a `python3 -m http.server` for the Flutter web bundle.
5. Pre-flight settles for ~3 s, then prints a "READY TO RECORD" banner + the dashboard URL + the wifi-drop / wifi-restore command snippets for both macOS and Linux + the connectivity-probe one-liner (see §4 below).
6. Starts a foreground 1 Hz scenario-tick pacer that prints `scenario_tick=<N>s` until t=240 (mission_complete).

The locked scenario is `resilience_v1`; the script does not accept a scenario flag.

### 4. Operator opens two terminal panes

**Pane A — command shell** runs the wifi-drop and wifi-restore commands when the pacer prints the right tick:

```bash
# macOS:
sudo ifconfig en0 down                    # at scenario t≈100
sudo ifconfig en0 up                      # at scenario t≈190

# Linux (substitute your interface, often wlan0 or wlp3s0):
sudo ip link set wlan0 down               # at scenario t≈100
sudo ip link set wlan0 up                 # at scenario t≈190
```

**Pane B — connectivity-probe loop** runs the verbatim one-liner that proves WAN is gone (printed in the rig's READY banner; reproduced here for searchability):

```bash
while true; do
  printf '%(%H:%M:%S)T  ' -1
  if curl -fsS --max-time 1 https://www.google.com > /dev/null; then
    echo "WAN: up"
  else
    echo "WAN: DOWN"
  fi
  sleep 1
done
```

Why both? The in-sim `egs_link_drop` event at t=120 is the load-bearing offline-proof marker — it severs drone3 → EGS findings delivery deterministically inside the mesh sim. The operator's WAN drop is the visual seal: viewers see the probe loop go from `WAN: up` to `WAN: DOWN` and the dashboard keeps working.

### 5. Operator drops wifi at scenario t≈100; brings it up at t≈190

Watch the pacer; run the wifi-drop command in pane A as the pacer prints `scenario_tick=100s` (anywhere t∈[95, 110] is fine — the in-sim `egs_link_drop` fires at t=120 and that is what actually severs the link). Run the wifi-restore command at scenario t≈190 (anywhere t∈[185, 200]; the in-sim `egs_link_restore` is at t=180 — the WAN-back lag is fine because we're showing recovery from a real network outage).

The pacer exits at t=240 (mission_complete). Stop the screen recording.

### 6. Run `scripts/check_beat5.py` to verify the run is good-to-cut

```bash
uv run python scripts/check_beat5.py \
    --bridge-url ws://127.0.0.1:${BRIDGE_PORT} \
    --validation-log $DEMO_DIR/validation_events.jsonl \
    --deadline-s 30
```

After the stack is torn down (or on a second machine), re-verify the same take from the recorded artifacts alone, with no live bridge required. `scripts/run_beat5_capture.sh` runs `scripts/ws_recorder.py` alongside the bridge during a capture, writing every `state_update` envelope to `$DEMO_DIR/ws_frames.jsonl`:

```bash
uv run python scripts/check_beat5.py \
    --ws-replay-log $DEMO_DIR/ws_frames.jsonl \
    --validation-log $DEMO_DIR/validation_events.jsonl
```

Replay uses the recorded `received_at_s` timestamps so A3/A4 timing semantics are preserved exactly. This is the load-bearing path for the Day 15 two-machine backup verification.

Exit code 0 with all six A-assertions PASS = the take is usable. Non-zero with a table of which A-assertions failed = re-run the scenario. Common failure modes (see the script's per-assertion `detail` text):

- A1 fails (`drone3 never observed in standalone`) → mesh sim wasn't running, or `egs_link_drop` wasn't received, or drone3's `LinkStatusSubscriber` died. Check `$DEMO_DIR/mesh.log` and `$DEMO_DIR/drone3.log` for "subscribed to mesh.link_status".
- A2 fails (`no drone3 report_finding`) → Gemma never produced a `report_finding` for drone3 inside the t∈[120,180] window. Re-run; if persistent, fall back to the MOCK Ollama path via `GG_OLLAMA_URL=http://127.0.0.1:<mock-port>` + `scripts/ollama_mock_server.py`.
- A3/A4 fail (`no count increment after restore` / `>5 s`) → buffer didn't drain (drone3's `_handle_link_event` wasn't called) OR the mesh sim's findings gate didn't relax `_link_down_overrides`. Check `$DEMO_DIR/mesh.log` for "egs_link_restore" log lines.
- A6 fails (`post-restore delta exceeds expected unique-finding count`) → EGS dedup regressed. Should not happen post-Wave-3a; if it does, suspect a bad merge.

### 7. Save the screen recording

Save the OBS / QuickTime capture to `docs_assets/beat5-offline-proof.mp4`. Tear the stack down with:

```bash
bash scripts/run_beat5_capture.sh --teardown
```

This is idempotent — safe to run twice or after a partial earlier failure.