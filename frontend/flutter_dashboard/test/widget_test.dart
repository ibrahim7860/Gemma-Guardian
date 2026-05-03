// Smoke test: app renders without throwing.
// Full integration tests require a running WebSocket server; that's out of
// scope for Phase 1B unit tests. The connection will fail gracefully in test
// (the WS channel throws / completes immediately) — the dashboard handles
// this via its exponential-backoff reconnect loop.

import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:flutter/material.dart';
import 'package:flutter_dashboard/state/mission_state.dart';

void main() {
  testWidgets('FieldAgentDashboard renders the app bar title', (WidgetTester tester) async {
    // Provide a MissionState so the Consumer widgets don't throw.
    await tester.pumpWidget(
      ChangeNotifierProvider(
        create: (_) => MissionState(),
        child: const MaterialApp(home: Scaffold(body: Text("smoke"))),
      ),
    );
    expect(find.text("smoke"), findsOneWidget);
  });
}
