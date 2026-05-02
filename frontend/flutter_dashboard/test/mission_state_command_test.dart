import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_dashboard/state/mission_state.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

class _RecordingSink implements WebSocketSink {
  final List<dynamic> sent = [];
  @override
  void add(dynamic data) => sent.add(data);
  @override
  Future close([int? closeCode, String? closeReason]) async {}
  @override
  Future addStream(Stream stream) async {}
  @override
  void addError(Object error, [StackTrace? stackTrace]) {}
  @override
  Future get done => Future.value();
}

void main() {
  group('MissionState command state machine', () {
    late MissionState state;
    late _RecordingSink sink;

    setUp(() {
      state = MissionState();
      sink = _RecordingSink();
      state.attachSink(sink);
      state.setConnectionStatus("connected");
    });

    test('submit command transitions sending -> translating on bridge ack', () {
      final cid = state.submitOperatorCommand(rawText: "recall drone1", language: "en");
      expect(state.commandState(cid), CommandState.sending);
      state.handleEcho({
        "type": "echo",
        "ack": "operator_command_received",
        "command_id": cid,
      });
      expect(state.commandState(cid), CommandState.translating);
    });

    test('command_translation transitions translating -> ready and stores preview', () {
      final cid = state.submitOperatorCommand(rawText: "recall drone1", language: "en");
      state.handleEcho({"type": "echo", "ack": "operator_command_received", "command_id": cid});
      state.applyTranslation({
        "type": "command_translation",
        "command_id": cid,
        "structured": {"command": "recall_drone", "args": {"drone_id": "drone1", "reason": "x"}},
        "valid": true,
        "preview_text": "Will recall drone1",
        "preview_text_in_operator_language": "Will recall drone1",
        "contract_version": "1.0.0",
      });
      expect(state.commandState(cid), CommandState.ready);
      expect(state.commandTranslation(cid)?["preview_text"], "Will recall drone1");
    });

    test('dispatch transitions ready -> dispatched and emits dispatch frame', () {
      final cid = state.submitOperatorCommand(rawText: "recall drone1", language: "en");
      state.handleEcho({"type": "echo", "ack": "operator_command_received", "command_id": cid});
      state.applyTranslation({
        "type": "command_translation",
        "command_id": cid,
        "structured": {"command": "recall_drone", "args": {"drone_id": "drone1", "reason": "x"}},
        "valid": true,
        "preview_text": "Will recall drone1",
        "preview_text_in_operator_language": "Will recall drone1",
        "contract_version": "1.0.0",
      });
      state.dispatchActiveCommand();
      state.handleEcho({"type": "echo", "ack": "operator_command_dispatch", "command_id": cid});
      expect(state.commandState(cid), CommandState.dispatched);
      // Sink should have sent operator_command then operator_command_dispatch
      expect(sink.sent.length, 2);
    });

    test('rephrase clears active command bookkeeping', () {
      final cid = state.submitOperatorCommand(rawText: "recall drone1", language: "en");
      state.handleEcho({"type": "echo", "ack": "operator_command_received", "command_id": cid});
      state.applyTranslation({
        "type": "command_translation",
        "command_id": cid,
        "structured": {"command": "recall_drone", "args": {"drone_id": "drone1", "reason": "x"}},
        "valid": true,
        "preview_text": "Will recall drone1",
        "preview_text_in_operator_language": "Will recall drone1",
        "contract_version": "1.0.0",
      });
      state.rephraseActiveCommand();
      expect(state.activeCommandId, isNull);
    });

    test('detachSink during translating flips state to failed', () {
      final cid = state.submitOperatorCommand(rawText: "recall drone1", language: "en");
      state.handleEcho({"type": "echo", "ack": "operator_command_received", "command_id": cid});
      state.detachSink();
      expect(state.commandState(cid), CommandState.failed);
    });

    test('late translation after timeout is dropped silently (1B)', () async {
      final cid = state.submitOperatorCommand(
        rawText: "recall drone1", language: "en",
        translationTimeout: const Duration(milliseconds: 50),
      );
      state.handleEcho({"type": "echo", "ack": "operator_command_received", "command_id": cid});
      await Future.delayed(const Duration(milliseconds: 100));
      expect(state.commandState(cid), CommandState.failed);
      // Late translation arrives — must not revive the panel
      state.applyTranslation({
        "type": "command_translation",
        "command_id": cid,
        "structured": {"command": "recall_drone", "args": {"drone_id": "drone1", "reason": "x"}},
        "valid": true,
        "preview_text": "Will recall drone1",
        "preview_text_in_operator_language": "Will recall drone1",
        "contract_version": "1.0.0",
      });
      expect(state.commandState(cid), CommandState.failed);
    });

    test('redis_publish_failed echo flips command to failed', () {
      final cid = state.submitOperatorCommand(rawText: "recall drone1", language: "en");
      state.handleEcho({
        "type": "echo",
        "error": "redis_publish_failed",
        "command_id": cid,
      });
      expect(state.commandState(cid), CommandState.failed);
    });

    test('second submit orphans the first cid: timer cancelled, bookkeeping dropped', () async {
      // Adversarial finding #4: prior cid's Timer must not fire after orphan.
      // Use a short timeout so the test runs fast and a leaked timer would
      // produce an observable snackbar.
      final snackbarEvents = <String>[];
      final sub = state.snackbarStream.listen(snackbarEvents.add);
      final cid1 = state.submitOperatorCommand(
        rawText: "first", language: "en",
        translationTimeout: const Duration(milliseconds: 50),
      );
      final cid2 = state.submitOperatorCommand(rawText: "second", language: "en");
      expect(state.activeCommandId, cid2);
      // cid1 must be dropped from _commandActions entirely
      expect(state.commandState(cid1), isNull);
      // Wait past cid1's would-be timeout — no snackbar should fire
      await Future.delayed(const Duration(milliseconds: 100));
      expect(snackbarEvents, isEmpty);
      await sub.cancel();
    });

    test('late translation for orphaned cid is dropped silently', () async {
      // Adversarial finding #4 + late-arrival: a translation arriving for
      // a cid that was orphaned (not in _commandActions) must not surface.
      final cid1 = state.submitOperatorCommand(rawText: "first", language: "en");
      final cid2 = state.submitOperatorCommand(rawText: "second", language: "en");
      // cid1 is orphaned. Apply a translation for it.
      state.applyTranslation({
        "type": "command_translation",
        "command_id": cid1,
        "structured": {"command": "recall_drone", "args": {"drone_id": "drone1", "reason": "x"}},
        "valid": true,
        "preview_text": "Will recall drone1",
        "preview_text_in_operator_language": "Will recall drone1",
        "contract_version": "1.0.0",
      });
      // Active panel must remain on cid2 (in sending — no echo yet)
      expect(state.activeCommandId, cid2);
      expect(state.commandTranslation(cid1), isNull);
      expect(state.commandState(cid1), isNull);
    });

    test('dispatch is non-optimistic: ready -> dispatching, ack -> dispatched', () {
      // Adversarial finding #5: don't optimistically transition to dispatched.
      final cid = state.submitOperatorCommand(rawText: "recall drone1", language: "en");
      state.handleEcho({"type": "echo", "ack": "operator_command_received", "command_id": cid});
      state.applyTranslation({
        "type": "command_translation",
        "command_id": cid,
        "structured": {"command": "recall_drone", "args": {"drone_id": "drone1", "reason": "x"}},
        "valid": true,
        "preview_text": "Will recall drone1",
        "preview_text_in_operator_language": "Will recall drone1",
        "contract_version": "1.0.0",
      });
      state.dispatchActiveCommand();
      expect(state.commandState(cid), CommandState.dispatching);  // not dispatched yet
      state.handleEcho({"type": "echo", "ack": "operator_command_dispatch", "command_id": cid});
      expect(state.commandState(cid), CommandState.dispatched);
    });

    test('redis_publish_failed on dispatch returns to ready (not failed)', () {
      // Adversarial finding #5: a transient Redis blip on dispatch must not
      // burn the translation; operator can re-tap DISPATCH from ready.
      final cid = state.submitOperatorCommand(rawText: "recall drone1", language: "en");
      state.handleEcho({"type": "echo", "ack": "operator_command_received", "command_id": cid});
      state.applyTranslation({
        "type": "command_translation",
        "command_id": cid,
        "structured": {"command": "recall_drone", "args": {"drone_id": "drone1", "reason": "x"}},
        "valid": true,
        "preview_text": "Will recall drone1",
        "preview_text_in_operator_language": "Will recall drone1",
        "contract_version": "1.0.0",
      });
      state.dispatchActiveCommand();
      expect(state.commandState(cid), CommandState.dispatching);
      state.handleEcho({
        "type": "echo",
        "error": "redis_publish_failed",
        "command_id": cid,
      });
      // Returns to ready, NOT failed — translation is still valid
      expect(state.commandState(cid), CommandState.ready);
    });
  });
}
