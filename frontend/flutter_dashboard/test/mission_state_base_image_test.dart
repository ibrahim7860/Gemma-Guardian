// Tests for MissionState.baseImagePath / baseImageExtents — the Contract 3
// fields that drive the map_panel static-aerial overlay (LOCKED DESIGN
// DECISIONS D1, D2 of docs/plans/2026-05-08-thayyil-fixtures-swap.md).
import 'package:flutter_dashboard/state/mission_state.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> _wrap({Map<String, dynamic>? egs}) => {
      "type": "state_update",
      "egs_state": egs ?? <String, dynamic>{},
      "active_drones": const [],
      "active_findings": const [],
    };

void main() {
  group('MissionState base_image fields', () {
    test('exposes baseImagePath + baseImageExtents from egs.state', () {
      final s = MissionState();
      s.applyStateUpdate(_wrap(egs: {
        "base_image_path": "sim/fixtures/base_images/disaster_zone_v1_base.jpg",
        "base_image_extents": {
          "lat_min": 33.9990,
          "lat_max": 34.0010,
          "lon_min": -118.5010,
          "lon_max": -118.4990,
        },
      }));

      expect(s.baseImagePath, "sim/fixtures/base_images/disaster_zone_v1_base.jpg");
      expect(s.baseImageExtents, isNotNull);
      expect(s.baseImageExtents!.latMin, 33.9990);
      expect(s.baseImageExtents!.lonMax, -118.4990);
    });

    test('returns null for both when egs.state lacks the fields', () {
      final s = MissionState();
      s.applyStateUpdate(_wrap(egs: {"mission_id": "single_drone_smoke"}));

      expect(s.baseImagePath, isNull);
      expect(s.baseImageExtents, isNull);
    });

    test('treats null/empty path as absent (D2 fallback path)', () {
      // Wire-permissive: Contract 3 allows null; dashboard treats it the
      // same as omitted so the map panel never shows half-state UI.
      final s = MissionState();
      s.applyStateUpdate(_wrap(egs: {
        "base_image_path": null,
        "base_image_extents": null,
      }));
      expect(s.baseImagePath, isNull);
      expect(s.baseImageExtents, isNull);

      s.applyStateUpdate(_wrap(egs: {"base_image_path": ""}));
      expect(s.baseImagePath, isNull);
    });

    test('rejects malformed bbox (lat_max <= lat_min) → null extents', () {
      // Defense in depth: if the upstream scenario validator was bypassed
      // somehow, the dashboard treats a degenerate bbox as "no overlay" —
      // safer than crashing the map_panel projection math.
      final s = MissionState();
      s.applyStateUpdate(_wrap(egs: {
        "base_image_path": "x.jpg",
        "base_image_extents": {
          "lat_min": 34.0010, "lat_max": 33.9990,
          "lon_min": -118.5010, "lon_max": -118.4990,
        },
      }));
      expect(s.baseImageExtents, isNull);
    });

    test('rejects bbox with missing key → null extents', () {
      final s = MissionState();
      s.applyStateUpdate(_wrap(egs: {
        "base_image_path": "x.jpg",
        "base_image_extents": {
          "lat_min": 33.9990, "lat_max": 34.0010,
          // lon_min / lon_max missing
        },
      }));
      expect(s.baseImageExtents, isNull);
    });

    test('rejects bbox with NaN/infinite values → null extents', () {
      final s = MissionState();
      s.applyStateUpdate(_wrap(egs: {
        "base_image_path": "x.jpg",
        "base_image_extents": {
          "lat_min": 33.9990,
          "lat_max": double.nan,
          "lon_min": -118.5010,
          "lon_max": -118.4990,
        },
      }));
      expect(s.baseImageExtents, isNull);
    });

    test('parses int-typed JSON numbers (jsonDecode coerces some to int)', () {
      // jsonDecode produces `int` for whole numbers; tryParse must accept
      // either int or double via the num? cast.
      final s = MissionState();
      s.applyStateUpdate(_wrap(egs: {
        "base_image_path": "x.jpg",
        "base_image_extents": {
          "lat_min": 0, "lat_max": 1, "lon_min": 0, "lon_max": 1,
        },
      }));
      expect(s.baseImageExtents, isNotNull);
      expect(s.baseImageExtents!.latMin, 0.0);
      expect(s.baseImageExtents!.lonMax, 1.0);
    });

    test('updates when egs.state changes mid-mission', () {
      final s = MissionState();
      s.applyStateUpdate(_wrap(egs: {"base_image_path": "old.jpg",
        "base_image_extents": {
          "lat_min": 0, "lat_max": 1, "lon_min": 0, "lon_max": 1,
        }}));
      expect(s.baseImagePath, "old.jpg");

      s.applyStateUpdate(_wrap(egs: {"base_image_path": "new.jpg",
        "base_image_extents": {
          "lat_min": 10, "lat_max": 11, "lon_min": 10, "lon_max": 11,
        }}));
      expect(s.baseImagePath, "new.jpg");
      expect(s.baseImageExtents!.latMin, 10.0);
    });

    test('BaseImageExtents equality + hashCode (for map-panel rebuild gates)', () {
      const a = BaseImageExtents(latMin: 0, latMax: 1, lonMin: 0, lonMax: 1);
      const b = BaseImageExtents(latMin: 0, latMax: 1, lonMin: 0, lonMax: 1);
      const c = BaseImageExtents(latMin: 0, latMax: 2, lonMin: 0, lonMax: 1);
      expect(a, equals(b));
      expect(a.hashCode, b.hashCode);
      expect(a, isNot(equals(c)));
    });
  });
}
