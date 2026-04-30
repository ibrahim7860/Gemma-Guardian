# 07 — Operator Interface

## Purpose

The Flutter dashboard is the human-in-the-loop view. It serves three jobs:

1. **Situational awareness** — what is the swarm doing, what has it found
2. **Command channel** — let the operator influence the mission via natural language
3. **Trust verification** — show the operator that Gemma 4's outputs are validated, surface failures honestly

Critically, the dashboard is also our **demo storytelling surface**. The video uses the dashboard to make the agentic system legible to judges.

## Tech Stack

- **Flutter web** (single-page app), default `canvaskit` renderer. Do **not** opt into the WebAssembly (`skwasm`) build for the hackathon — it adds packaging complexity and the demo doesn't need it. Lock the renderer at `_flutter.loader.load({config: {renderer: "canvaskit"}})` in `web/index.html` so behaviour is deterministic across browsers.
- **rosbridge_suite** (`rosbridge_websocket` node) on the EGS host, exposing ROS 2 topics/services as JSON ops over WebSocket on port 9090.
- **`web_socket_channel`** Flutter package for the raw socket. We speak rosbridge protocol directly (`{op: "subscribe", topic, type}`, `{op: "publish", topic, msg}`) — there is no maintained first-party Dart equivalent of roslibjs, and writing a thin client against a handful of topics is faster than vendoring one.
- **State management:** `Provider` (or plain `ChangeNotifier` + `InheritedWidget`). No Bloc/Riverpod — we have one global mission state stream and four panels reading from it; anything heavier is over-engineering for 20 days.
- **flutter_map** for the map layer (OSM tiles disabled — we use a static base image, see Panel 1). `google_maps_flutter` is rejected because it requires an API key + internet and we are explicitly an offline system.
- Hosted locally (served from the same dev machine as rosbridge_websocket for the demo).

## Layout

Four panels in a 2×2 grid:

```
┌──────────────────────────┬──────────────────────────┐
│ MAP VIEW                 │ DRONE STATUS              │
│ - Drone positions        │ - For each drone:         │
│ - Survey points (color)  │   battery, task,          │
│ - Fire boundary          │   findings count,         │
│ - Findings as icons      │   last action,            │
│                          │   validation failures     │
├──────────────────────────┼──────────────────────────┤
│ FINDINGS FEED            │ COMMAND BOX                │
│ - Newest first           │ - Language selector        │
│ - Type / severity / conf │ - Text input               │
│ - Visual description     │ - Live: Gemma 4's          │
│ - APPROVE / DISMISS      │   structured translation   │
│                          │ - DISPATCH button          │
└──────────────────────────┴──────────────────────────┘
```

## Panel 1: Map View

Renders the simulated environment in top-down view.

**Layers:**
1. Base layer: satellite-style image of the simulated world (static, exported from Gazebo once)
2. Zone polygon: outlined region currently being surveyed
3. Survey points: small dots, color-coded per assigned drone
4. Drone positions: animated icons showing current location and heading; each drone gets a distinct color
5. Findings: icons by type (red marker = victim, orange flame = fire, gray triangle = damage, blue X = blocked route)
6. Mesh links: faint lines between drones currently in radio range of each other

**Interactivity:**
- Click a drone icon → its status panel highlights
- Click a finding → details popup with confidence, description, photo if available
- Hover a survey point → shows ID and assigned drone

**Implementation note:** Don't try to make this look like Google Maps. It's a Gazebo top-down view with overlays. Functional > pretty.

## Panel 2: Drone Status

For each drone, show:

```
┌─────────────────────────────────┐
│ Drone 1 ▮▮▮▮▮▮▮▯▯ 87%            │
│ Task: survey_zone_a (12/20)      │
│ Last action: report_finding      │
│ Findings: 4 | Validation fails: 2│
│ Connected: drone2, egs           │
└─────────────────────────────────┘
```

When a validation failure happens, the failure count increments visibly. This is part of the demo storytelling — the operator (and the audience watching the video) can see the validation loop working.

When a drone goes offline, its panel goes gray with "OFFLINE" overlay.

## Panel 3: Findings Feed

Newest findings on top. Each entry:

```
┌────────────────────────────────────────────────┐
│ 🔴 VICTIM (severity 4, confidence 0.78)        │
│ Drone 1 · 14:23:11                             │
│ "Person prone, partially covered by debris,    │
│  upper body visible, no movement observed"     │
│ Lat 34.1234 Lon -118.5678                      │
│                                                 │
│ [APPROVE FOR DISPATCH] [DISMISS] [VIEW ON MAP] │
└────────────────────────────────────────────────┘
```

Below the threshold (e.g., confidence < 0.6), findings are shown but flagged as "needs review."

When a finding is approved, the icon on the map changes color and an ALL_DRONES broadcast is sent (e.g., "victim confirmed, dispatch en route").

## Panel 4: Command Box

The most important panel for showcasing Gemma 4's multilingual capability.

**Layout:**

```
┌──────────────────────────────────────────────┐
│ Language: [English ▼]    [Spanish] [Arabic]   │
│                                                │
│ ┌────────────────────────────────────────────┐ │
│ │ Type a command...                          │ │
│ │                                            │ │
│ └────────────────────────────────────────────┘ │
│                                                │
│ Gemma 4 understanding:                         │
│   ┌─────────────────────────────────────────┐ │
│   │ recall_drone(drone_id="drone2",         │ │
│   │              reason="ordered")           │ │
│   └─────────────────────────────────────────┘ │
│                                                │
│  [DISPATCH COMMAND]   [REPHRASE]               │
└──────────────────────────────────────────────┘
```

**Flow:**
1. Operator types in any language
2. Frontend sends text to EGS
3. EGS calls Gemma 4 E4B for translation (with operator command schema)
4. EGS validates the structured output
5. Frontend shows the structured translation
6. Operator clicks DISPATCH or REPHRASE
7. On dispatch, EGS executes the command (replans, sends to drones, etc.)

**For the demo,** scripted commands in the video:
- English: "drone 2, return to base"
- Spanish: "concéntrate en la zona este" (focus on the eastern zone)
- (Stretch) Arabic: a recall command

The video makes a point of showing Gemma 4 correctly translating each.

## WebSocket Message Schema

These are **app-level** payloads carried inside rosbridge `publish`/`subscribe` ops, not raw rosbridge envelopes. Flutter subscribes to a fixed set of ROS 2 topics owned by the EGS:

- `/fieldagent/state` (`std_msgs/String` carrying the JSON below) — pushed by EGS at 1 Hz
- `/fieldagent/operator_command` (`std_msgs/String`) — published by Flutter
- `/fieldagent/command_translation` (`std_msgs/String`) — pushed by EGS in response
- `/fieldagent/operator_command_dispatch` (`std_msgs/String`) — published by Flutter on approval

We use `std_msgs/String` with a JSON payload (rather than custom `.msg` files) so the contract lives in `shared/schemas/` and doesn't require rebuilding the ROS 2 workspace every time we tweak it. See [`20-integration-contracts.md`](20-integration-contracts.md) for the locked field list.

The EGS pushes state to Flutter every 1 second:

```json
{
  "type": "state_update",
  "timestamp": "2026-05-15T14:23:11.342Z",
  "mission_status": "active",
  "drones": [
    {"id": "drone1", "position": {...}, "battery": 87, "task": "survey_zone_a", ...},
    ...
  ],
  "findings": [...],
  "survey_points": [...],
  "zone_polygon": [...],
  "validation_events": [
    {"timestamp": ..., "agent": "drone1", "task": "report_finding", "retries": 1}
  ]
}
```

For commands, Flutter sends:

```json
{
  "type": "operator_command",
  "language": "es",
  "text": "concéntrate en la zona este"
}
```

EGS responds:

```json
{
  "type": "command_translation",
  "structured": {
    "command": "restrict_zone",
    "args": {"zone_id": "east"}
  },
  "valid": true,
  "preview_text": "Will restrict mission to zone 'east'"
}
```

After operator approves:

```json
{
  "type": "operator_command_dispatch",
  "command_id": "cmd_47"
}
```

Detailed in [`20-integration-contracts.md`](20-integration-contracts.md).

## Stretch Features (Only If Time)

- Mini camera feed from each drone (one frame per second, pulled from ROS topic)
- Audio operator commands via voice (would use Gemma 4 E4B audio mode if accessible)
- Mission timeline scrubber for replay

These are nice-to-haves. Don't build them unless the rest is solid by Day 16.

## What Could Go Wrong

| Failure | Mitigation |
|---|---|
| WebSocket disconnects | Auto-reconnect with exponential backoff (1s, 2s, 4s, capped at 10s); cache last-known state client-side and re-subscribe to all four topics on reconnect |
| Map renders slowly | Use static base layer, don't fetch tiles |
| Command translation slow | Show "translating..." spinner; cap timeout at 15 seconds |
| Multilingual fails | Fall back to English-only for the demo, document limitation |

## Why This Matters for the Demo

The dashboard is what the judge actually watches. The Gazebo footage is supporting context; the dashboard is where the story is told. Specifically:

- Validation event ticks visible → "Gemma 4 is being self-corrected, you can see it"
- Multilingual command translation → "Gemma 4 speaks Spanish natively, no translation API"
- Drone status panel going OFFLINE → "the swarm is reorganizing without external help"

The dashboard lets a non-technical viewer understand what an agentic LLM-driven swarm actually means. Without it, the demo is just terminal output and Gazebo footage. With it, the demo tells a story.
