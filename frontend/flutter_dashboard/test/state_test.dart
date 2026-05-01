import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_dashboard/state/mission_state.dart';

void main() {
  test("applyStateUpdate populates fields from a state_update envelope", () {
    final m = MissionState();
    final envelope = {
      "type": "state_update",
      "timestamp": "2026-05-15T14:23:11.342Z",
      "contract_version": "1.0.0",
      "egs_state": {"mission_status": "active"},
      "active_findings": [],
      "active_drones": [
        {
          "drone_id": "drone1",
          "battery_pct": 87,
          "agent_status": "active",
          "current_task": "survey",
          "findings_count": 4,
          "validation_failures_total": 2,
        },
      ],
    };
    m.applyStateUpdate(envelope);
    expect(m.lastTimestamp, "2026-05-15T14:23:11.342Z");
    expect(m.contractVersion, "1.0.0");
    expect(m.activeDrones.length, 1);
    expect((m.activeDrones[0] as Map)["drone_id"], "drone1");
  });

  test("applyStateUpdate ignores non-state_update messages", () {
    final m = MissionState();
    m.applyStateUpdate({"type": "echo", "received": "ping"});
    expect(m.lastTimestamp, isNull);
  });

  test("applyRawFrame decodes JSON and applies", () {
    final m = MissionState();
    final raw = jsonEncode({
      "type": "state_update",
      "timestamp": "2026-05-15T14:23:11.342Z",
      "contract_version": "1.0.0",
      "egs_state": null,
      "active_findings": [],
      "active_drones": [],
    });
    m.applyRawFrame(raw);
    expect(m.lastTimestamp, "2026-05-15T14:23:11.342Z");
  });

  test("applyRawFrame handles malformed JSON gracefully", () {
    final m = MissionState();
    m.applyRawFrame("not json at all");
    expect(m.lastTimestamp, isNull);
  });
}
