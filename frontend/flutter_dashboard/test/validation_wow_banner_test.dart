/// Phase 2 widget tests for the wow-moment validation banner.
///
/// Covers the rev-2 plan Phase-2 test matrix #2 (8 cases):
///   1. Hidden state — empty log → SizedBox.shrink, banner not in tree.
///   2. 1 invalid attempt — red FAILED chip + verbatim corrective text.
///   3. Invalid + valid sequence — attempt 1 red, attempt 2 green.
///   4. failed_after_retries shape — all attempts invalid, no green chip.
///   5. success_first_try — single green chip, no corrective text.
///   6. Semantics identifiers present and findable.
///   7. Animated entry — pumpAndSettle confirms fade-in completes.
///   8. No rule_id but corrective_text present → renders text without rule chip.
///
/// The literal corrective_text asserted in cases 2/3/6/7 matches
/// `RULE_REGISTRY[ASSIGNMENT_TOTAL_MISMATCH].corrective_template.format(
///    assigned=27, total=25)` from `shared/contracts/rules.py`.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import 'package:flutter_dashboard/state/mission_state.dart';
import 'package:flutter_dashboard/widgets/validation_wow_banner.dart';

const String _kCorrectiveText =
    'Your assignments cover 27 points but 25 are available. '
    'Reassign so every point is covered exactly once.';

Map<String, dynamic> _envelopeWith(List<Map<String, dynamic>> attempts) => {
      'type': 'state_update',
      'egs_state': {
        'mission_id': 'm1',
        'replan_in_flight_attempt_log': attempts,
      },
      'active_findings': const [],
      'active_drones': const [],
    };

Widget _mount(MissionState mission) {
  return MaterialApp(
    home: ChangeNotifierProvider<MissionState>.value(
      value: mission,
      child: const Scaffold(body: ValidationWowBanner()),
    ),
  );
}

void main() {
  group('ValidationWowBanner', () {
    testWidgets('case 1 — hidden when replan log is empty', (tester) async {
      final mission = MissionState();
      addTearDown(mission.dispose);
      // No state_update at all → empty log by default.
      await tester.pumpWidget(_mount(mission));
      await tester.pump();

      expect(find.bySemanticsIdentifier('validation-wow-banner'), findsNothing);
      // The widget itself mounts, but its child is SizedBox.shrink.
      expect(find.text('VALIDATION LOOP'), findsNothing);
    });

    testWidgets('case 2 — 1 invalid attempt renders red FAILED + corrective text',
        (tester) async {
      final mission = MissionState();
      addTearDown(mission.dispose);
      mission.applyStateUpdate(_envelopeWith([
        {
          'timestamp': '2026-05-12T18:00:00.000Z',
          'attempt_n': 1,
          'valid': false,
          'rule_id': 'ASSIGNMENT_TOTAL_MISMATCH',
          'corrective_text': _kCorrectiveText,
        },
      ]));

      await tester.pumpWidget(_mount(mission));
      await tester.pumpAndSettle();

      expect(find.bySemanticsIdentifier('validation-wow-banner'), findsOneWidget);
      expect(find.text('FAILED'), findsOneWidget);
      expect(find.text('PASSED'), findsNothing);
      expect(
        find.textContaining('Your assignments cover 27 points but 25 are available'),
        findsOneWidget,
      );
      expect(find.text('ASSIGNMENT_TOTAL_MISMATCH'), findsOneWidget);
    });

    testWidgets('case 3 — invalid + valid sequence: red then green, both visible',
        (tester) async {
      final mission = MissionState();
      addTearDown(mission.dispose);
      mission.applyStateUpdate(_envelopeWith([
        {
          'timestamp': '2026-05-12T18:00:00.000Z',
          'attempt_n': 1,
          'valid': false,
          'rule_id': 'ASSIGNMENT_TOTAL_MISMATCH',
          'corrective_text': _kCorrectiveText,
        },
        {
          'timestamp': '2026-05-12T18:00:02.500Z',
          'attempt_n': 2,
          'valid': true,
        },
      ]));

      await tester.pumpWidget(_mount(mission));
      await tester.pumpAndSettle();

      expect(find.bySemanticsIdentifier('validation-attempt-1'), findsOneWidget);
      expect(find.bySemanticsIdentifier('validation-attempt-2'), findsOneWidget);
      expect(find.text('FAILED'), findsOneWidget);
      expect(find.text('PASSED'), findsOneWidget);
    });

    testWidgets(
        'case 4 — failed_after_retries shape: all attempts red, no green chip',
        (tester) async {
      final mission = MissionState();
      addTearDown(mission.dispose);
      mission.applyStateUpdate(_envelopeWith([
        for (var i = 1; i <= 3; i++)
          {
            'timestamp':
                '2026-05-12T18:00:0$i.000Z',
            'attempt_n': i,
            'valid': false,
            'rule_id': 'ASSIGNMENT_TOTAL_MISMATCH',
            'corrective_text': _kCorrectiveText,
          },
      ]));

      await tester.pumpWidget(_mount(mission));
      await tester.pumpAndSettle();

      expect(find.text('FAILED'), findsNWidgets(3));
      expect(find.text('PASSED'), findsNothing);
    });

    testWidgets('case 5 — success_first_try: green chip, no corrective text shown',
        (tester) async {
      final mission = MissionState();
      addTearDown(mission.dispose);
      mission.applyStateUpdate(_envelopeWith([
        {
          'timestamp': '2026-05-12T18:00:00.000Z',
          'attempt_n': 1,
          'valid': true,
        },
      ]));

      await tester.pumpWidget(_mount(mission));
      await tester.pumpAndSettle();

      expect(find.text('PASSED'), findsOneWidget);
      expect(find.text('FAILED'), findsNothing);
      // No corrective text / rule chip when the model succeeds on the first try.
      expect(find.text('ASSIGNMENT_TOTAL_MISMATCH'), findsNothing);
      expect(
        find.textContaining('Your assignments cover'),
        findsNothing,
      );
    });

    testWidgets('case 6 — Semantics identifiers are present and findable',
        (tester) async {
      final mission = MissionState();
      addTearDown(mission.dispose);
      mission.applyStateUpdate(_envelopeWith([
        {
          'timestamp': '2026-05-12T18:00:00.000Z',
          'attempt_n': 1,
          'valid': false,
          'rule_id': 'ASSIGNMENT_TOTAL_MISMATCH',
          'corrective_text': _kCorrectiveText,
        },
        {
          'timestamp': '2026-05-12T18:00:02.500Z',
          'attempt_n': 2,
          'valid': true,
        },
      ]));

      await tester.pumpWidget(_mount(mission));
      await tester.pumpAndSettle();

      expect(find.bySemanticsIdentifier('validation-wow-banner'), findsOneWidget);
      expect(find.bySemanticsIdentifier('validation-attempt-1'), findsOneWidget);
      expect(find.bySemanticsIdentifier('validation-attempt-1-outcome'),
          findsOneWidget);
      expect(find.bySemanticsIdentifier('validation-attempt-1-text'),
          findsOneWidget);
      expect(find.bySemanticsIdentifier('validation-attempt-2'), findsOneWidget);
      expect(find.bySemanticsIdentifier('validation-attempt-2-outcome'),
          findsOneWidget);
      expect(find.bySemanticsIdentifier('validation-attempt-2-text'),
          findsOneWidget);
    });

    testWidgets('case 7 — animated entry: fade-in completes within 300ms',
        (tester) async {
      final mission = MissionState();
      addTearDown(mission.dispose);

      // Mount empty first.
      await tester.pumpWidget(_mount(mission));
      await tester.pump();

      // Inject the first attempt → AnimatedSwitcher should fade in.
      mission.applyStateUpdate(_envelopeWith([
        {
          'timestamp': '2026-05-12T18:00:00.000Z',
          'attempt_n': 1,
          'valid': false,
          'rule_id': 'ASSIGNMENT_TOTAL_MISMATCH',
          'corrective_text': _kCorrectiveText,
        },
      ]));

      // Mid-animation: a FadeTransition exists with opacity < 1.
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
      expect(find.byType(FadeTransition), findsWidgets);

      // Settle: fade-in completes, banner fully visible.
      await tester.pumpAndSettle(const Duration(milliseconds: 300));
      expect(find.bySemanticsIdentifier('validation-wow-banner'), findsOneWidget);
      expect(find.text('FAILED'), findsOneWidget);
    });

    testWidgets(
        'case 8 — no rule_id but corrective_text present → renders text without rule chip',
        (tester) async {
      final mission = MissionState();
      addTearDown(mission.dispose);
      mission.applyStateUpdate(_envelopeWith([
        {
          'timestamp': '2026-05-12T18:00:00.000Z',
          'attempt_n': 1,
          'valid': false,
          // No rule_id field.
          'corrective_text': _kCorrectiveText,
        },
      ]));

      await tester.pumpWidget(_mount(mission));
      await tester.pumpAndSettle();

      expect(find.text('FAILED'), findsOneWidget);
      expect(
        find.textContaining('Your assignments cover 27 points but 25 are available'),
        findsOneWidget,
      );
      // No rule_id chip rendered.
      expect(find.text('ASSIGNMENT_TOTAL_MISMATCH'), findsNothing);
    });
  });
}
