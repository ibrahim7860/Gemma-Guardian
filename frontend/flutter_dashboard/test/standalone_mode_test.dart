/// Beat 4 dashboard pre-flight: STANDALONE MODE badge + EGS LINK SEVERED banner.
///
/// Schemas are locked (docs/20-integration-contracts.md), so "EGS link severed"
/// is derived from heartbeat staleness on egs.state (Contract 3 publishes at
/// 1 Hz). The badge keys directly off the existing agent_status enum value
/// "standalone" already in shared/schemas/_common.json.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:flutter_dashboard/main.dart' show EgsLinkSeveredBanner;
import 'package:flutter_dashboard/state/mission_state.dart';
import 'package:flutter_dashboard/widgets/drone_status_panel.dart';

Map<String, dynamic> _stateUpdateWith(List<Map<String, dynamic>> drones) => {
      'type': 'state_update',
      'egs_state': {'mission_id': 'm1'},
      'active_drones': drones,
      'active_findings': const [],
    };

void main() {
  group('STANDALONE badge in DroneStatusPanel', () {
    testWidgets('renders when agent_status == "standalone"', (tester) async {
      final mission = MissionState();
      addTearDown(mission.dispose);
      mission.applyStateUpdate(_stateUpdateWith([
        {
          'drone_id': 'drone3',
          'agent_status': 'standalone',
          'battery_pct': 62,
          'current_task': 'survey',
          'findings_count': 1,
          'validation_failures_total': 0,
        },
      ]));

      await tester.pumpWidget(
        MaterialApp(
          home: ChangeNotifierProvider<MissionState>.value(
            value: mission,
            child: const Scaffold(body: DroneStatusPanel()),
          ),
        ),
      );
      await tester.pump();

      expect(
        find.bySemanticsIdentifier('standalone-badge-drone3'),
        findsOneWidget,
        reason:
            'DroneStatusPanel must emit Semantics(identifier: '
            '"standalone-badge-<id>") whenever agent_status == "standalone" '
            'so Beat 4 of the demo storyboard can verify the panel state '
            'via the Flutter accessibility tree.',
      );
    });

    testWidgets('does not render when agent_status == "active"',
        (tester) async {
      final mission = MissionState();
      addTearDown(mission.dispose);
      mission.applyStateUpdate(_stateUpdateWith([
        {
          'drone_id': 'drone1',
          'agent_status': 'active',
          'battery_pct': 88,
          'current_task': 'survey',
          'findings_count': 0,
          'validation_failures_total': 0,
        },
      ]));

      await tester.pumpWidget(
        MaterialApp(
          home: ChangeNotifierProvider<MissionState>.value(
            value: mission,
            child: const Scaffold(body: DroneStatusPanel()),
          ),
        ),
      );
      await tester.pump();

      expect(find.bySemanticsIdentifier('standalone-badge-drone1'),
          findsNothing);
    });
  });

  group('EGS LINK SEVERED banner', () {
    testWidgets('does not render when egs.state heartbeat is fresh',
        (tester) async {
      var fakeNow = DateTime(2026, 5, 7, 10, 0, 0);
      final mission = MissionState(now: () => fakeNow);
      addTearDown(mission.dispose);
      mission.setConnectionStatus("connected");
      mission.applyStateUpdate(_stateUpdateWith(const []));
      // Advance only 1 s — well below the 5 s tolerance.
      fakeNow = fakeNow.add(const Duration(seconds: 1));
      mission.debugRecomputeEgsLinkSevered();

      await tester.pumpWidget(
        MaterialApp(
          home: ChangeNotifierProvider<MissionState>.value(
            value: mission,
            child: const Scaffold(body: EgsLinkSeveredBanner()),
          ),
        ),
      );
      await tester.pump();

      expect(mission.egsLinkSevered, isFalse);
      expect(find.bySemanticsIdentifier('egs-link-severed-banner'),
          findsNothing);
    });

    testWidgets('renders when egs.state heartbeat exceeds tolerance',
        (tester) async {
      var fakeNow = DateTime(2026, 5, 7, 10, 0, 0);
      final mission = MissionState(now: () => fakeNow);
      addTearDown(mission.dispose);
      mission.setConnectionStatus("connected");
      mission.applyStateUpdate(_stateUpdateWith(const []));
      // 6 s > MissionState.egsHeartbeatStaleAfter (5 s).
      fakeNow = fakeNow.add(const Duration(seconds: 6));
      mission.debugRecomputeEgsLinkSevered();

      await tester.pumpWidget(
        MaterialApp(
          home: ChangeNotifierProvider<MissionState>.value(
            value: mission,
            child: const Scaffold(body: EgsLinkSeveredBanner()),
          ),
        ),
      );
      await tester.pump();

      expect(mission.egsLinkSevered, isTrue);
      expect(find.bySemanticsIdentifier('egs-link-severed-banner'),
          findsOneWidget);
    });

    testWidgets('does not render when WS itself is disconnected',
        (tester) async {
      // Connection-status header already reports WS-down separately; the
      // banner is specifically for the case where WS is up but EGS is silent.
      var fakeNow = DateTime(2026, 5, 7, 10, 0, 0);
      final mission = MissionState(now: () => fakeNow);
      addTearDown(mission.dispose);
      mission.setConnectionStatus("connected");
      mission.applyStateUpdate(_stateUpdateWith(const []));
      fakeNow = fakeNow.add(const Duration(seconds: 30));
      mission.setConnectionStatus("reconnecting in 2s");
      mission.debugRecomputeEgsLinkSevered();

      expect(mission.egsLinkSevered, isFalse);
    });

    testWidgets('does not render before the first egs.state arrives',
        (tester) async {
      // Cold start: WS connected but EGS hasn't published yet. The banner
      // would be a false positive — _egsLastSeenAt is null.
      var fakeNow = DateTime(2026, 5, 7, 10, 0, 0);
      final mission = MissionState(now: () => fakeNow);
      addTearDown(mission.dispose);
      mission.setConnectionStatus("connected");
      fakeNow = fakeNow.add(const Duration(seconds: 60));
      mission.debugRecomputeEgsLinkSevered();

      expect(mission.egsLinkSevered, isFalse);
    });
  });
}
