import 'package:flutter/material.dart';
import 'package:flutter_dashboard/widgets/command_panel.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('DISPATCH button is disabled', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: Scaffold(body: CommandPanel())));
    final button = find.widgetWithText(ElevatedButton, "DISPATCH");
    expect(button, findsOneWidget);
    expect(tester.widget<ElevatedButton>(button).onPressed, isNull);
    expect(find.byType(Tooltip), findsWidgets);
  });
}
