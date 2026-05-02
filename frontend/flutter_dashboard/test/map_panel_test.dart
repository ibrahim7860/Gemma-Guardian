import 'package:flutter/material.dart';
import 'package:flutter_dashboard/state/mission_state.dart';
import 'package:flutter_dashboard/widgets/map_panel.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

Widget _wrap(MissionState s) => MaterialApp(
      home: ChangeNotifierProvider<MissionState>.value(
        value: s,
        child: const Scaffold(body: MapPanel()),
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

void main() {
  testWidgets('empty state shows "Waiting for state…"', (tester) async {
    await tester.pumpWidget(_wrap(MissionState()));
    expect(find.textContaining("Waiting"), findsOneWidget);
  });

  testWidgets('renders one marker per active drone', (tester) async {
    final s = MissionState();
    s.applyStateUpdate({
      "type": "state_update",
      "timestamp": "2026-05-02T12:00:00.000Z",
      "contract_version": "1.0.0",
      "active_findings": [],
      "active_drones": [
        _drone("drone1", 34.0, -118.0),
        _drone("drone2", 34.01, -118.01),
      ],
    });
    await tester.pumpWidget(_wrap(s));
    expect(find.byKey(const ValueKey("map-drone-drone1")), findsOneWidget);
    expect(find.byKey(const ValueKey("map-drone-drone2")), findsOneWidget);
  });

  testWidgets('NaN coords skipped without crash', (tester) async {
    final s = MissionState();
    s.applyStateUpdate({
      "type": "state_update",
      "timestamp": "2026-05-02T12:00:00.000Z",
      "contract_version": "1.0.0",
      "active_findings": [],
      "active_drones": [
        {
          ..._drone("drone1", 34.0, -118.0),
          "position": {"lat": double.nan, "lon": -118.0, "alt": 50.0},
        },
        _drone("drone2", 34.01, -118.01),
      ],
    });
    await tester.pumpWidget(_wrap(s));
    // Bad drone is skipped; good drone is rendered.
    expect(find.byKey(const ValueKey("map-drone-drone1")), findsNothing);
    expect(find.byKey(const ValueKey("map-drone-drone2")), findsOneWidget);
  });

  testWidgets('refit button is present', (tester) async {
    final s = MissionState();
    s.applyStateUpdate({
      "type": "state_update",
      "timestamp": "2026-05-02T12:00:00.000Z",
      "contract_version": "1.0.0",
      "active_findings": [],
      "active_drones": [_drone("drone1", 34.0, -118.0)],
    });
    await tester.pumpWidget(_wrap(s));
    expect(find.byIcon(Icons.center_focus_strong), findsOneWidget);
  });

  testWidgets('tapping refit recomputes bbox without crash', (tester) async {
    final s = MissionState();
    s.applyStateUpdate({
      "type": "state_update",
      "timestamp": "2026-05-02T12:00:00.000Z",
      "contract_version": "1.0.0",
      "active_findings": [],
      "active_drones": [_drone("drone1", 34.0, -118.0)],
    });
    await tester.pumpWidget(_wrap(s));
    expect(find.byKey(const ValueKey("map-drone-drone1")), findsOneWidget);
    await tester.tap(find.byIcon(Icons.center_focus_strong));
    await tester.pump();
    // Drone marker still rendered after refit.
    expect(find.byKey(const ValueKey("map-drone-drone1")), findsOneWidget);
  });

  test('palette is deterministic for sorted drone ids', () {
    final colors1 = palettePreview(["drone3", "drone1", "drone2"]);
    final colors2 = palettePreview(["drone1", "drone2", "drone3"]);
    expect(colors1["drone1"], colors2["drone1"]);
    expect(colors1["drone2"], colors2["drone2"]);
    expect(colors1["drone3"], colors2["drone3"]);
    // First three sorted ids get the first three palette entries.
    expect(colors1["drone1"], isNot(colors1["drone2"]));
  });
}
