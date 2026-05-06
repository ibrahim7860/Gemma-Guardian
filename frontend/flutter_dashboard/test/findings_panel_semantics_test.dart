import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:flutter_dashboard/state/mission_state.dart';
import 'package:flutter_dashboard/widgets/findings_panel.dart';

void main() {
  testWidgets('FindingsPanel emits stable Semantics identifier per tile',
      (tester) async {
    final mission = MissionState();
    mission.applyStateUpdate({
      'type': 'state_update',
      'active_findings': [
        {
          'finding_id': 'finding-abc',
          'type': 'victim',
          'severity': 4,
          'confidence': 0.85,
          'source_drone_id': 'drone1',
          'timestamp': '2026-05-06T10:00:00.000Z',
          'visual_description':
              'Person trapped under collapsed wall, visible from above',
        }
      ],
    });

    await tester.pumpWidget(
      MaterialApp(
        home: ChangeNotifierProvider<MissionState>.value(
          value: mission,
          child: const Scaffold(body: FindingsPanel()),
        ),
      ),
    );
    await tester.pump();

    expect(
      find.bySemanticsIdentifier('finding-tile-finding-abc'),
      findsOneWidget,
      reason:
          'FindingsPanel must emit Semantics(identifier: "finding-tile-<id>") '
          'so the Playwright DOM-render test (test_e2e_playwright_dom_render.py) '
          'has a stable accessibility hook.',
    );
  });
}
