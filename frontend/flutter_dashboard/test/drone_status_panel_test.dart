import 'package:flutter/material.dart';
import 'package:flutter_dashboard/state/mission_state.dart';
import 'package:flutter_dashboard/widgets/drone_status_panel.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

Widget _wrap(MissionState s) => MaterialApp(
      home: ChangeNotifierProvider<MissionState>.value(
        value: s,
        child: const Scaffold(body: DroneStatusPanel()),
      ),
    );

void main() {
  testWidgets('empty state shows "No drones online"', (tester) async {
    await tester.pumpWidget(_wrap(MissionState()));
    expect(find.textContaining("No drones"), findsOneWidget);
  });

  testWidgets('renders one tile per drone', (tester) async {
    final s = MissionState();
    s.applyStateUpdate({
      "type": "state_update",
      "timestamp": "2026-05-02T12:00:00.000Z",
      "contract_version": "1.0.0",
      "active_findings": [],
      "active_drones": [
        {
          "drone_id": "drone1", "agent_status": "active",
          "battery_pct": 87, "current_task": "survey_zone_a",
          "findings_count": 4, "validation_failures_total": 2,
        },
        {
          "drone_id": "drone2", "agent_status": "active",
          "battery_pct": 65, "current_task": "investigate_finding",
          "findings_count": 1, "validation_failures_total": 0,
        },
      ],
    });
    await tester.pumpWidget(_wrap(s));
    expect(find.byType(ListTile), findsNWidgets(2));
    expect(find.textContaining("drone1"), findsOneWidget);
    expect(find.textContaining("drone2"), findsOneWidget);
  });
}
