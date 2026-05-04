import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../state/mission_state.dart';

const _palette = <Color>[
  Color(0xFF3F51B5), // indigo
  Color(0xFFFF9800), // orange
  Color(0xFF009688), // teal
  Color(0xFFE91E63), // pink/magenta
  Color(0xFFCDDC39), // lime
  Color(0xFFFFC107), // amber
];

/// Test helper exposed for unit tests; deterministic palette for the
/// alphabetically-sorted drone_id list.
Map<String, Color> palettePreview(List<String> droneIds) {
  final sorted = List<String>.from(droneIds)..sort();
  return {for (var i = 0; i < sorted.length; i++) sorted[i]: _palette[i % _palette.length]};
}

class MapPanel extends StatefulWidget {
  const MapPanel({super.key});

  @override
  State<MapPanel> createState() => _MapPanelState();
}

class _MapPanelState extends State<MapPanel> {
  _Bbox? _bbox;

  @override
  Widget build(BuildContext context) {
    return Consumer<MissionState>(
      builder: (_, mission, _) {
        final drones = mission.activeDrones.whereType<Map<String, dynamic>>().toList();
        final findings = mission.activeFindings.whereType<Map<String, dynamic>>().toList();
        final hasData = drones.isNotEmpty || findings.isNotEmpty;

        if (!hasData) {
          return const Center(child: Text("Waiting for state…"));
        }

        // Lock bbox on first non-empty frame.
        _bbox ??= _computeBbox(drones, findings);

        // Self-heal if the locked bbox no longer covers any current point.
        // Defends against the (0,0) "no-GPS-yet" sentinel: if the first
        // frame contained only sentinel coords and now real coords arrive
        // outside the original ±1° box, we recompute instead of silently
        // showing an empty map.
        if (!_bboxStillCovers(_bbox!, drones, findings)) {
          _bbox = _computeBbox(drones, findings);
        }
        final bbox = _bbox!;
        final colors = palettePreview([
          for (final d in drones) (d["drone_id"] as String?) ?? "?",
        ]);

        return LayoutBuilder(builder: (context, constraints) {
          final size = Size(constraints.maxWidth, constraints.maxHeight);
          return Stack(
            children: [
              CustomPaint(
                size: Size.infinite,
                painter: _ProjectionPainter(
                  drones: drones,
                  findings: findings,
                  bbox: bbox,
                  colors: colors,
                ),
              ),
              // Eng-review issue 2A: paint order is findings UNDER
              // drones (see _ProjectionPainter.paint). Tap order must
              // match: findings FIRST in the Stack so drones sit on
              // top of finding hit-boxes when co-located.
              ..._buildFindingMarkers(findings, bbox, size, mission),
              ..._buildDroneMarkers(drones, bbox, size, mission),
              Positioned(
                top: 4, right: 4,
                child: IconButton(
                  tooltip: "Refit",
                  icon: const Icon(Icons.center_focus_strong),
                  onPressed: () => setState(() => _bbox = null),
                ),
              ),
            ],
          );
        });
      },
    );
  }

  static const double _droneHitRadius = 18;
  static const double _findingHitRadius = 14;

  List<Widget> _buildDroneMarkers(
    List<Map<String, dynamic>> drones,
    _Bbox bbox,
    Size size,
    MissionState mission,
  ) {
    final out = <Widget>[];
    for (final d in drones) {
      final id = (d["drone_id"] as String?) ?? "?";
      final pos = d["position"] as Map<String, dynamic>?;
      final p = _project(pos?["lat"] as num?, pos?["lon"] as num?, bbox, size);
      if (p == null) continue;
      out.add(
        Positioned(
          key: ValueKey("map-drone-$id"),
          left: p.dx - _droneHitRadius,
          top: p.dy - _droneHitRadius,
          width: _droneHitRadius * 2,
          height: _droneHitRadius * 2,
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: () => mission.selectDrone(id),
            child: const SizedBox.expand(),
          ),
        ),
      );
    }
    return out;
  }

  List<Widget> _buildFindingMarkers(
    List<Map<String, dynamic>> findings,
    _Bbox bbox,
    Size size,
    MissionState mission,
  ) {
    final out = <Widget>[];
    for (final f in findings) {
      final id = f["finding_id"] as String?;
      if (id == null) continue;
      final loc = f["location"] as Map<String, dynamic>?;
      final p = _project(loc?["lat"] as num?, loc?["lon"] as num?, bbox, size);
      if (p == null) continue;
      out.add(Positioned(
        key: ValueKey("map-finding-$id"),
        left: p.dx - _findingHitRadius,
        top: p.dy - _findingHitRadius,
        width: _findingHitRadius * 2,
        height: _findingHitRadius * 2,
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: () => mission.selectFinding(id),
          child: const SizedBox.expand(),
        ),
      ));
    }
    return out;
  }
}

/// Top-level projection used by both the painter and the widget hit-boxes.
/// Single source of truth: if you change one, change the painter together.
Offset? _project(num? la, num? lo, _Bbox bbox, Size size) {
  if (la == null || lo == null) return null;
  final lat = la.toDouble();
  final lon = lo.toDouble();
  if (!lat.isFinite || !lon.isFinite) return null;
  final cosLat = math.max(
    math.cos(bbox.midLat * math.pi / 180.0).abs(),
    0.01,
  );
  final lonScale = size.width / (bbox.lonSpan * cosLat);
  final latScale = size.height / bbox.latSpan;
  final x = (lon - bbox.minLon) * cosLat * lonScale;
  final y = size.height - (lat - bbox.minLat) * latScale;
  return Offset(x, y);
}

class _Bbox {
  final double minLat;
  final double maxLat;
  final double minLon;
  final double maxLon;
  const _Bbox(this.minLat, this.maxLat, this.minLon, this.maxLon);

  double get midLat => (minLat + maxLat) / 2.0;
  double get latSpan => math.max((maxLat - minLat).abs(), 1e-6);
  double get lonSpan => math.max((maxLon - minLon).abs(), 1e-6);

  bool covers(double lat, double lon) =>
      lat >= minLat && lat <= maxLat && lon >= minLon && lon <= maxLon;
}

/// Returns false if any drone or finding has finite coords outside [bbox].
/// Used to auto-refit when the locked bbox doesn't represent current state
/// (e.g., the first frame had only (0,0) sentinels).
bool _bboxStillCovers(
  _Bbox bbox,
  List<Map<String, dynamic>> drones,
  List<Map<String, dynamic>> findings,
) {
  bool checkPoint(num? la, num? lo) {
    if (la == null || lo == null) return true;
    final lat = la.toDouble();
    final lon = lo.toDouble();
    if (!lat.isFinite || !lon.isFinite) return true;
    return bbox.covers(lat, lon);
  }
  for (final d in drones) {
    final p = d["position"] as Map<String, dynamic>?;
    if (!checkPoint(p?["lat"] as num?, p?["lon"] as num?)) return false;
  }
  for (final f in findings) {
    final p = f["location"] as Map<String, dynamic>?;
    if (!checkPoint(p?["lat"] as num?, p?["lon"] as num?)) return false;
  }
  return true;
}

_Bbox _computeBbox(
  List<Map<String, dynamic>> drones,
  List<Map<String, dynamic>> findings,
) {
  final lats = <double>[];
  final lons = <double>[];
  void add(num? la, num? lo) {
    if (la == null || lo == null) return;
    final d = la.toDouble();
    final e = lo.toDouble();
    if (!d.isFinite || !e.isFinite) return;
    lats.add(d);
    lons.add(e);
  }
  for (final d in drones) {
    final p = d["position"] as Map<String, dynamic>?;
    add(p?["lat"] as num?, p?["lon"] as num?);
  }
  for (final f in findings) {
    final p = f["location"] as Map<String, dynamic>?;
    add(p?["lat"] as num?, p?["lon"] as num?);
  }
  if (lats.isEmpty) {
    return const _Bbox(-1, 1, -1, 1);
  }
  final padLat = (lats.reduce(math.max) - lats.reduce(math.min)).abs() * 0.2 + 1e-4;
  final padLon = (lons.reduce(math.max) - lons.reduce(math.min)).abs() * 0.2 + 1e-4;
  return _Bbox(
    lats.reduce(math.min) - padLat,
    lats.reduce(math.max) + padLat,
    lons.reduce(math.min) - padLon,
    lons.reduce(math.max) + padLon,
  );
}

class _ProjectionPainter extends CustomPainter {
  final List<Map<String, dynamic>> drones;
  final List<Map<String, dynamic>> findings;
  final _Bbox bbox;
  final Map<String, Color> colors;

  _ProjectionPainter({
    required this.drones,
    required this.findings,
    required this.bbox,
    required this.colors,
  });

  @override
  void paint(Canvas canvas, Size size) {
    // Background grid.
    final bg = Paint()..color = const Color(0xFFF5F5F5);
    canvas.drawRect(Offset.zero & size, bg);
    final grid = Paint()
      ..color = Colors.grey.withValues(alpha: 0.10)
      ..strokeWidth = 1;
    for (var x = 0.0; x < size.width; x += 50) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), grid);
    }
    for (var y = 0.0; y < size.height; y += 50) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), grid);
    }

    // Delegate to top-level _project — single source of truth for the
    // projection math shared with the widget hit-box layer.
    Offset? project(num? la, num? lo) => _project(la, lo, bbox, size);

    // Findings under drones.
    for (final f in findings) {
      final loc = f["location"] as Map<String, dynamic>?;
      final p = project(loc?["lat"] as num?, loc?["lon"] as num?);
      if (p == null) continue;
      final color = _findingColor((f["type"] as String?) ?? "");
      final rect = Paint()..color = color;
      canvas.drawCircle(p, 6, rect);
    }

    // Drones on top.
    final paintLabel = TextPainter(textDirection: TextDirection.ltr);
    for (final d in drones) {
      final id = (d["drone_id"] as String?) ?? "?";
      final pos = d["position"] as Map<String, dynamic>?;
      final p = project(pos?["lat"] as num?, pos?["lon"] as num?);
      if (p == null) continue;
      final color = colors[id] ?? Colors.indigo;
      canvas.drawCircle(p, 9, Paint()..color = Colors.white);
      canvas.drawCircle(p, 8, Paint()..color = color);
      paintLabel
        ..text = TextSpan(text: id, style: const TextStyle(fontSize: 10, color: Colors.black))
        ..layout(maxWidth: 80);
      paintLabel.paint(canvas, p + const Offset(10, -6));
    }
  }

  Color _findingColor(String type) {
    switch (type) {
      case "victim": return Colors.red.shade700;
      case "fire": return Colors.deepOrange.shade700;
      case "smoke": return Colors.orange.shade400;
      case "damaged_structure": return Colors.grey.shade700;
      case "blocked_route": return Colors.blue.shade700;
      default: return Colors.purple.shade700;
    }
  }

  @override
  bool shouldRepaint(covariant _ProjectionPainter old) {
    return drones != old.drones || findings != old.findings || bbox != old.bbox;
  }
}
