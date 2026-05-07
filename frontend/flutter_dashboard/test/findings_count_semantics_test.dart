/// GATE 2 (Task 7b): per-type findings-count Semantics hooks.
///
/// The Playwright e2e at
/// `frontend/ws_bridge/tests/test_e2e_playwright_egs_findings.py`
/// queries the dashboard semantics tree for
/// `findings-count-<type>` to prove the EGS-driven count flowed through
/// the bridge into the rendered DOM. These widget tests pin that
/// contract on the Flutter side so a refactor that drops a Semantics
/// wrapper fails fast (here, in <1s) instead of failing 60s into the
/// e2e subprocess fan-out with a confusing "selector not attached".
///
/// The summary widget renders all five locked types regardless of
/// zero/non-zero count for layout stability, so both `victim` (>0)
/// and `smoke` (==0) identifiers are expected to attach.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:flutter_dashboard/state/mission_state.dart';
import 'package:flutter_dashboard/widgets/findings_panel.dart';

Map<String, dynamic> _stateUpdateWith(Map<String, int> counts) => {
      'type': 'state_update',
      'egs_state': {
        'mission_id': 'm1',
        'findings_count_by_type': counts,
      },
      'active_drones': const [],
      'active_findings': const [],
    };

Widget _wrap(MissionState mission) {
  return MaterialApp(
    home: ChangeNotifierProvider<MissionState>.value(
      value: mission,
      child: const Scaffold(body: FindingsCountSummary()),
    ),
  );
}

void main() {
  group('FindingsCountSummary semantics identifiers', () {
    testWidgets(
      'renders findings-count-<type> semantics for each locked type',
      (tester) async {
        final mission = MissionState();
        addTearDown(mission.dispose);
        mission.applyStateUpdate(_stateUpdateWith({
          'victim': 3,
          'fire': 1,
          'smoke': 0,
          'damaged_structure': 0,
          'blocked_route': 0,
        }));

        await tester.pumpWidget(_wrap(mission));
        await tester.pump();

        // Non-zero types must attach.
        expect(
          find.bySemanticsIdentifier('findings-count-victim'),
          findsOneWidget,
          reason:
              'FindingsCountSummary must emit Semantics(identifier: '
              '"findings-count-victim") so the Playwright e2e can verify '
              'the EGS-driven count reached the dashboard DOM.',
        );
        expect(
          find.bySemanticsIdentifier('findings-count-fire'),
          findsOneWidget,
        );

        // The widget renders zero-count entries for layout stability,
        // so smoke/damaged_structure/blocked_route also attach. The
        // Playwright e2e relies on this — DO NOT collapse zero counts
        // without also updating the e2e's victim-only assertion to
        // tolerate missing zero-type identifiers.
        expect(
          find.bySemanticsIdentifier('findings-count-smoke'),
          findsOneWidget,
        );
        expect(
          find.bySemanticsIdentifier('findings-count-damaged_structure'),
          findsOneWidget,
        );
        expect(
          find.bySemanticsIdentifier('findings-count-blocked_route'),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'renders all five identifiers even when egs_state has no '
      'findings_count_by_type field (cold-start tolerance)',
      (tester) async {
        // egs_state is present but missing findings_count_by_type — common
        // before the first EGS publish lands.
        final mission = MissionState();
        addTearDown(mission.dispose);
        mission.applyStateUpdate({
          'type': 'state_update',
          'egs_state': {'mission_id': 'm1'},
          'active_drones': const [],
          'active_findings': const [],
        });

        await tester.pumpWidget(_wrap(mission));
        await tester.pump();

        for (final t in const [
          'victim',
          'fire',
          'smoke',
          'damaged_structure',
          'blocked_route',
        ]) {
          expect(
            find.bySemanticsIdentifier('findings-count-$t'),
            findsOneWidget,
            reason: 'cold-start must still expose findings-count-$t',
          );
        }
      },
    );

    testWidgets(
      'reflects updated counts on subsequent state updates',
      (tester) async {
        final mission = MissionState();
        addTearDown(mission.dispose);
        mission.applyStateUpdate(_stateUpdateWith({
          'victim': 1,
          'fire': 0,
          'smoke': 0,
          'damaged_structure': 0,
          'blocked_route': 0,
        }));

        await tester.pumpWidget(_wrap(mission));
        await tester.pump();

        // Each chip renders the count as `<type>: <n>` text.
        expect(find.text('victim: 1'), findsOneWidget);

        // Drive a second state_update with a higher count and re-pump.
        mission.applyStateUpdate(_stateUpdateWith({
          'victim': 5,
          'fire': 2,
          'smoke': 0,
          'damaged_structure': 0,
          'blocked_route': 0,
        }));
        await tester.pump();

        // Identifier still attaches.
        expect(
          find.bySemanticsIdentifier('findings-count-victim'),
          findsOneWidget,
        );
        // The visible text reflects the new count and the old text is gone.
        expect(find.text('victim: 5'), findsOneWidget);
        expect(find.text('victim: 1'), findsNothing);
        // Sibling type updated too.
        expect(find.text('fire: 2'), findsOneWidget);
      },
    );
  });
}
