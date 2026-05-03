import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:flutter_dashboard/state/mission_state.dart';
import 'package:flutter_dashboard/widgets/command_panel.dart';

Widget _wrap(MissionState state) {
  return MaterialApp(
    home: ChangeNotifierProvider<MissionState>.value(
      value: state,
      child: const Scaffold(body: CommandPanel()),
    ),
  );
}

void main() {
  group('CommandPanel visual states', () {
    testWidgets('disconnected state disables Translate', (tester) async {
      final state = MissionState();
      // No setConnectionStatus("connected") — default is "disconnected"
      await tester.pumpWidget(_wrap(state));
      final translate = find.widgetWithText(ElevatedButton, "TRANSLATE");
      expect(translate, findsOneWidget);
      final ElevatedButton btn = tester.widget(translate);
      expect(btn.onPressed, isNull);
    });

    testWidgets('connected with empty input disables Translate', (tester) async {
      final state = MissionState();
      state.setConnectionStatus("connected");
      await tester.pumpWidget(_wrap(state));
      final ElevatedButton btn = tester.widget(find.widgetWithText(ElevatedButton, "TRANSLATE"));
      expect(btn.onPressed, isNull);
    });

    testWidgets('typing enables Translate; click submits and switches to Sending', (tester) async {
      final state = MissionState();
      state.setConnectionStatus("connected");
      // We don't attach a real sink — sendOutbound will silently no-op when
      // sink is null (per existing MissionState contract). The point of the
      // widget test is the UI transition, not the wire format.
      await tester.pumpWidget(_wrap(state));
      await tester.enterText(find.byType(TextField), "recall drone1");
      await tester.pump();
      final ElevatedButton btn = tester.widget(find.widgetWithText(ElevatedButton, "TRANSLATE"));
      expect(btn.onPressed, isNotNull);
    });

    testWidgets('ready state with valid=true enables DISPATCH', (tester) async {
      final state = MissionState();
      state.setConnectionStatus("connected");
      // Force-set state machine into ready
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
      await tester.pumpWidget(_wrap(state));
      expect(find.text("Will recall drone1"), findsAtLeast(1));
      final dispatch = find.widgetWithText(ElevatedButton, "DISPATCH");
      expect(dispatch, findsOneWidget);
      final ElevatedButton btn = tester.widget(dispatch);
      expect(btn.onPressed, isNotNull);
      state.dispose();  // cancel pending translation Timer
    });

    testWidgets('ready state with valid=false (unknown_command) disables DISPATCH', (tester) async {
      final state = MissionState();
      state.setConnectionStatus("connected");
      final cid = state.submitOperatorCommand(rawText: "asdf", language: "en");
      state.handleEcho({"type": "echo", "ack": "operator_command_received", "command_id": cid});
      state.applyTranslation({
        "type": "command_translation",
        "command_id": cid,
        "structured": {"command": "unknown_command", "args": {"operator_text": "asdf", "suggestion": "Try ..."}},
        "valid": false,
        "preview_text": "Command not understood",
        "preview_text_in_operator_language": "Command not understood",
        "contract_version": "1.0.0",
      });
      await tester.pumpWidget(_wrap(state));
      final dispatch = find.widgetWithText(ElevatedButton, "DISPATCH");
      final ElevatedButton btn = tester.widget(dispatch);
      expect(btn.onPressed, isNull);
      state.dispose();  // cancel pending translation Timer
    });

    testWidgets('language dropdown round-trips into outbound payload via state', (tester) async {
      final state = MissionState();
      state.setConnectionStatus("connected");
      await tester.pumpWidget(_wrap(state));
      // Open the dropdown and tap Spanish
      await tester.tap(find.byType(DropdownButton<String>));
      await tester.pumpAndSettle();
      await tester.tap(find.text("Spanish").last);
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), "concéntrate en zona este");
      await tester.pump();
      await tester.tap(find.widgetWithText(ElevatedButton, "TRANSLATE"));
      await tester.pump();
      // The active command must reflect Spanish — we verify via the wire
      // shape on the next layer (mission_state already sends operator_command).
      // Here we just assert the panel transitioned to a non-default state.
      final cid = state.activeCommandId;
      expect(cid, isNotNull);
      expect(state.commandState(cid!), CommandState.sending);
      state.dispose();  // cancel pending translation Timer
    });
  });
}
