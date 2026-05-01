# 08 — Mesh Communication

## What This Document Covers

The communication substrate between drones, between drones and EGS, and the simulation of realistic mesh dropout. The reference paper hand-waves this with "self-organizing wireless mesh network using technology such as Wi-Fi" but never specifies. This doc fills that gap with our concrete implementation choices.

## Real World vs Our Simulation

**Real deployment:**
- WiFi mesh (e.g., 802.11s) or Wi-Fi HaLow (802.11ah) for longer range
- Each drone broadcasts findings, telemetry, and coordination messages
- Range-limited; drones moving out of range drop their connection
- EGS is one node in the mesh

**Our simulation:**
- Redis pub/sub on `localhost:6379` with dot-notation channel names
- Range-based dropout simulated in software (a simple Euclidean distance check)
- All "broadcasts" are publishes to Redis channels with software filtering by a separate `mesh_simulator` process
- Pure application-layer filtering. No network shaping (`tc`/`netem`). The mesh simulator owns the visibility logic.

## Channel Structure

```
drones.<id>.state              # 2 Hz, drone state telemetry (JSON)
drones.<id>.findings           # event-driven, individual findings (JSON)
drones.<id>.tasks              # event-driven, EGS → drone commands (JSON)
drones.<id>.camera             # ~1 Hz from frame_server, sampled at 1 Hz by agent (JPEG bytes)

swarm.broadcasts.<sender_id>   # event-driven, raw peer broadcasts (sender publishes here; JSON)
swarm.<receiver_id>.visible_to.<receiver_id>
                               # event-driven, mesh_simulator republishes broadcasts that
                               # <receiver_id> can hear (JSON)
swarm.operator_alerts          # event-driven, operator → all drones (JSON)

egs.state                      # 1 Hz, EGS state for the dashboard (JSON)
egs.replan_events              # event-driven, replanning notifications (JSON)
mesh.adjacency_matrix          # 1 Hz, mesh_simulator publishes the current adjacency matrix (JSON)
```

Naming convention: lowercase dot-notation, glob-friendly with `redis-cli PSUBSCRIBE` (e.g., `PSUBSCRIBE drones.*.state`). `<id>` is the drone identifier (e.g., `drone1`). Each drone agent only ever publishes to `drones.<own_id>.*` and `swarm.broadcasts.<own_id>`, and only ever subscribes to `swarm.<own_id>.visible_to.<own_id>` (plus its own `drones.<own_id>.tasks` and the operator/EGS channels). This keeps the per-drone agent identical across drones — only the drone ID argument changes. The canonical channel registry is in `shared/contracts/topics.yaml`; see [`20-integration-contracts.md`](20-integration-contracts.md).

## Delivery Semantics

Redis pub/sub is fire-and-forget at the broker level: a message is delivered to all current subscribers and dropped if no one is listening. We map the old per-channel reliability/durability intentions onto application-layer conventions:

| Channel class | Delivery intent | Application convention |
|---|---|---|
| `drones.<id>.state` | Best-effort; drop preferred over backlog | Published at 2 Hz; consumers use latest received; no buffering |
| `drones.<id>.camera` | Best-effort | Published at ~1 Hz; consumer uses latest frame; frame_server drops if slow |
| `drones.<id>.findings` | Reliable (must not be lost) | Agent retains in local log and re-publishes on reconnect if no ACK from EGS |
| `drones.<id>.tasks` | Reliable + "latch" semantics | EGS re-publishes on reconnect; drone agent stores last-received task to disk |
| `swarm.broadcasts.<sender_id>` | Reliable (sim-internal hop) | mesh_simulator subscribes synchronously; loss here is a bug |
| `swarm.<receiver_id>.visible_to.<receiver_id>` | Reliable | Forwarded immediately by mesh_simulator; dropout is explicit by omission |
| `swarm.operator_alerts` | Reliable | EGS re-publishes on reconnect |
| `egs.state` | Latch-style | EGS maintains last state and re-publishes to newly connected subscribers |
| `egs.replan_events` | Reliable | EGS queues until subscriber connects |
| `mesh.adjacency_matrix` | Latch-style | mesh_simulator re-publishes at 1 Hz unconditionally |

Heartbeat detection is handled in application code (see below), not at the transport layer, so the demo can show explicit, narratable timeouts on the dashboard.

## Range-Based Dropout

The realism we need for the demo is "drones lose connection when out of range, swarm continues anyway." We implement this in software:

**Configuration:**
- `MESH_RANGE_METERS = 200` (configurable for the demo)
- `EGS_LINK_RANGE_METERS = 500`

**Implementation:**

A small Python process called `mesh_simulator` runs alongside the drones. It:
1. Pattern-subscribes (`PSUBSCRIBE drones.*.state`) to track all drone positions via Redis
2. Computes pairwise Euclidean distances every 1 second against the live position snapshot
3. Maintains an in-memory adjacency matrix and publishes it at 1 Hz on `mesh.adjacency_matrix`
4. Pattern-subscribes to `swarm.broadcasts.*` and republishes each message onto `swarm.<receiver_id>.visible_to.<receiver_id>` for every receiver currently in range of the sender

Each drone subscribes only to its own `swarm.<id>.visible_to.<id>`. When a peer moves out of range, the simulator stops fanning that peer's broadcasts to the drone's channel — exactly as a real mesh would behave. The same process also gates EGS-bound traffic (see EGS Link below).

The `in_mesh_range_of` field in the drone state schema is a convenience copy: drones populate it by reading the latest `mesh.adjacency_matrix` snapshot. Ground truth lives in the simulator.

**Code structure (simplified):**

```python
class MeshSimulator:
    def __init__(self, redis_client):
        self.drone_positions = {}
        self.redis = redis_client
        # Pattern-subscribe to drones.*.state (position updates)
        # Pattern-subscribe to swarm.broadcasts.* (peer broadcasts)
    
    def filter_broadcast(self, sender_id, msg):
        for receiver_id in self.drone_positions:
            if receiver_id == sender_id:
                continue
            distance = euclidean(self.drone_positions[sender_id],
                                 self.drone_positions[receiver_id])
            if distance < MESH_RANGE_METERS:
                # Republish onto swarm.<receiver_id>.visible_to.<receiver_id>
                channel = f"swarm.{receiver_id}.visible_to.{receiver_id}"
                self.redis.publish(channel, msg)
```

This is simple, works, and gives us the resilience scenarios we need to demo.

## EGS Link

Drones publish state and findings to the EGS via dedicated Redis channels. The EGS link is also range-gated:

- If a drone is more than `EGS_LINK_RANGE_METERS` from the EGS position, the mesh_simulator withholds forwarding that drone's `drones.<id>.state` and `drones.<id>.findings` messages to the EGS subscriber
- The drone queues telemetry locally
- When back in range, queued telemetry flushes

This is handled the same way as peer-to-peer mesh: the mesh_simulator filters EGS-bound traffic too.

## Heartbeat and Failure Detection

**Drone heartbeats:** every drone publishes `drones.<id>.state` at 2 Hz unconditionally. If the EGS doesn't see a state update for 10 consecutive seconds, the drone is marked as offline. The EGS then triggers replanning to reassign that drone's survey points.

**EGS heartbeats:** the EGS publishes `egs.state` at 1 Hz. If a drone doesn't see an EGS update for 10 seconds, it enters **standalone mode**:
- Continues current task
- Coordinates with peers via direct broadcasts
- Doesn't wait for re-tasking
- Queues findings for later sync

Standalone mode is a key resilience demo. It's the exact scenario the reference paper's Architecture A handles, and we show our system can degrade gracefully into it.

## Message Schemas

### `drones.<id>.state` (2 Hz from each drone; JSON)

```json
{
  "drone_id": "drone1",
  "timestamp": "2026-05-15T14:23:11.342Z",
  "position": {"lat": 34.1234, "lon": -118.5678, "alt": 25.0},
  "battery_pct": 87,
  "heading_deg": 135,
  "current_task": "survey_zone_a",
  "assigned_survey_points_remaining": 12,
  "last_action": "report_finding",
  "last_action_timestamp": "2026-05-15T14:23:08.119Z",
  "validation_failures_total": 2,
  "findings_count": 4,
  "in_mesh_range_of": ["drone2", "egs"]
}
```

### `swarm.broadcasts.<id>` (event-driven; JSON)

```json
{
  "broadcast_id": "drone1_b047",
  "sender_id": "drone1",
  "sender_position": {"lat": ..., "lon": ..., "alt": ...},
  "timestamp": "2026-05-15T14:23:11.342Z",
  "broadcast_type": "finding",
  "payload": {
    "type": "victim",
    "severity": 4,
    "gps_lat": 34.1235,
    "gps_lon": -118.5679,
    "confidence": 0.78,
    "visual_description": "Person prone, partially covered..."
  }
}
```

Other broadcast types: `assist_request`, `task_complete`, `entering_standalone_mode`.

### `drones.<id>.tasks` (event-driven, EGS → drone; JSON)

```json
{
  "task_id": "task_237",
  "drone_id": "drone1",
  "issued_at": "2026-05-15T14:23:00.000Z",
  "task_type": "survey",
  "assigned_survey_points": [
    {"id": "sp_001", "lat": ..., "lon": ...},
    {"id": "sp_002", "lat": ..., "lon": ...}
  ],
  "priority": "normal",
  "valid_until": "2026-05-15T14:38:00.000Z"
}
```

Detailed in [`20-integration-contracts.md`](20-integration-contracts.md).

## Resilience Scenarios

These are scripted for the demo. Each demonstrates a real-world failure mode the architecture handles.

### Scenario 1: Drone Out of Range

A drone flies to the edge of the survey zone and loses mesh contact with peers (but stays in EGS range). It continues its task autonomously, queues any findings locally, and re-syncs when it returns.

**Demo timing:** 15 seconds of footage.

### Scenario 2: EGS Link Severed

We script a moment where the EGS becomes unreachable (e.g., simulated network failure). All drones detect the heartbeat loss and enter standalone mode. Peer broadcasts continue. Each drone's onboard Gemma 4 E2B reasons about its own task without waiting for the EGS. When the EGS comes back, drones flush queued findings and resume normal operation.

**Demo timing:** 20 seconds of footage. This is the killer resilience moment.

### Scenario 3: Drone Failure

A drone simulates GPS failure and calls `return_to_base`. The EGS detects the orphaned survey points and reassigns them to the remaining drones via the validation-loop assignment task.

**Demo timing:** 15 seconds of footage. This shows the validation loop working under stress.

## What Could Go Wrong

| Failure | Mitigation |
|---|---|
| Mesh simulator becomes a bottleneck | Adjacency recomputed at 1 Hz; broadcast forwarding is event-driven and small (peer count ≤ 3 in our demo) |
| Redis channel name typo causes silent no-delivery | All channel names generated from `shared/contracts/topics.yaml`; never hardcoded. `test_topics_codegen_fresh.py` CI check catches stale constants. |
| Redis drops messages (no current subscriber) | Findings and tasks use application-layer queuing + re-publish on reconnect (see Delivery Semantics). |
| Heartbeat false positives (lag spikes) | 10-second timeout is generous; can extend to 15 if needed |
| Standalone mode produces erratic behavior | Test heavily in Week 3; if drones make bad decisions, tighten reasoning prompt |

## What's Mocked

- Real WiFi MAC layer / IP routing — pure software topic filtering
- RF interference, signal strength, multipath — not modeled
- Mesh protocol negotiation — not modeled
- Encryption / authentication — out of scope for the prototype

State this explicitly in the writeup. The demo claim is "the architecture survives communication failure," not "we built a real mesh."
