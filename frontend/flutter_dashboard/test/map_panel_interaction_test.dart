import 'package:flutter/material.dart';
import 'package:flutter_dashboard/state/mission_state.dart';
import 'package:flutter_dashboard/widgets/map_panel.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

Widget _wrap(MissionState s) => MaterialApp(
      home: ChangeNotifierProvider<MissionState>.value(
        value: s,
        child: const Scaffold(body: SizedBox(width: 600, height: 600, child: MapPanel())),
      ),
    );

Map<String, dynamic> _drone(String id, double lat, double lon) => {
      "drone_id": id,
      "agent_status": "active",
      "battery_pct": 87,
      "current_task": "survey_zone_a",
      "findings_count": 0,
      "validation_failures_total": 0,
      "position": {"lat": lat, "lon": lon, "alt": 50.0},
    };

Map<String, dynamic> _finding(String id, String drone, double lat, double lon) => {
      "finding_id": id,
      "source_drone_id": drone,
      "type": "victim",
      "severity": 4,
      "confidence": 0.8,
      "timestamp": "2026-05-04T12:00:00.000Z",
      "visual_description": "person prone in debris",
      "location": {"lat": lat, "lon": lon, "alt": 0.0},
      "validated": true,
      "operator_status": "pending",
    };

void _seed(MissionState s) {
  s.applyStateUpdate({
    "type": "state_update",
    "timestamp": "2026-05-04T12:00:00.000Z",
    "contract_version": "1.0.0",
    "active_findings": [
      _finding("f_drone1_5", "drone1", 34.001, -118.001),
    ],
    "active_drones": [
      _drone("drone1", 34.0, -118.0),
      _drone("drone2", 34.01, -118.01),
    ],
  });
}

void main() {
  testWidgets('tapping a drone marker selects that drone', (tester) async {
    final s = MissionState();
    _seed(s);
    await tester.pumpWidget(_wrap(s));
    await tester.pump();

    await tester.tap(find.byKey(const ValueKey('map-drone-drone1')));
    await tester.pump();

    expect(s.selectedDroneId, equals('drone1'));
    expect(s.selectedFindingId, isNull);
  });

  testWidgets('tapping a finding marker selects that finding', (tester) async {
    final s = MissionState();
    _seed(s);
    await tester.pumpWidget(_wrap(s));
    await tester.pump();

    await tester.tap(find.byKey(const ValueKey('map-finding-f_drone1_5')));
    await tester.pump();

    expect(s.selectedFindingId, equals('f_drone1_5'));
    expect(s.selectedDroneId, isNull);
  });

  testWidgets('tapping the same drone marker twice deselects', (tester) async {
    final s = MissionState();
    _seed(s);
    await tester.pumpWidget(_wrap(s));
    await tester.pump();

    await tester.tap(find.byKey(const ValueKey('map-drone-drone1')));
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('map-drone-drone1')));
    await tester.pump();

    expect(s.selectedDroneId, isNull);
  });

  testWidgets(
      'co-located drone+finding: tap selects the DRONE (eng-review 2A/3C)',
      (tester) async {
    // A drone reports a finding at its current position — same lat/lon.
    // Painter renders findings under drones; tap layer must match so the
    // visible drone wins the tap.
    final s = MissionState();
    s.applyStateUpdate({
      "type": "state_update",
      "timestamp": "2026-05-04T12:00:00.000Z",
      "contract_version": "1.0.0",
      "active_findings": [_finding("f_drone1_5", "drone1", 34.0, -118.0)],
      "active_drones": [_drone("drone1", 34.0, -118.0)],
    });
    await tester.pumpWidget(_wrap(s));
    await tester.pump();

    await tester.tap(find.byKey(const ValueKey('map-drone-drone1')));
    await tester.pump();

    expect(s.selectedDroneId, equals('drone1'),
        reason: 'visible drone must win the tap when co-located with a finding');
    expect(s.selectedFindingId, isNull);
  });
}
