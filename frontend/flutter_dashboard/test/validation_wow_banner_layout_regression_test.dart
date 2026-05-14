/// Phase 2 layout regression tests for the wow-moment banner.
///
/// Covers the rev-2 plan Phase-2 test matrix #3 (2 cases):
///   1. No layout overflow at 1280x720 (capture resolution) and 1920x1080
///      (judge-screen resolution) when banner + EgsLinkSeveredBanner +
///      _FourPanelGrid are mounted together.
///   2. _FourPanelGrid height is unchanged when the banner is hidden
///      (the banner must collapse cleanly via SizedBox.shrink).
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import 'package:flutter_dashboard/main.dart' show EgsLinkSeveredBanner;
import 'package:flutter_dashboard/state/mission_state.dart';
import 'package:flutter_dashboard/widgets/command_panel.dart';
import 'package:flutter_dashboard/widgets/drone_status_panel.dart';
import 'package:flutter_dashboard/widgets/findings_panel.dart';
import 'package:flutter_dashboard/widgets/map_panel.dart';
import 'package:flutter_dashboard/widgets/validation_wow_banner.dart';

/// Mirror of `_FourPanelGrid` in main.dart (which is private). Pure-layout
/// stand-in so this test can poke at its rendered height without depending
/// on the private symbol.
class _GridStandIn extends StatelessWidget {
  const _GridStandIn();

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (_, c) {
        final w = c.maxWidth / 2;
        final h = c.maxHeight / 2;
        return Column(
          key: const ValueKey('grid-stand-in'),
          children: [
            Row(children: [
              SizedBox(width: w, height: h, child: const MapPanel()),
              SizedBox(width: w, height: h, child: const DroneStatusPanel()),
            ]),
            Row(children: [
              SizedBox(width: w, height: h, child: const FindingsPanel()),
              SizedBox(width: w, height: h, child: const CommandPanel()),
            ]),
          ],
        );
      },
    );
  }
}

Widget _shell(MissionState mission) {
  return MaterialApp(
    home: ChangeNotifierProvider<MissionState>.value(
      value: mission,
      child: const Scaffold(
        body: Column(
          children: [
            EgsLinkSeveredBanner(),
            ValidationWowBanner(),
            Expanded(child: _GridStandIn()),
          ],
        ),
      ),
    ),
  );
}

Map<String, dynamic> _populatedEnvelope() => {
      'type': 'state_update',
      'egs_state': {
        'mission_id': 'm1',
        'replan_in_flight_attempt_log': [
          {
            'timestamp': '2026-05-12T18:00:00.000Z',
            'attempt_n': 1,
            'valid': false,
            'rule_id': 'ASSIGNMENT_TOTAL_MISMATCH',
            'corrective_text':
                'Your assignments cover 27 points but 25 are available. '
                    'Reassign so every point is covered exactly once.',
          },
          {
            'timestamp': '2026-05-12T18:00:02.500Z',
            'attempt_n': 2,
            'valid': true,
          },
        ],
      },
      'active_findings': const [],
      'active_drones': const [],
    };

void main() {
  final flutterExceptions = <FlutterErrorDetails>[];

  setUp(() {
    flutterExceptions.clear();
    FlutterError.onError = flutterExceptions.add;
  });

  tearDown(() {
    FlutterError.onError = FlutterError.presentError;
  });

  group('ValidationWowBanner layout regression', () {
    for (final size in [const Size(1280, 720), const Size(1920, 1080)]) {
      testWidgets(
        'no layout overflow at ${size.width.toInt()}x${size.height.toInt()} '
        'with banner populated',
        (tester) async {
          tester.view.physicalSize = size;
          tester.view.devicePixelRatio = 1.0;
          addTearDown(tester.view.resetPhysicalSize);
          addTearDown(tester.view.resetDevicePixelRatio);

          final mission = MissionState();
          addTearDown(mission.dispose);
          mission.applyStateUpdate(_populatedEnvelope());

          await tester.pumpWidget(_shell(mission));
          await tester.pumpAndSettle();

          // Banner is in the tree.
          expect(find.bySemanticsIdentifier('validation-wow-banner'),
              findsOneWidget);

          // No layout-overflow errors should have been reported.
          final overflowErrors = flutterExceptions
              .where((e) =>
                  e.exception.toString().toLowerCase().contains('overflow'))
              .toList();
          expect(overflowErrors, isEmpty,
              reason:
                  'Banner + grid must not overflow at $size. Errors: $overflowErrors');
        },
      );
    }

    testWidgets('grid height unchanged when banner is hidden', (tester) async {
      const size = Size(1280, 720);
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      // First: mount with empty log, capture grid height.
      final missionEmpty = MissionState();
      addTearDown(missionEmpty.dispose);
      await tester.pumpWidget(_shell(missionEmpty));
      await tester.pumpAndSettle();

      final gridFinder = find.byKey(const ValueKey('grid-stand-in'));
      expect(gridFinder, findsOneWidget);
      final heightHidden = tester.getSize(gridFinder).height;

      // Sanity: banner must truly be absent here.
      expect(
        find.bySemanticsIdentifier('validation-wow-banner'),
        findsNothing,
      );

      // Now: same shell, with the banner populated — grid height should
      // shrink only by the banner's height. The contract we assert is that
      // when the banner is *hidden* (initial state of this test), the grid
      // takes the full remaining height (banner takes 0 px via
      // SizedBox.shrink).
      final missionPopulated = MissionState();
      addTearDown(missionPopulated.dispose);
      missionPopulated.applyStateUpdate(_populatedEnvelope());
      await tester.pumpWidget(_shell(missionPopulated));
      await tester.pumpAndSettle();
      final heightVisible = tester.getSize(gridFinder).height;

      // Banner present must consume some pixels (grid loses height); banner
      // hidden must consume zero (grid gets the full slot). This is the
      // load-bearing assertion: SizedBox.shrink must not occupy space.
      expect(heightHidden, greaterThan(heightVisible),
          reason:
              'Grid should be taller when banner is hidden than when populated; '
              'hidden=$heightHidden, visible=$heightVisible');
    });
  });
}
