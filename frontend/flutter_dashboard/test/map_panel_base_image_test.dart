// Widget tests for the static-aerial overlay path of MapPanel
// (LOCKED DESIGN DECISIONS D1, D2, D3 from
// docs/plans/2026-05-08-thayyil-fixtures-swap.md Task 8).
//
// What's covered here:
//   D1 — bbox locks to base_image_extents, Refit hidden, off-extents
//        drones render as edge chevrons (not clipped markers)
//   D2 — grid paints synchronously; aerial image fades in over 150ms;
//        missing asset → toast + grid stays
//   D3 — drone-id labels render in white pills (not painter text);
//        touch targets are ≥44px
//
// Asset path under test: `assets/base_images/disaster_zone_v1_base.jpg`
// is bundled by the Flutter test runner because pubspec.yaml declares
// it. The byte equality with `sim/fixtures/base_images/` is verified
// separately by `scripts/tests/test_flutter_asset_sync.py`.
import 'package:flutter/material.dart';
import 'package:flutter_dashboard/state/mission_state.dart';
import 'package:flutter_dashboard/widgets/map_panel.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

const _validPath = "assets/base_images/disaster_zone_v1_base.jpg";

const _validExtents = {
  "lat_min": 33.9990,
  "lat_max": 34.0010,
  "lon_min": -118.5010,
  "lon_max": -118.4990,
};

Widget _wrap(MissionState s, {Size size = const Size(600, 600)}) => MaterialApp(
      home: ChangeNotifierProvider<MissionState>.value(
        value: s,
        child: Scaffold(
          body: SizedBox(width: size.width, height: size.height, child: const MapPanel()),
        ),
      ),
    );

Map<String, dynamic> _drone(String id, double lat, double lon) => {
      "drone_id": id,
      "agent_status": "active",
      "battery_pct": 87,
      "current_task": "survey_zone_a",
      "findings_count": 0,
      "validation_failures_total": 0,
      "position": {"lat": lat, "lon": lon, "alt": 50.0},
    };

Map<String, dynamic> _baseStateUpdate({
  String? path,
  Map<String, dynamic>? extents,
  List<Map<String, dynamic>>? drones,
}) {
  final egs = <String, dynamic>{};
  if (path != null) egs["base_image_path"] = path;
  if (extents != null) egs["base_image_extents"] = extents;
  return {
    "type": "state_update",
    "timestamp": "2026-05-08T12:00:00.000Z",
    "contract_version": "1.0.0",
    "egs_state": egs,
    "active_findings": const [],
    "active_drones": drones ?? [_drone("drone1", 34.0000, -118.5000)],
  };
}

void main() {
  group('D1 — bbox locks to base_image_extents', () {
    testWidgets('Refit button is hidden when overlay is present', (tester) async {
      final s = MissionState();
      s.applyStateUpdate(_baseStateUpdate(
        path: _validPath,
        extents: Map<String, dynamic>.from(_validExtents),
      ));
      await tester.pumpWidget(_wrap(s));
      await tester.pump();
      expect(find.byTooltip('Refit'), findsNothing);
    });

    testWidgets('Refit button is visible without overlay (data-driven path)',
        (tester) async {
      final s = MissionState();
      s.applyStateUpdate(_baseStateUpdate());
      await tester.pumpWidget(_wrap(s));
      await tester.pump();
      expect(find.byTooltip('Refit'), findsOneWidget);
    });

    testWidgets('Drone outside extents renders as off-extents chevron',
        (tester) async {
      final s = MissionState();
      // drone1 inside the extents, drone2 well to the east outside.
      s.applyStateUpdate(_baseStateUpdate(
        path: _validPath,
        extents: Map<String, dynamic>.from(_validExtents),
        drones: [
          _drone("drone1", 34.0000, -118.5000),
          _drone("drone2", 34.0000, -118.4900), // 100m+ east of lon_max
        ],
      ));
      await tester.pumpWidget(_wrap(s));
      await tester.pump();

      // drone1 keeps its normal hit-box marker; drone2 is the chevron.
      expect(find.byKey(const ValueKey('map-drone-drone1')), findsOneWidget);
      expect(find.byKey(const ValueKey('map-drone-drone2')), findsNothing);
      expect(find.byKey(const ValueKey('map-drone-chevron-drone2')),
          findsOneWidget);
    });

    testWidgets('Tapping off-extents chevron surfaces "Nm <cardinal>" toast',
        (tester) async {
      final s = MissionState();
      s.applyStateUpdate(_baseStateUpdate(
        path: _validPath,
        extents: Map<String, dynamic>.from(_validExtents),
        drones: [_drone("drone7", 34.0000, -118.4800)], // ~1900m east
      ));
      await tester.pumpWidget(_wrap(s));
      await tester.pump();

      await tester.tap(find.byKey(const ValueKey('map-drone-chevron-drone7')));
      await tester.pump(); // SnackBar enqueue
      await tester.pump(const Duration(milliseconds: 100));

      // Toast text is "<id> is <Nm> <cardinal>". We don't pin the exact meter
      // count (haversine on a 0.01-deg span has small rounding), but we do
      // pin the structure: id + cardinal.
      expect(
        find.byWidgetPredicate((w) =>
            w is Text &&
            w.data is String &&
            w.data!.startsWith('drone7 is ') &&
            w.data!.endsWith(' east')),
        findsOneWidget,
      );
    });
  });

  group('D2 — image-load state machine', () {
    testWidgets('grid paints synchronously on first frame', (tester) async {
      final s = MissionState();
      s.applyStateUpdate(_baseStateUpdate(
        path: _validPath,
        extents: Map<String, dynamic>.from(_validExtents),
      ));
      await tester.pumpWidget(_wrap(s));
      await tester.pump(); // single frame, image not yet decoded

      // Grid layer is the first CustomPaint in the Stack.
      expect(find.byType(CustomPaint), findsWidgets);
      // AnimatedOpacity layer exists and starts at 0 before image decodes.
      final ao = tester.widget<AnimatedOpacity>(find.byType(AnimatedOpacity));
      // Allow either 0 (pre-decode) or 0.80 (already-loaded sync path
      // taken on test bundles where decode is instantaneous).
      expect(ao.opacity == 0.0 || ao.opacity == 0.80, isTrue,
          reason: 'first frame opacity was ${ao.opacity}');
    });

    testWidgets('image-overlay layer is absent when path is null',
        (tester) async {
      final s = MissionState();
      s.applyStateUpdate(_baseStateUpdate());
      await tester.pumpWidget(_wrap(s));
      await tester.pump();

      // Without baseImagePath, we don't render the AnimatedOpacity layer
      // at all — the grid serves as the only background.
      expect(find.byType(AnimatedOpacity), findsNothing);
      expect(find.byType(CustomPaint), findsWidgets);
    });

    testWidgets('missing asset fires errorBuilder + toast, grid still paints',
        (tester) async {
      final s = MissionState();
      s.applyStateUpdate(_baseStateUpdate(
        path: "assets/base_images/this_file_does_not_exist.jpg",
        extents: Map<String, dynamic>.from(_validExtents),
      ));
      await tester.pumpWidget(_wrap(s));
      // Pump enough frames for the addPostFrameCallback to schedule + the
      // SnackBar to enqueue.
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));

      expect(find.text("Aerial overlay unavailable"), findsOneWidget);
      // Grid layer (CustomPaint) is unaffected by the asset failure.
      expect(find.byType(CustomPaint), findsWidgets);
    });
  });

  group('D3 — marker contrast + a11y', () {
    testWidgets('drone-id label renders inside white pill, not raw text',
        (tester) async {
      final s = MissionState();
      s.applyStateUpdate(_baseStateUpdate(
        path: _validPath,
        extents: Map<String, dynamic>.from(_validExtents),
        drones: [_drone("drone1", 34.0000, -118.5000)],
      ));
      await tester.pumpWidget(_wrap(s));
      await tester.pump();

      final labelFinder = find.byKey(const ValueKey('map-drone-label-drone1'));
      expect(labelFinder, findsOneWidget);

      // Walk down: Positioned → IgnorePointer → Container (the pill).
      final container = tester.widget<Container>(find.descendant(
        of: labelFinder,
        matching: find.byType(Container),
      ));
      final decoration = container.decoration as BoxDecoration;
      expect(decoration.color, Colors.white);
      expect(decoration.borderRadius, BorderRadius.circular(8));
      // The pill must contain the drone-id text.
      final text = tester.widget<Text>(find.descendant(
        of: labelFinder,
        matching: find.byType(Text),
      ));
      expect(text.data, "drone1");
      expect(text.style?.color, Colors.black);
      expect(text.style?.fontWeight, FontWeight.w600);
    });

    testWidgets('drone hit target is at least 44px (iOS a11y minimum)',
        (tester) async {
      final s = MissionState();
      s.applyStateUpdate(_baseStateUpdate(
        path: _validPath,
        extents: Map<String, dynamic>.from(_validExtents),
        drones: [_drone("drone1", 34.0000, -118.5000)],
      ));
      await tester.pumpWidget(_wrap(s));
      await tester.pump();

      final hitBox = tester.getRect(
        find.byKey(const ValueKey('map-drone-drone1')),
      );
      expect(hitBox.width, greaterThanOrEqualTo(44.0));
      expect(hitBox.height, greaterThanOrEqualTo(44.0));
    });
  });

  group('Fallback path', () {
    testWidgets('no overlay → no AnimatedOpacity, grid is the background',
        (tester) async {
      final s = MissionState();
      s.applyStateUpdate(_baseStateUpdate());
      await tester.pumpWidget(_wrap(s));
      await tester.pump();
      expect(find.byType(AnimatedOpacity), findsNothing);
      expect(find.byType(CustomPaint), findsWidgets);
    });

    testWidgets('extents present but path null → no overlay (D2 fallback)',
        (tester) async {
      // MissionState.baseImagePath returns null for null/empty strings, so
      // hasOverlay is false — the AnimatedOpacity layer is omitted entirely.
      final s = MissionState();
      s.applyStateUpdate(_baseStateUpdate(
        extents: Map<String, dynamic>.from(_validExtents),
      ));
      await tester.pumpWidget(_wrap(s));
      await tester.pump();
      expect(find.byType(AnimatedOpacity), findsNothing);
    });
  });
}
