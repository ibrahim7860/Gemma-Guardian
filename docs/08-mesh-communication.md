# 08 — Mesh Communication

## What This Document Covers

The communication substrate between drones, between drones and EGS, and the simulation of realistic mesh dropout. The reference paper hand-waves this with "self-organizing wireless mesh network using technology such as Wi-Fi" but never specifies. This doc fills that gap with our concrete implementation choices.

## Real World vs Our Simulation

**Real deployment:**
- WiFi mesh (e.g., 802.11s) or WiFi-Halow for longer range
- Each drone broadcasts findings, telemetry, and coordination messages
- Range-limited; drones moving out of range drop their connection
- EGS is one node in the mesh

**Our simulation:**
- ROS 2 topics with explicit per-drone namespaces
- Range-based dropout simulated in software (a simple Euclidean distance check)
- All "broadcasts" are actually publishes to ROS 2 topics with software filtering on subscribe

## Topic Structure

```
/drones/<id>/state              # 2 Hz, drone state telemetry
/drones/<id>/findings           # event-driven, individual findings
/drones/<id>/tasks              # event-driven, EGS → drone commands
/drones/<id>/camera/image_raw   # 30 Hz from PX4, sampled at 1 Hz by agent

/swarm/broadcasts/<id>          # event-driven, peer broadcasts (findings, requests)
/swarm/operator_alerts          # event-driven, operator → all drones

/egs/state                      # 1 Hz, EGS state for the dashboard
/egs/replan_events              # event-driven, replanning notifications
```

## Range-Based Dropout

The realism we need for the demo is "drones lose connection when out of range, swarm continues anyway." We implement this in software:

**Configuration:**
- `MESH_RANGE_METERS = 200` (configurable for the demo)
- `EGS_LINK_RANGE_METERS = 500`

**Implementation:**

A small ROS 2 node called `mesh_simulator` runs alongside the drones. It:
1. Subscribes to `/drones/<id>/state` for all drones
2. Computes pairwise Euclidean distances every 1 second
3. Maintains an in-memory adjacency matrix
4. Republishes broadcasts on `/swarm/<id>/visible_to_<other_id>` filtered topics

Each drone subscribes only to broadcasts it would actually receive given the adjacency matrix. When a drone moves out of range, it stops receiving — exactly as a real mesh would behave.

**Code structure (simplified):**

```python
class MeshSimulator(Node):
    def __init__(self):
        self.drone_positions = {}
        self.broadcasts_received_by = defaultdict(set)
        # Subscribe to all drone states
        # Subscribe to all raw broadcasts
        # Republish filtered broadcasts on a per-recipient topic
    
    def filter_broadcast(self, sender_id, msg):
        for receiver_id in self.drone_positions:
            if receiver_id == sender_id:
                continue
            distance = euclidean(self.drone_positions[sender_id], 
                                self.drone_positions[receiver_id])
            if distance < MESH_RANGE_METERS:
                self.publish_to(receiver_id, sender_id, msg)
```

This is simple, works, and gives us the resilience scenarios we need to demo.

## EGS Link

Drones publish state and findings to the EGS via dedicated topics. The EGS link is also range-gated:

- If a drone is more than `EGS_LINK_RANGE_METERS` from the EGS position, its `/drones/<id>/state` and `/drones/<id>/findings` publishes are filtered out
- The drone queues telemetry locally
- When back in range, queued telemetry flushes

This is handled the same way as peer-to-peer mesh: the `mesh_simulator` node filters EGS-bound traffic too.

## Heartbeat and Failure Detection

**Drone heartbeats:** every drone publishes `/drones/<id>/state` at 2 Hz unconditionally. If the EGS doesn't see a state update for 10 consecutive seconds, the drone is marked as offline. The EGS then triggers replanning to reassign that drone's survey points.

**EGS heartbeats:** the EGS publishes `/egs/state` at 1 Hz. If a drone doesn't see an EGS update for 10 seconds, it enters **standalone mode**:
- Continues current task
- Coordinates with peers via direct broadcasts
- Doesn't wait for re-tasking
- Queues findings for later sync

Standalone mode is a key resilience demo. It's the exact scenario the reference paper's Architecture A handles, and we show our system can degrade gracefully into it.

## Message Schemas

### `/drones/<id>/state` (2 Hz from each drone)

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

### `/swarm/broadcasts/<id>` (event-driven)

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

### `/drones/<id>/tasks` (event-driven, EGS → drone)

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
| Mesh simulator becomes a bottleneck | Run at 1 Hz update rate; broadcasts are infrequent enough |
| ROS 2 namespace collisions | Strict naming convention enforced via launch file |
| Heartbeat false positives (lag spikes) | 10-second timeout is generous; can extend to 15 if needed |
| Standalone mode produces erratic behavior | Test heavily in Week 3; if drones make bad decisions, tighten reasoning prompt |

## What's Mocked

- Real WiFi MAC layer / IP routing — pure software topic filtering
- RF interference, signal strength, multipath — not modeled
- Mesh protocol negotiation — not modeled
- Encryption / authentication — out of scope for the prototype

State this explicitly in the writeup. The demo claim is "the architecture survives communication failure," not "we built a real mesh."
