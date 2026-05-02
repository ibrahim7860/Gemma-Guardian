import 'dart:async';
import 'dart:convert';

import 'package:flutter_dashboard/state/mission_state.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

class _RecordingSink implements WebSocketSink {
  final List<dynamic> received = [];
  bool closed = false;

  @override
  void add(dynamic data) => received.add(data);

  @override
  Future addStream(Stream stream) async {
    await for (final v in stream) {
      received.add(v);
    }
  }

  @override
  Future close([int? closeCode, String? closeReason]) async {
    closed = true;
  }

  @override
  void addError(Object error, [StackTrace? stackTrace]) {}

  @override
  Future get done => Future.value();
}

void main() {
  group('sendOutbound', () {
    test('writes encoded JSON to attached sink when connected', () {
      final s = MissionState();
      final sink = _RecordingSink();
      s.attachSink(sink);
      s.setConnectionStatus("connected");
      s.sendOutbound({"type": "x", "n": 1});
      expect(sink.received, hasLength(1));
      expect(jsonDecode(sink.received.single as String), {"type": "x", "n": 1});
    });

    test('no-ops when sink is null', () {
      final s = MissionState();
      s.setConnectionStatus("connected");
      s.sendOutbound({"type": "x"});  // must not throw
    });

    test('no-ops when status is not "connected"', () {
      final s = MissionState();
      final sink = _RecordingSink();
      s.attachSink(sink);
      s.setConnectionStatus("connecting");
      s.sendOutbound({"type": "x"});
      expect(sink.received, isEmpty);
    });
  });

  group('markFinding + handleEcho lifecycle', () {
    test('markFinding(approve) emits envelope and sets pending', () {
      final s = MissionState();
      final sink = _RecordingSink();
      s.attachSink(sink);
      s.setConnectionStatus("connected");
      s.markFinding("f_drone1_42", "approve");
      expect(s.findingState("f_drone1_42"), ApprovalState.pending);
      final emitted = jsonDecode(sink.received.single as String) as Map<String, dynamic>;
      expect(emitted["type"], "finding_approval");
      expect(emitted["finding_id"], "f_drone1_42");
      expect(emitted["action"], "approve");
      expect(emitted["command_id"], isA<String>());
      expect(emitted["contract_version"], isA<String>());
    });

    test('handleEcho ack:finding_approval (after approve) → received', () {
      final s = MissionState();
      final sink = _RecordingSink();
      s.attachSink(sink);
      s.setConnectionStatus("connected");
      s.markFinding("f_drone1_42", "approve");
      final emitted = jsonDecode(sink.received.single as String) as Map<String, dynamic>;
      s.handleEcho({
        "type": "echo",
        "ack": "finding_approval",
        "command_id": emitted["command_id"],
        "finding_id": "f_drone1_42",
      });
      expect(s.findingState("f_drone1_42"), ApprovalState.received);
    });

    test('handleEcho ack:finding_approval (after dismiss) → dismissed', () {
      final s = MissionState();
      final sink = _RecordingSink();
      s.attachSink(sink);
      s.setConnectionStatus("connected");
      s.markFinding("f_drone1_42", "dismiss");
      final emitted = jsonDecode(sink.received.single as String) as Map<String, dynamic>;
      s.handleEcho({
        "type": "echo",
        "ack": "finding_approval",
        "command_id": emitted["command_id"],
        "finding_id": "f_drone1_42",
      });
      expect(s.findingState("f_drone1_42"), ApprovalState.dismissed);
    });

    test('handleEcho error:redis_publish_failed → failed + snackbar event', () async {
      final s = MissionState();
      final sink = _RecordingSink();
      s.attachSink(sink);
      s.setConnectionStatus("connected");
      s.markFinding("f_drone1_42", "approve");
      final events = <String>[];
      final sub = s.snackbarStream.listen(events.add);
      s.handleEcho({
        "type": "echo",
        "error": "redis_publish_failed",
        "command_id": "ignored",
        "finding_id": "f_drone1_42",
      });
      await Future<void>.delayed(Duration.zero);
      expect(s.findingState("f_drone1_42"), ApprovalState.failed);
      expect(events, hasLength(1));
      await sub.cancel();
    });

    test('applyStateUpdate promotes received → confirmed when finding.approved is true', () {
      final s = MissionState();
      final sink = _RecordingSink();
      s.attachSink(sink);
      s.setConnectionStatus("connected");
      s.markFinding("f_drone1_42", "approve");
      final emitted = jsonDecode(sink.received.single as String) as Map<String, dynamic>;
      s.handleEcho({
        "type": "echo",
        "ack": "finding_approval",
        "command_id": emitted["command_id"],
        "finding_id": "f_drone1_42",
      });
      expect(s.findingState("f_drone1_42"), ApprovalState.received);
      s.applyStateUpdate({
        "type": "state_update",
        "timestamp": "2026-05-02T12:00:00.000Z",
        "contract_version": "1.0.0",
        "active_findings": [
          {"finding_id": "f_drone1_42", "approved": true},
        ],
        "active_drones": [],
      });
      expect(s.findingState("f_drone1_42"), ApprovalState.confirmed);
    });

    test('detachSink fails all pending and emits one snackbar event', () async {
      final s = MissionState();
      final sink = _RecordingSink();
      s.attachSink(sink);
      s.setConnectionStatus("connected");
      s.markFinding("f_drone1_42", "approve");
      s.markFinding("f_drone2_5", "approve");
      final events = <String>[];
      final sub = s.snackbarStream.listen(events.add);
      s.detachSink();
      await Future<void>.delayed(Duration.zero);
      expect(s.findingState("f_drone1_42"), ApprovalState.failed);
      expect(s.findingState("f_drone2_5"), ApprovalState.failed);
      expect(events, hasLength(1));
      await sub.cancel();
    });
  });

  group('command_id uniqueness', () {
    test('1000 sequential calls produce 1000 distinct ids', () {
      final s = MissionState();
      final sink = _RecordingSink();
      s.attachSink(sink);
      s.setConnectionStatus("connected");
      for (var i = 0; i < 1000; i++) {
        s.markFinding("f_drone1_$i", "approve");
      }
      final ids = sink.received
          .map((e) => (jsonDecode(e as String) as Map<String, dynamic>)["command_id"] as String)
          .toSet();
      expect(ids.length, 1000);
    });
  });

  group('idempotency + forward-compat', () {
    test('markFinding is no-op if finding already pending (double-tap guard)', () {
      final s = MissionState();
      final sink = _RecordingSink();
      s.attachSink(sink);
      s.setConnectionStatus("connected");
      s.markFinding("f_drone1_42", "approve");
      s.markFinding("f_drone1_42", "approve"); // double-tap
      expect(sink.received, hasLength(1));
      expect(s.findingState("f_drone1_42"), ApprovalState.pending);
    });

    test('markFinding is no-op if finding already received', () {
      final s = MissionState();
      final sink = _RecordingSink();
      s.attachSink(sink);
      s.setConnectionStatus("connected");
      s.markFinding("f_drone1_42", "approve");
      final emitted = jsonDecode(sink.received.single as String) as Map<String, dynamic>;
      s.handleEcho({
        "type": "echo",
        "ack": "finding_approval",
        "command_id": emitted["command_id"],
        "finding_id": "f_drone1_42",
      });
      expect(s.findingState("f_drone1_42"), ApprovalState.received);
      s.markFinding("f_drone1_42", "approve");
      expect(sink.received, hasLength(1)); // no second envelope
    });

    test('markFinding allows retry after failed', () {
      final s = MissionState();
      final sink = _RecordingSink();
      s.attachSink(sink);
      s.setConnectionStatus("connected");
      s.markFinding("f_drone1_42", "approve");
      s.handleEcho({
        "type": "echo",
        "error": "redis_publish_failed",
        "finding_id": "f_drone1_42",
      });
      expect(s.findingState("f_drone1_42"), ApprovalState.failed);
      s.markFinding("f_drone1_42", "approve");
      expect(sink.received, hasLength(2));
      expect(s.findingState("f_drone1_42"), ApprovalState.pending);
    });

    test('applyStateUpdate(approved=true) promotes pending → confirmed (EGS-before-ack)', () {
      final s = MissionState();
      final sink = _RecordingSink();
      s.attachSink(sink);
      s.setConnectionStatus("connected");
      s.markFinding("f_drone1_42", "approve");
      expect(s.findingState("f_drone1_42"), ApprovalState.pending);
      s.applyStateUpdate({
        "type": "state_update",
        "timestamp": "2026-05-02T12:00:00.000Z",
        "contract_version": "1.0.0",
        "active_findings": [
          {"finding_id": "f_drone1_42", "approved": true},
        ],
        "active_drones": [],
      });
      expect(s.findingState("f_drone1_42"), ApprovalState.confirmed);
    });

    test('applyStateUpdate(approved=true) does NOT override dismissed', () {
      final s = MissionState();
      final sink = _RecordingSink();
      s.attachSink(sink);
      s.setConnectionStatus("connected");
      s.markFinding("f_drone1_42", "dismiss");
      final emitted = jsonDecode(sink.received.single as String) as Map<String, dynamic>;
      s.handleEcho({
        "type": "echo",
        "ack": "finding_approval",
        "command_id": emitted["command_id"],
        "finding_id": "f_drone1_42",
      });
      expect(s.findingState("f_drone1_42"), ApprovalState.dismissed);
      s.applyStateUpdate({
        "type": "state_update",
        "timestamp": "2026-05-02T12:01:00.000Z",
        "contract_version": "1.0.0",
        "active_findings": [
          {"finding_id": "f_drone1_42", "approved": true},
        ],
        "active_drones": [],
      });
      expect(s.findingState("f_drone1_42"), ApprovalState.dismissed);
    });
  });
}
