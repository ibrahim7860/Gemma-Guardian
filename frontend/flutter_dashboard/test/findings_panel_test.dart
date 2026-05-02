import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_dashboard/state/mission_state.dart';
import 'package:flutter_dashboard/widgets/findings_panel.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

class _RecordingSink implements WebSocketSink {
  final List<dynamic> received = [];
  @override void add(dynamic data) => received.add(data);
  @override Future addStream(Stream stream) async {}
  @override Future close([int? c, String? r]) async {}
  @override void addError(Object e, [StackTrace? s]) {}
  @override Future get done => Future.value();
}

Widget _wrap(MissionState state) => MaterialApp(
      home: ChangeNotifierProvider<MissionState>.value(
        value: state,
        child: const Scaffold(body: FindingsPanel()),
      ),
    );

Map<String, dynamic> _finding(String id, {bool approved = false}) => {
      "finding_id": id,
      "type": "victim",
      "severity": 4,
      "confidence": 0.78,
      "source_drone_id": "drone1",
      "timestamp": "2026-05-02T12:00:00.000Z",
      "visual_description": "Person prone, partially covered by debris.",
      "approved": approved,
    };

void main() {
  testWidgets('empty findings show "no findings yet"', (tester) async {
    final s = MissionState();
    await tester.pumpWidget(_wrap(s));
    expect(find.textContaining("no findings"), findsOneWidget);
  });

  testWidgets('APPROVE tap calls markFinding with "approve"', (tester) async {
    final s = MissionState();
    final sink = _RecordingSink();
    s.attachSink(sink);
    s.setConnectionStatus("connected");
    s.applyStateUpdate({
      "type": "state_update",
      "timestamp": "2026-05-02T12:00:00.000Z",
      "contract_version": "1.0.0",
      "active_findings": [_finding("f_drone1_42")],
      "active_drones": [],
    });
    await tester.pumpWidget(_wrap(s));
    await tester.tap(find.text("APPROVE"));
    await tester.pump();
    expect(s.findingState("f_drone1_42"), ApprovalState.pending);
  });

  testWidgets('button disabled while pending and re-enabled on failed', (tester) async {
    final s = MissionState();
    final sink = _RecordingSink();
    s.attachSink(sink);
    s.setConnectionStatus("connected");
    s.applyStateUpdate({
      "type": "state_update",
      "timestamp": "2026-05-02T12:00:00.000Z",
      "contract_version": "1.0.0",
      "active_findings": [_finding("f_drone1_42")],
      "active_drones": [],
    });
    await tester.pumpWidget(_wrap(s));
    s.markFinding("f_drone1_42", "approve");
    await tester.pump();
    final approveButton = find.widgetWithText(ElevatedButton, "APPROVE");
    expect(tester.widget<ElevatedButton>(approveButton).onPressed, isNull);
    s.handleEcho({
      "type": "echo",
      "error": "redis_publish_failed",
      "finding_id": "f_drone1_42",
    });
    await tester.pump();
    expect(tester.widget<ElevatedButton>(approveButton).onPressed, isNotNull);
  });

  testWidgets('confirmed finding shows green check', (tester) async {
    final s = MissionState();
    final sink = _RecordingSink();
    s.attachSink(sink);
    s.setConnectionStatus("connected");
    s.applyStateUpdate({
      "type": "state_update",
      "timestamp": "2026-05-02T12:00:00.000Z",
      "contract_version": "1.0.0",
      "active_findings": [_finding("f_drone1_42")],
      "active_drones": [],
    });
    s.markFinding("f_drone1_42", "approve");
    s.handleEcho({
      "type": "echo",
      "ack": "finding_approval",
      "finding_id": "f_drone1_42",
    });
    s.applyStateUpdate({
      "type": "state_update",
      "timestamp": "2026-05-02T12:01:00.000Z",
      "contract_version": "1.0.0",
      "active_findings": [_finding("f_drone1_42", approved: true)],
      "active_drones": [],
    });
    await tester.pumpWidget(_wrap(s));
    expect(find.byKey(const ValueKey("approval-icon-confirmed-f_drone1_42")), findsOneWidget);
  });

  testWidgets('dismissed row has strikethrough', (tester) async {
    final s = MissionState();
    final sink = _RecordingSink();
    s.attachSink(sink);
    s.setConnectionStatus("connected");
    s.applyStateUpdate({
      "type": "state_update",
      "timestamp": "2026-05-02T12:00:00.000Z",
      "contract_version": "1.0.0",
      "active_findings": [_finding("f_drone1_42")],
      "active_drones": [],
    });
    s.markFinding("f_drone1_42", "dismiss");
    final emitted = jsonDecode(sink.received.single as String) as Map<String, dynamic>;
    s.handleEcho({
      "type": "echo",
      "ack": "finding_approval",
      "command_id": emitted["command_id"],
      "finding_id": "f_drone1_42",
    });
    await tester.pumpWidget(_wrap(s));
    expect(find.byKey(const ValueKey("approval-icon-dismissed-f_drone1_42")), findsOneWidget);
  });

  testWidgets('archived finding still visible after upstream removal', (tester) async {
    final s = MissionState();
    final sink = _RecordingSink();
    s.attachSink(sink);
    s.setConnectionStatus("connected");
    s.applyStateUpdate({
      "type": "state_update",
      "timestamp": "2026-05-02T12:00:00.000Z",
      "contract_version": "1.0.0",
      "active_findings": [_finding("f_drone1_42")],
      "active_drones": [],
    });
    s.markFinding("f_drone1_42", "approve");
    s.handleEcho({
      "type": "echo",
      "ack": "finding_approval",
      "finding_id": "f_drone1_42",
    });
    s.applyStateUpdate({
      "type": "state_update",
      "timestamp": "2026-05-02T12:01:00.000Z",
      "contract_version": "1.0.0",
      "active_findings": [],
      "active_drones": [],
    });
    await tester.pumpWidget(_wrap(s));
    expect(find.textContaining("(archived)"), findsOneWidget);
  });
}
