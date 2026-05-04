# Phase 3 — Flutter Dashboard MVP — Design Spec

**Status:** approved 2026-05-02 after `/plan-eng-review` (CLEAR, 11 issues resolved, 0 critical gaps).
**Branch:** `feat/dashboard-mvp`.
**Owner:** Ibrahim (Frontend / Demo / Comms).
**Reviewers:** outside voice ran (Claude subagent; Codex unavailable due to CLI version mismatch). 10 findings; 7 just-do-its incorporated, 3 cross-model decisions resolved.

## Goal

Promote the Flutter dashboard from "renders text-only panels" to a live operator surface:

1. Real map visualization with drone + finding markers, equirectangular projection with `cos(midLat)` correction, locked bounding box plus a manual refit button.
2. APPROVE / DISMISS interactions on findings, ending in a validated Redis publish on a new typed channel `egs.operator_actions`.
3. Two-stage UI feedback (bridge ack → EGS confirmation) so Phase 4's EGS-side approval echo lands without rework.

Phase 3 is read-only on Panels 1–3 plus one outbound interaction (finding approval). Command box stays stubbed. Multilingual command path is Phase 4.

## Non-goals (deferred with rationale)

- Multilingual command box wiring — couples to Qasim's EGS translation path; not yet built.
- Validation event ticker on drone status panel — Day-10 work in roadmap.
- Static aerial base image for map — no asset committed; procedural background fine for now. Tracked in `TODOS.md`.
- EGS-side approval echo back to dashboard — Qasim's Phase 4 work. Two-stage UI is forward-compatible without it.
- Mesh links between drones — Day-11 work.
- `flutter_map` package, OSM tiles — offline system; static base only.
- Map marker tap/hover interactivity — Phase 3 map is read-only.
- EGS subscriber for `egs.operator_actions` — Qasim's Phase 4 seat. Phase 3 publishes the contract; `scripts/dev_actions_logger.py` lets us verify locally.
- Server-side `command_id` dedup — EGS responsibility once it subscribes.

## Architecture

```
┌─────────── Flutter (web/canvaskit) ────────────────────────────────┐
│  MissionState (existing, extended)                                 │
│   ├─ applyStateUpdate           (existing)                         │
│   ├─ sendOutbound(envelope)     ← NEW (writes to WebSocketSink)    │
│   ├─ handleEcho(envelope)       ← NEW (drives state machine)       │
│   ├─ markFinding(id, action)    ← NEW (issues finding_approval)    │
│   ├─ snackbarStream             ← NEW (one-shot UX events)         │
│   └─ _findingActions:           ← NEW (Map<id, _ApprovalState>)    │
│                                                                     │
│  MapPanel       ← REWRITE: pure CustomPaint, no flutter_map        │
│  FindingsPanel  ← extend with APPROVE/DISMISS + 4 visual states    │
│  DroneStatusPanel (no behavior change; widget test added)          │
│  CommandPanel   ← DISPATCH disabled w/ tooltip                     │
└──────────────────────────────────┬─────────────────────────────────┘
                                   │ ws://localhost:9090
                       (state_update ↑   finding_approval / echo ↓↑)
                                   ▼
┌─────────── frontend/ws_bridge/main.py ─────────────────────────────┐
│  Inbound dispatch in ws_endpoint:                                  │
│    operator_command  → echo (existing)                             │
│    finding_approval  → validate                                    │
│                        → RedisPublisher.publish(                   │
│                            "egs.operator_actions", payload)        │
│                        → echo {ack:"finding_approval", ...}        │
│                        OR echo {error:"redis_publish_failed", ...} │
│  All error echoes go through _echo_error(...) (DRY)                │
│                                                                     │
│  RedisSubscriber, StateAggregator, _emit_loop, _ConnectionRegistry │
│  (all unchanged from Phase 2)                                      │
│                                                                     │
│  RedisPublisher (NEW): single instance on app.state.publisher,     │
│    lazy-init via redis.asyncio.from_url, closed in lifespan        │
└──────────────────────────────────┬─────────────────────────────────┘
                                   │
                                   ▼ egs.operator_actions (NEW typed channel)
                              (Redis pub/sub)
                                   │
                                   ▼
                  scripts/dev_actions_logger.py
                  (CLI subscriber for local verification;
                   Qasim's EGS subscriber lands in Phase 4)
```

### State machine: per-finding approval

```
              markFinding(id,"approve"|"dismiss")
                       │
                       ▼
                   ┌──────┐
                   │ idle │
                   └──┬───┘
                      │ user clicks APPROVE / DISMISS
                      ▼
                  ┌───────┐
                  │pending│  (button disabled, spinner inline)
                  └───┬───┘
                      │
            ┌─────────┼─────────────┐
            │         │             │
   echo ack │  echo error │  WS drops while pending
            ▼         ▼             ▼
       ┌─────────┐ ┌────────┐  ┌────────┐
       │received │ │ failed │  │ failed │ + SnackBar "Reconnect: please re-tap"
       │ (grey ✓)│ │(error  │  │        │
       └────┬────┘ │ snack) │  └───┬────┘
            │     └───┬────┘      │
            │         │            │ user re-taps → back to pending
            │  state_update from EGS marks finding approved (Phase 4)
            ▼
       ┌──────────┐
       │confirmed │ (green ✓ + green left border)
       │          │
       └──────────┘

dismissed: parallel branch from pending; visual = strikethrough + 0.5 opacity.

archived: when state_update.active_findings no longer contains an
          approved/dismissed/received finding, the row stays visible with
          a badge "approved — archived from EGS state". Map marker disappears.
```

## Components

### 1. `shared/schemas/operator_actions.json` (NEW)

JSON Schema for payloads on `egs.operator_actions` Redis channel. Discriminated by `kind` so future operator action types (recall, restrict_zone) can land on the same channel.

Required fields per `kind: "finding_approval"`:
- `kind` (`const: "finding_approval"`)
- `command_id` (`{type: "string", minLength: 1}`)
- `finding_id` (ref `_common.json#/$defs/finding_id`)
- `action` (`{enum: ["approve", "dismiss"]}`)
- `bridge_received_at_iso_ms` (ref `_common.json#/$defs/iso_timestamp_utc_ms`)
- `contract_version` (semver pattern)

`additionalProperties: false`. Bridge constructs this payload from the inbound `finding_approval` envelope plus its own timestamp.

### 2. `shared/contracts/topics.yaml` (EXTEND)

Add under `egs:`:
```yaml
operator_actions: {channel: "egs.operator_actions", payload: "json", json_schema: "operator_actions"}
```

Re-run `python scripts/gen_topic_constants.py` to regenerate `frontend/flutter_dashboard/lib/generated/topics.dart` and any Python-side channel constants.

### 3. `frontend/ws_bridge/redis_publisher.py` (NEW, ~50 lines)

```python
class RedisPublisher:
    def __init__(self, *, redis_url: str) -> None: ...
    async def publish(self, channel: str, payload: dict) -> None: ...
    async def close(self) -> None: ...
```

- Lazy connection: first `publish()` call opens the client via `redis.asyncio.from_url(redis_url)`. Subsequent calls reuse.
- `publish` JSON-encodes payload, calls `redis.publish(channel, encoded)`. Raises on connection failure (caller handles).
- `close()` awaits `redis.aclose()` if a client was created. Idempotent.

### 4. `frontend/ws_bridge/main.py` (EXTEND)

- `create_app()` constructs `RedisPublisher(redis_url=config.redis_url)` and assigns `app.state.publisher = publisher`.
- `lifespan` adds `await app.state.publisher.close()` to the teardown branch.
- `ws_endpoint` adds a branch for `parsed["type"] == "finding_approval"`:
  1. `validate("websocket_messages", parsed)` — on invalid, `await _echo_error(websocket, error="invalid_finding_approval", detail=[...], command_id=parsed.get("command_id"), finding_id=parsed.get("finding_id"))`.
  2. Build Redis payload: `{kind: "finding_approval", command_id, finding_id, action, bridge_received_at_iso_ms: _now_iso_ms(), contract_version: VERSION}`.
  3. `validate("operator_actions", payload)` — defensive (catches schema bugs in our own code; failure → log + `_echo_error(error="bridge_internal")`).
  4. `try: await publisher.publish("egs.operator_actions", payload); except: await _echo_error(error="redis_publish_failed", command_id, finding_id)`.
  5. Success → send `{type: "echo", ack: "finding_approval", command_id, finding_id, contract_version: VERSION}`.

`_echo_error(websocket, *, error: str, detail: list | None = None, command_id: str | None = None, finding_id: str | None = None) -> None` factors out the JSON shape used by all error echoes (existing `operator_command` invalid path migrates to it). Always sends `{type: "echo", error, contract_version: VERSION}` plus any provided fields.

### 5. `frontend/flutter_dashboard/lib/state/mission_state.dart` (EXTEND)

New state:

```dart
enum _ApprovalState { pending, received, confirmed, dismissed, failed }

class MissionState extends ChangeNotifier {
  // ... existing fields ...
  final Map<String, _ApprovalState> _findingActions = {};
  final StreamController<String> _snackbarController =
      StreamController<String>.broadcast();
  Stream<String> get snackbarStream => _snackbarController.stream;

  WebSocketSink? _sink;
  String _sessionId = _generateSessionId();   // 4 chars, Random.secure
  int _commandCounter = 0;

  void attachSink(WebSocketSink sink) { _sink = sink; }
  void detachSink() { _sink = null; _failAllPending("Reconnect: please re-tap"); }

  void sendOutbound(Map<String, dynamic> envelope) {
    if (connectionStatus != "connected" || _sink == null) {
      if (kDebugMode) debugPrint("[MissionState] sendOutbound dropped: not connected");
      return;
    }
    _sink!.add(jsonEncode(envelope));
  }

  void markFinding(String id, String action) {
    final commandId = _nextCommandId();
    _findingActions[id] = _ApprovalState.pending;
    notifyListeners();
    sendOutbound({
      "type": "finding_approval",
      "command_id": commandId,
      "finding_id": id,
      "action": action,                          // "approve" | "dismiss"
      "contract_version": ContractVersion.current,
    });
  }

  void handleEcho(Map<String, dynamic> envelope) {
    if (envelope["type"] != "echo") return;
    final findingId = envelope["finding_id"] as String?;
    if (findingId == null) return;
    if (envelope["ack"] == "finding_approval") {
      // bridge received + published
      final wasDismiss = /* lookup by command_id or last action; see below */;
      _findingActions[findingId] =
          wasDismiss ? _ApprovalState.dismissed : _ApprovalState.received;
    } else if (envelope["error"] != null) {
      _findingActions[findingId] = _ApprovalState.failed;
      _snackbarController.add("Approval not delivered — retry");
    }
    notifyListeners();
  }

  void applyStateUpdate(Map<String, dynamic> envelope) {
    // ... existing parse ...
    // After updating activeFindings, promote any received → confirmed
    // when the upstream finding has approved=true (Phase 4 will set this).
    for (final f in activeFindings) {
      final id = (f as Map<String, dynamic>)["finding_id"] as String?;
      if (id == null) continue;
      if (_findingActions[id] == _ApprovalState.received &&
          f["approved"] == true) {
        _findingActions[id] = _ApprovalState.confirmed;
      }
    }
    notifyListeners();
  }
}
```

`command_id` format: `${sessionId}-${ms}-${counter}` where `sessionId` is 4 base32 chars from `Random.secure()` at app start. Prevents collisions across browser tabs against the same bridge.

`detachSink` (called from `_DashboardShell._scheduleReconnect`) moves all `pending` entries to `failed` and emits a single SnackBar event "Reconnect: please re-tap". Already-`received`/`confirmed`/`dismissed` rows preserve their state across reconnect.

To map echo → action (approve vs dismiss) for `received`/`dismissed` distinction, MissionState tracks `_pendingActions: Map<String, String>` (command_id → action) cleared on echo arrival.

### 6. `frontend/flutter_dashboard/lib/widgets/findings_panel.dart` (EXTEND)

- Each row gets two trailing buttons: `APPROVE` (green) and `DISMISS` (grey).
- Disabled when `_findingActions[id]` is in `{pending, received, confirmed, dismissed}`. Re-enabled when state is `failed` or absent.
- Visual states:
  - `pending`: small `CircularProgressIndicator` (16×16) inline before the buttons.
  - `received`: grey check icon, no border. Tooltip on icon: "Received by bridge".
  - `confirmed`: green check icon + green 4px left border. Tooltip: "Confirmed by EGS".
  - `dismissed`: row strikethrough + 0.5 opacity; small grey "✕" icon.
  - `failed`: small red "!" icon, button re-enabled.
- Findings absent from `state_update.active_findings` but present in `_findingActions` with state in `{received, confirmed, dismissed}` render as **archived rows** (full opacity, italic, "(archived)" suffix in title) at the bottom of the list.
- Listen on `MissionState.snackbarStream` from a parent `StatefulWidget` that calls `ScaffoldMessenger.of(context).showSnackBar(...)` for each event.

### 7. `frontend/flutter_dashboard/lib/widgets/map_panel.dart` (REWRITE, ~150 lines)

Pure `CustomPaint` with `_ProjectionPainter`:

- **bbox lock:** stored on the `_MapPanelState`. On first non-empty frame (`activeDrones.isNotEmpty || activeFindings.isNotEmpty`), compute min/max lat & lon with 20% padding, store. Subsequent frames re-render with the same bbox.
- **Refit button:** `IconButton(Icons.center_focus_strong)` in panel header → calls `setState(() => _bbox = null)` so next frame recomputes.
- **Projection:** equirectangular with `cos(midLat)` longitude correction. `pixelX = (lon - minLon) * cos(midLat * pi/180) * scaleX + offsetX`. Prevents distortion at non-equatorial scenarios.
- **NaN/null guard:** before each marker draw, check `lat.isFinite && lon.isFinite`. Skip silently otherwise.
- **Drone color palette:** `const _palette = [Colors.indigo, Colors.orange, Colors.teal, Colors.pink, Colors.lime, Colors.amber];`. Sort `activeDrones` by `drone_id` alphabetically; `palette[i % 6]`.
- **Drone marker:** filled circle (radius 8), white border (2px), drone_id label below (10pt).
- **Finding marker:** icon by type (`victim`=red person, `fire`=orange flame, `damage`=grey triangle, `blocked`=blue X), 14×14, drawn after drones so it sits on top.
- **Empty state:** `Text("Waiting for state…")` centered when both lists are empty. No bbox computed.
- **Background:** light grey (`Colors.grey.shade100`) with a faint 10% opacity grid every 50 pixels. Procedural; later replaced by static aerial image (see `TODOS.md`).

### 8. `frontend/flutter_dashboard/lib/widgets/command_panel.dart` (MINIMAL TWEAK)

`DISPATCH` button:
- `onPressed: null` (disabled).
- Wrapped in `Tooltip(message: "Coming soon — multilingual command path")`.
- Existing language dropdown remains active (no behavior change).

### 9. `scripts/run_dashboard_dev.sh` (NEW)

```bash
#!/usr/bin/env bash
# Starts Redis (if not already running), bridge, dev producers, and Flutter web
# dev server in dependent order, with a single trap for clean teardown.
set -euo pipefail
trap 'kill $(jobs -p) 2>/dev/null; exit' INT TERM EXIT

# 1. Redis check
if ! redis-cli ping > /dev/null 2>&1; then
  echo "ERROR: redis-server not running. Start it: brew services start redis (macOS) or sudo systemctl start redis (Linux)." >&2
  exit 1
fi

# 2. Port check (9090 for bridge, 8000 for flutter dev)
for port in 9090 8000; do
  if lsof -ti:$port > /dev/null 2>&1; then
    echo "ERROR: port $port is busy. Free it before running." >&2
    exit 1
  fi
done

# 3. Launch
PYTHONPATH=. uvicorn frontend.ws_bridge.main:app --host 127.0.0.1 --port 9090 &
PYTHONPATH=. python scripts/dev_fake_producers.py --tick-s 1.0 &
cd frontend/flutter_dashboard && flutter run -d chrome --web-port=8000 --web-hostname=127.0.0.1
```

### 10. `scripts/dev_actions_logger.py` (NEW, ~30 lines)

Stand-in EGS subscriber. Subscribes to `egs.operator_actions`, validates each message against `operator_actions` schema, prints `[approve|dismiss] finding_id command_id` to stdout. Used to verify the Phase 3 publish path locally without an EGS process.

### 11. README run instructions (EXTEND `frontend/flutter_dashboard/README.md`)

Replace placeholder content with:
- Prereqs (Redis, Flutter SDK, Python 3.11+).
- One-command launch via `scripts/run_dashboard_dev.sh`.
- Manual step-by-step for those who want to inspect each process.
- How to run unit + widget + Playwright tests.

## Data Flow — Approve a Finding (the demo beat)

1. Operator clicks `APPROVE` on finding row in Findings panel.
2. `FindingsPanel.onApprove` → `mission.markFinding(findingId, "approve")`.
3. `MissionState`:
   a. Generates `command_id = ${sessionId4}-${ms}-${counter++}`.
   b. Sets `_findingActions[id] = pending`, stores `_pendingActions[commandId] = "approve"`.
   c. Calls `notifyListeners()` (button shows spinner).
   d. Calls `sendOutbound({...})` writing JSON to `_sink`.
4. Bridge `ws_endpoint` receives JSON, parses, sees `type=="finding_approval"`.
5. Bridge validates → builds Redis payload → calls `publisher.publish("egs.operator_actions", payload)` → echoes `{type:"echo", ack:"finding_approval", command_id, finding_id}`.
6. Flutter receives echo via `_DashboardShell._sub` → routed to `mission.handleEcho(envelope)`.
7. `MissionState.handleEcho` looks up `_pendingActions[commandId]` → "approve" → sets `_findingActions[id] = received`. Notifies listeners. Row re-renders with grey check.
8. (Phase 4) When EGS subscribes, processes the approval, and emits state_update with `finding.approved == true`, `applyStateUpdate` promotes `received → confirmed`. Row gets green check + green border.

Failure variants:
- Schema reject → `_findingActions[id] = failed`, SnackBar.
- Redis publish raises → bridge sends error echo → same as above.
- WS drops while pending → `detachSink` moves all pending to failed + SnackBar.

## Failure Modes

| Codepath | Failure | Test? | Error handling? | Visible to operator? |
|---|---|---|---|---|
| Flutter `sendOutbound` | sink null/closed | ✅ unit | ✅ no-op + debug log | Implicit via pending → failed on next disconnect |
| Bridge inbound | invalid `finding_approval` | ✅ integration | ✅ `_echo_error` | ✅ SnackBar |
| Bridge | Redis unreachable | ✅ integration (monkeypatched) | ✅ `_echo_error` | ✅ SnackBar + button re-enable |
| Bridge ack lost | WS drops between publish and ack | ✅ e2e | ✅ pending → failed on reconnect | ✅ SnackBar prompts retry |
| Map projection | NaN / null coords | ✅ widget | ✅ skip marker | Silent (acceptable) |
| Upstream removal | finding leaves `active_findings` while approved/dismissed | ✅ widget + integration | ✅ archived row | ✅ visible badge |
| `command_id` collision | two tabs same bridge | ✅ unit | ✅ session prefix | N/A (prevented at source) |

**Zero critical gaps.** Every failure has a test, error handling, and (where it matters) operator-visible feedback.

## Test Plan (behaviors, not file counts)

### Python (`frontend/ws_bridge/tests/`)

- **`test_redis_publisher.py`** — RedisPublisher behaviors:
  - First publish opens connection from `redis.asyncio.from_url`.
  - Subsequent publishes reuse the connection.
  - Publish encodes payload as JSON (validates against fakeredis subscriber).
  - `close()` is idempotent.
  - `close()` cleanly disposes the client.

- **`test_outbound_publish.py`** — bridge `finding_approval` round-trip:
  - Valid envelope → publishes to `egs.operator_actions` with `bridge_received_at_iso_ms` stamped → echo `ack:"finding_approval"` returned with same `command_id`/`finding_id`.
  - Invalid `action` enum → echo `error:"invalid_finding_approval"`, no Redis publish.
  - Missing `command_id` → echo error, no Redis publish.
  - Missing `finding_id` → echo error, no Redis publish.
  - Redis publish raises → echo `error:"redis_publish_failed"` with `command_id`/`finding_id`, no ack.
  - `bridge_received_at_iso_ms` matches `iso_timestamp_utc_ms` regex.
  - Bridge-internal payload validation failure (mock schema reject) → echo `error:"bridge_internal"`.
  - **Regression:** existing `operator_command` echo path still passes.
  - `_echo_error` helper produces consistent shape across all error types.

### Flutter (`frontend/flutter_dashboard/test/`)

- **`mission_state_test.dart`** — state machine + outbound:
  - `sendOutbound` writes encoded JSON to attached sink.
  - `sendOutbound` no-ops when sink is null.
  - `sendOutbound` no-ops when `connectionStatus != "connected"`.
  - `markFinding(id, "approve")` → state = pending, sink receives correct envelope, listeners notified.
  - `handleEcho` with `ack:"finding_approval"` → state = received (or dismissed if action was dismiss).
  - `handleEcho` with `error:"redis_publish_failed"` → state = failed, snackbarStream emits.
  - `applyStateUpdate` promotes `received → confirmed` when upstream finding has `approved == true`.
  - `detachSink` moves all `pending` to `failed` and emits one snackbar event.
  - `command_id` uniqueness: 1000 sequential calls produce 1000 distinct IDs.

- **`findings_panel_test.dart`** — button states + visual states:
  - APPROVE tap → `mission.markFinding(id, "approve")` called.
  - DISMISS tap → `mission.markFinding(id, "dismiss")` called.
  - Button disabled when state in `{pending, received, confirmed, dismissed}`.
  - Button re-enabled when state is `failed`.
  - `received` row → grey check visible.
  - `confirmed` row → green check + green left border visible.
  - `dismissed` row → strikethrough + 0.5 opacity.
  - `archived` row → italic + "(archived)" suffix, button hidden.
  - Empty findings list → "no findings yet".

- **`map_panel_test.dart`** — projection + bbox + palette:
  - Equirectangular projection with cos(midLat) correction: known lat/lon → expected pixel.
  - bbox locks on first non-empty frame; subsequent frames don't recompute.
  - Refit button tap → bbox recomputed.
  - NaN/null coords skipped (no exception, no `_DroneMarker` in tree for that drone).
  - Empty state → "Waiting for state…" visible.
  - Drone palette: sorted-id index deterministic across runs.

- **`drone_status_panel_test.dart`** — boil-the-lake regression:
  - Renders one ListTile per drone in `activeDrones`.
  - Empty state → "No drones online" visible.

- **`command_panel_test.dart`**:
  - DISPATCH button is disabled (Tooltip wraps a non-interactive child).

### Playwright e2e (`frontend/ws_bridge/tests/test_e2e_phase3.py`, marker `e2e`)

Session-scoped fixture: `flutter build web` once (skip if `flutter` not on PATH), serve via `python -m http.server`, launch real bridge against fakeredis, launch `dev_fake_producers.py`. All tests reuse the same browser session via Playwright fixtures.

- **`test_e2e_drones_appear_on_map`** — within 5s, ≥1 drone marker rendered. Screenshot.
- **`test_e2e_findings_appear_in_panel`** — within 10s, ≥1 finding row in panel.
- **`test_e2e_panel_layout_stable`** — all 4 panel headers visible at 1280×720.
- **`test_e2e_approve_round_trip`** — click APPROVE, fakeredis subscriber receives matching `egs.operator_actions` payload, row shows grey check within 500ms.
- **`test_e2e_approve_with_redis_down`** — pre-stop fakeredis on test server side, click APPROVE, SnackBar "Approval not delivered — retry" visible within 1s, button re-enables.
- **`test_e2e_reconnect_after_bridge_restart`** — kill bridge subprocess → status shows "reconnecting" → restart → status returns to "connected" → confirmed approvals retain styling.

### Manual visual gate (Playwright MCP, by Claude on PR creation)

Three screenshots attached to PR via `mcp__playwright__browser_*`:
1. Map panel with drones in motion, findings as markers, drones using deterministic palette.
2. Findings panel mid-APPROVE: spinner inline.
3. Findings panel post-ack: grey check visible. Plus reconnect status visible after bridge kill.

## Worktree parallelization

| Step | Modules | Depends on |
|---|---|---|
| (1) Schema add `operator_actions.json` + topics.yaml + codegen | `shared/schemas/`, `shared/contracts/`, `frontend/flutter_dashboard/lib/generated/` | — |
| (2) Bridge: RedisPublisher + ws_endpoint extension + `_echo_error` | `frontend/ws_bridge/` | (1) |
| (3) Flutter MissionState + handleEcho + Stream | `frontend/flutter_dashboard/lib/state/` | (1) |
| (4) Flutter MapPanel rewrite | `frontend/flutter_dashboard/lib/widgets/map_panel.dart` | — |
| (5) Flutter FindingsPanel + CommandPanel | `frontend/flutter_dashboard/lib/widgets/` | (3) |
| (6) Tests (Python + Dart + Playwright) | `frontend/ws_bridge/tests/`, `frontend/flutter_dashboard/test/` | (2) + (3) + (4) + (5) |
| (7) `scripts/run_dashboard_dev.sh` + `scripts/dev_actions_logger.py` + README | `scripts/`, `frontend/flutter_dashboard/README.md` | (2) |

Lanes:
- **Lane A:** (1) → (2) → (7).
- **Lane B:** (4) (independent).
- **Lane C:** (3) → (5).
- **Lane D:** (6) (rolls behind each implementation lane).

Solo execution: 1 → 2 → 3 → 4 → 5 → 6 → 7.

## Out-of-band concerns

- **Branch hygiene:** working tree is `feat/dashboard-mvp` (cut from `main` post-Phase-2 squash-merge).
- **gstack upgrade:** 0.17.0.0 → 1.25.0.0 available. Defer until after Phase 3 lands.
