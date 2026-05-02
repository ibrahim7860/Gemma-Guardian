import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:flutter_dashboard/state/mission_state.dart';
import 'package:flutter_dashboard/widgets/drone_status_panel.dart';

Widget _wrap(MissionState state) => MaterialApp(
      home: ChangeNotifierProvider<MissionState>.value(
        value: state,
        child: const Scaffold(body: DroneStatusPanel()),
      ),
    );

Map<String, dynamic> _drone(String id) => {
      "drone_id": id,
      "agent_status": "active",
      "battery_pct": 87,
      "current_task": "survey",
      "findings_count": 4,
      "validation_failures_total": 2,
    };

void main() {
  testWidgets('renders empty when no drones', (tester) async {
    final state = MissionState();
    await tester.pumpWidget(_wrap(state));
    expect(find.text("No drones online"), findsOneWidget);
  });

  testWidgets('renders empty validation row when no events', (tester) async {
    final state = MissionState();
    state.applyStateUpdate({
      "type": "state_update",
      "timestamp": "2026-05-02T12:00:00.000Z",
      "contract_version": "1.0.0",
      "egs_state": {"recent_validation_events": []},
      "active_drones": [_drone("drone1")],
      "active_findings": [],
    });
    await tester.pumpWidget(_wrap(state));
    expect(find.textContaining("Validation: 0 fails"), findsOneWidget);
  });

  testWidgets('renders ticker when events exist for this drone', (tester) async {
    final state = MissionState();
    state.applyStateUpdate({
      "type": "state_update",
      "timestamp": "2026-05-02T12:00:00.000Z",
      "contract_version": "1.0.0",
      "egs_state": {
        "recent_validation_events": [
          {
            "timestamp": "2026-05-02T11:59:50.000Z",
            "agent": "drone1",
            "task": "report_finding",
            "outcome": "corrected_after_retry",
            "issue": "DUPLICATE_FINDING",
          },
          {
            "timestamp": "2026-05-02T11:59:40.000Z",
            "agent": "drone2",
            "task": "report_finding",
            "outcome": "corrected_after_retry",
            "issue": "GPS_OUT_OF_ZONE",
          },
        ],
      },
      "active_drones": [_drone("drone1"), _drone("drone2")],
      "active_findings": [],
    });
    await tester.pumpWidget(_wrap(state));
    expect(find.textContaining("DUPLICATE_FINDING"), findsOneWidget);
    expect(find.textContaining("GPS_OUT_OF_ZONE"), findsOneWidget);
  });

  testWidgets('renders safely when egs_state is null (reconnect window)', (tester) async {
    final state = MissionState();
    state.applyStateUpdate({
      "type": "state_update",
      "timestamp": "2026-05-02T12:00:00.000Z",
      "contract_version": "1.0.0",
      "egs_state": null,
      "active_drones": [_drone("drone1")],
      "active_findings": [],
    });
    await tester.pumpWidget(_wrap(state));
    // Renders the drone row without crashing; ticker line is empty
    expect(find.textContaining("drone1"), findsOneWidget);
    expect(find.textContaining("Validation: 0 fails"), findsOneWidget);
  });
}
