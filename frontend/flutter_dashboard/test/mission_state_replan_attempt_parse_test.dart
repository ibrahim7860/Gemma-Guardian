/// Phase 2 unit tests for MissionState.replanInFlightAttemptLog parsing.
///
/// Covers the rev-2 plan Phase-2 test matrix #1 (5 cases):
///   1. 3-attempt list parsed from a hand-crafted egs.state JSON.
///   2. Empty list defaults to empty (no nulls).
///   3. Missing field handled gracefully (legacy / pre-version-bump envelope).
///   4. Malformed entry (missing required `attempt_n`) dropped, rest preserved.
///   5. notifyListeners() fires when the field changes.
library;

import 'package:flutter_dashboard/state/mission_state.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> _envelope({
  Map<String, dynamic>? egsStateOverride,
}) {
  return {
    'type': 'state_update',
    'egs_state': egsStateOverride ?? <String, dynamic>{'mission_id': 'm1'},
    'active_findings': const [],
    'active_drones': const [],
  };
}

void main() {
  group('MissionState.replanInFlightAttemptLog parsing', () {
    test('parses 3-attempt list from hand-crafted egs.state JSON', () {
      final mission = MissionState();
      addTearDown(mission.dispose);

      mission.applyStateUpdate(_envelope(egsStateOverride: {
        'mission_id': 'm1',
        'replan_in_flight_attempt_log': [
          {
            'timestamp': '2026-05-12T18:00:00.000Z',
            'attempt_n': 1,
            'valid': false,
            'rule_id': 'ASSIGNMENT_TOTAL_MISMATCH',
            'corrective_text':
                'Your assignments cover 27 points but 25 are available. Reassign so every point is covered exactly once.',
            'details': {'assigned': 27, 'total': 25},
          },
          {
            'timestamp': '2026-05-12T18:00:02.500Z',
            'attempt_n': 2,
            'valid': false,
            'rule_id': 'ASSIGNMENT_DUPLICATE_POINT',
            'corrective_text': 'duplicate corrective text',
          },
          {
            'timestamp': '2026-05-12T18:00:05.000Z',
            'attempt_n': 3,
            'valid': true,
          },
        ],
      }));

      final log = mission.replanInFlightAttemptLog;
      expect(log, hasLength(3));
      expect(log[0].attemptN, 1);
      expect(log[0].valid, isFalse);
      expect(log[0].ruleId, 'ASSIGNMENT_TOTAL_MISMATCH');
      expect(
        log[0].correctiveText,
        contains('Your assignments cover 27 points but 25 are available'),
      );
      expect(log[0].details['assigned'], 27);
      expect(log[1].attemptN, 2);
      expect(log[1].valid, isFalse);
      expect(log[2].attemptN, 3);
      expect(log[2].valid, isTrue);
      expect(log[2].ruleId, isNull);
      expect(log[2].correctiveText, isNull);
    });

    test('empty list defaults to empty (no nulls)', () {
      final mission = MissionState();
      addTearDown(mission.dispose);

      mission.applyStateUpdate(_envelope(egsStateOverride: {
        'mission_id': 'm1',
        'replan_in_flight_attempt_log': const [],
      }));

      expect(mission.replanInFlightAttemptLog, isEmpty);
    });

    test('missing field handled gracefully (legacy envelope)', () {
      final mission = MissionState();
      addTearDown(mission.dispose);

      // No replan_in_flight_attempt_log key — simulates a pre-1.1.0 envelope.
      mission.applyStateUpdate(_envelope(egsStateOverride: {
        'mission_id': 'm1',
      }));

      expect(mission.replanInFlightAttemptLog, isEmpty);
      expect(mission.replanInFlightAttemptLog, isA<List<ReplanAttempt>>());
    });

    test('malformed entry dropped, remaining entries preserved', () {
      final mission = MissionState();
      addTearDown(mission.dispose);

      mission.applyStateUpdate(_envelope(egsStateOverride: {
        'mission_id': 'm1',
        'replan_in_flight_attempt_log': [
          // Missing attempt_n — must be dropped.
          {
            'timestamp': '2026-05-12T18:00:00.000Z',
            'valid': false,
            'rule_id': 'ASSIGNMENT_TOTAL_MISMATCH',
          },
          // Valid entry — must be preserved.
          {
            'timestamp': '2026-05-12T18:00:02.500Z',
            'attempt_n': 2,
            'valid': true,
          },
          // attempt_n=0 below the minimum — must be dropped.
          {
            'timestamp': '2026-05-12T18:00:03.000Z',
            'attempt_n': 0,
            'valid': false,
          },
        ],
      }));

      final log = mission.replanInFlightAttemptLog;
      expect(log, hasLength(1));
      expect(log.single.attemptN, 2);
      expect(log.single.valid, isTrue);
    });

    test('notifyListeners() fires when the field changes', () {
      final mission = MissionState();
      addTearDown(mission.dispose);
      var notifications = 0;
      mission.addListener(() => notifications++);

      mission.applyStateUpdate(_envelope(egsStateOverride: {
        'mission_id': 'm1',
        'replan_in_flight_attempt_log': [
          {
            'timestamp': '2026-05-12T18:00:00.000Z',
            'attempt_n': 1,
            'valid': false,
            'rule_id': 'ASSIGNMENT_TOTAL_MISMATCH',
            'corrective_text': 'Your assignments cover 27 points but 25 are available.',
          },
        ],
      }));

      expect(notifications, greaterThanOrEqualTo(1),
          reason: 'applyStateUpdate must fire notifyListeners');
      expect(mission.replanInFlightAttemptLog, hasLength(1));

      final beforeSecond = notifications;
      mission.applyStateUpdate(_envelope(egsStateOverride: {
        'mission_id': 'm1',
        'replan_in_flight_attempt_log': [
          {
            'timestamp': '2026-05-12T18:00:00.000Z',
            'attempt_n': 1,
            'valid': false,
            'rule_id': 'ASSIGNMENT_TOTAL_MISMATCH',
            'corrective_text': 'Your assignments cover 27 points but 25 are available.',
          },
          {
            'timestamp': '2026-05-12T18:00:02.500Z',
            'attempt_n': 2,
            'valid': true,
          },
        ],
      }));

      expect(notifications, greaterThan(beforeSecond),
          reason: 'extending the log fires another notifyListeners');
      expect(mission.replanInFlightAttemptLog, hasLength(2));
    });
  });
}
