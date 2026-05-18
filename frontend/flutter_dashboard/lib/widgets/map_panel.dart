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
  return {
    for (var i = 0; i < sorted.length; i++)
      sorted[i]: _palette[i % _palette.length],
  };
}

/// Toast duration for the missing-asset and chevron-tap SnackBars. Locked
/// at 4s per LOCKED DESIGN DECISION D2 ("4-second auto-dismissed toast").
const _toastDuration = Duration(seconds: 4);

/// Image fade-in duration when the static aerial decodes (D2).
const _imageFadeDuration = Duration(milliseconds: 150);

/// Aerial overlay opacity when fully loaded. Tuned for marker contrast on
/// photographic backgrounds (D3) — 0.80 lets the underlying grid show
/// through enough that satellite-blue rooftops don't steal attention from
/// the colored drone markers.
const _imageOpacityLoaded = 0.80;

class MapPanel extends StatefulWidget {
  const MapPanel({super.key});

  @override
  State<MapPanel> createState() => _MapPanelState();
}

class _MapPanelState extends State<MapPanel> {
  _Bbox? _bbox;
  bool _imageLoaded = false;
  String? _imageLoadedFor; // path the loaded flag corresponds to
  bool _toastScheduled = false;

  @override
  Widget build(BuildContext context) {
    return Consumer<MissionState>(
      builder: (_, mission, _) {
        final drones = mission.activeDrones
            .whereType<Map<String, dynamic>>()
            .toList();
        final findings = mission.activeFindings
            .whereType<Map<String, dynamic>>()
            .toList();

        // Reset image-loaded latch if the path changed (mission switch /
        // EGS replan). Without this, a swap to a missing asset would never
        // re-fire the errorBuilder.
        final path = mission.baseImagePath;
        if (_imageLoadedFor != path) {
          _imageLoaded = false;
          _imageLoadedFor = path;
          _toastScheduled = false;
        }

        // D1: lock bbox to base_image_extents when present.
        final baseExtents = mission.baseImageExtents;
        final hasOverlay = path != null && baseExtents != null;
        if (hasOverlay) {
          _bbox = _bboxFromExtents(baseExtents);
        } else {
          // Pre-existing data-driven path: lock on first non-empty frame,
          // self-heal if the locked bbox no longer covers any current point.
          final hasData = drones.isNotEmpty || findings.isNotEmpty;
          if (!hasData) {
            return const Center(child: Text("Waiting for state…"));
          }
          _bbox ??= _computeBbox(drones, findings);
          if (!_bboxStillCovers(_bbox!, drones, findings)) {
            _bbox = _computeBbox(drones, findings);
          }
        }
        final bbox = _bbox!;
        final colors = palettePreview([
          for (final d in drones) (d["drone_id"] as String?) ?? "?",
        ]);
        // Tier-2: per-drone breadcrumb trails. Pre-snapshot from
        // MissionState so the painter doesn't reach back into the
        // Provider (CustomPainter shouldn't depend on InheritedWidgets).
        final trails = <String, List<List<double>>>{
          for (final d in drones)
            ((d["drone_id"] as String?) ?? "?"):
                mission.droneTrail((d["drone_id"] as String?) ?? "?"),
        };

        return LayoutBuilder(
          builder: (context, constraints) {
            final size = Size(constraints.maxWidth, constraints.maxHeight);
            // Layer order (bottom → top):
            //   1. _GridBackgroundPainter — synchronous, always paints
            //   2. AnimatedOpacity(Image.asset) — fades in at 0.80 over 150ms
            //   3. _ProjectionPainter — markers only (drones, finding dots)
            //   4. Finding GestureDetectors (tap targets, beneath drones)
            //   5. Drone GestureDetectors + label pills
            //   6. Off-extents drone chevrons (only when overlay locked)
            //   7. Refit IconButton (hidden when overlay locked, D1)
            return Stack(
              children: [
                CustomPaint(
                  size: Size.infinite,
                  painter: _GridBackgroundPainter(),
                ),
                if (hasOverlay)
                  Positioned.fill(
                    child: AnimatedOpacity(
                      opacity: _imageLoaded ? _imageOpacityLoaded : 0.0,
                      duration: _imageFadeDuration,
                      child: Image.asset(
                        _resolveAssetPath(path),
                        fit: BoxFit.fill,
                        gaplessPlayback: true,
                        errorBuilder: (ctx, _, _) {
                          _scheduleToast(
                            ctx,
                            "Aerial overlay unavailable",
                            key: "asset_error_$path",
                          );
                          return const SizedBox.shrink();
                        },
                        frameBuilder:
                            (_, child, frame, wasSynchronouslyLoaded) {
                              if (frame != null && !_imageLoaded) {
                                WidgetsBinding.instance.addPostFrameCallback((
                                  _,
                                ) {
                                  if (mounted && !_imageLoaded) {
                                    setState(() => _imageLoaded = true);
                                  }
                                });
                              }
                              return child;
                            },
                      ),
                    ),
                  ),
                CustomPaint(
                  size: Size.infinite,
                  painter: _ProjectionPainter(
                    drones: drones,
                    findings: findings,
                    bbox: bbox,
                    colors: colors,
                    trails: trails,
                  ),
                ),
                // Tap order: findings UNDER drones, so drones win when
                // co-located (matches paint order in _ProjectionPainter).
                ..._buildFindingMarkers(findings, bbox, size, mission),
                ..._buildDroneMarkers(
                  drones: drones,
                  bbox: bbox,
                  size: size,
                  mission: mission,
                  colors: colors,
                  hasOverlay: hasOverlay,
                ),
                if (!hasOverlay)
                  Positioned(
                    top: 4,
                    right: 4,
                    child: IconButton(
                      tooltip: "Refit",
                      icon: const Icon(Icons.center_focus_strong),
                      onPressed: () => setState(() => _bbox = null),
                    ),
                  ),
              ],
            );
          },
        );
      },
    );
  }

  // D3: touch targets bumped from 18/14 to 24/24 (48px hit area). The
  // 36px / 28px diameters of the prior values were below the iOS 44px
  // minimum and the WCAG 24x24 minimum — fixed here while we're in the
  // file (pre-existing a11y gap, called out in LOCKED DESIGN DECISION D3).
  static const double _droneHitRadius = 24;
  static const double _findingHitRadius = 24;

  /// 16px filled triangle for off-extents chevrons. Kept tight so a fully
  /// out-of-extent swarm doesn't crowd the canvas edges.
  static const double _chevronSize = 16;

  List<Widget> _buildDroneMarkers({
    required List<Map<String, dynamic>> drones,
    required _Bbox bbox,
    required Size size,
    required MissionState mission,
    required Map<String, Color> colors,
    required bool hasOverlay,
  }) {
    final out = <Widget>[];
    for (final d in drones) {
      final id = (d["drone_id"] as String?) ?? "?";
      final pos = d["position"] as Map<String, dynamic>?;
      final lat = (pos?["lat"] as num?)?.toDouble();
      final lon = (pos?["lon"] as num?)?.toDouble();
      final p = _project(lat, lon, bbox, size);
      if (p == null) continue;

      final inCanvas =
          p.dx >= 0 && p.dx <= size.width && p.dy >= 0 && p.dy <= size.height;

      // D1 follow-on: drones outside the locked extents render as edge
      // chevrons instead of clipped markers. Only triggers when the
      // overlay is locked — without an overlay, we'd just refit the bbox.
      if (hasOverlay && !inCanvas && lat != null && lon != null) {
        out.add(
          _buildOffExtentsChevron(
            id: id,
            droneLat: lat,
            droneLon: lon,
            bbox: bbox,
            size: size,
            color: colors[id] ?? Colors.indigo,
          ),
        );
        continue;
      }

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
      // D3: drone-id label as a real widget (white pill), not painter
      // text. Painter text doesn't antialias against a JPEG photographic
      // background and isn't a11y-discoverable. The pill sits to the
      // right of the marker's hit box, vertically centered.
      out.add(
        Positioned(
          key: ValueKey("map-drone-label-$id"),
          left: p.dx + 10,
          top: p.dy - 10,
          child: IgnorePointer(
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(8),
                boxShadow: const [
                  BoxShadow(
                    color: Colors.black26,
                    blurRadius: 2,
                    offset: Offset(0, 1),
                  ),
                ],
              ),
              child: Text(
                id,
                style: const TextStyle(
                  fontSize: 11,
                  color: Colors.black,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          ),
        ),
      );
    }
    return out;
  }

  Widget _buildOffExtentsChevron({
    required String id,
    required double droneLat,
    required double droneLon,
    required _Bbox bbox,
    required Size size,
    required Color color,
  }) {
    // Place the chevron at the canvas edge nearest the drone's projected
    // position, then rotate it to point toward the actual (off-canvas)
    // position. We use the *un-clamped* projection to drive the rotation
    // angle so the tip continues to track the drone.
    final unclamped = _project(droneLat, droneLon, bbox, size)!;
    final cx = unclamped.dx.clamp(_chevronSize, size.width - _chevronSize);
    final cy = unclamped.dy.clamp(_chevronSize, size.height - _chevronSize);
    final dx = unclamped.dx - cx;
    final dy = unclamped.dy - cy;
    final angle = math.atan2(dy, dx);
    final dist = _haversineMeters(
      _bboxNearestLat(droneLat, bbox),
      _bboxNearestLon(droneLon, bbox),
      droneLat,
      droneLon,
    );
    final cardinal = _cardinalFromBbox(droneLat, droneLon, bbox);
    final message = "$id is ${dist.round()}m $cardinal";

    return Positioned(
      key: ValueKey("map-drone-chevron-$id"),
      left: cx - _chevronSize,
      top: cy - _chevronSize,
      width: _chevronSize * 2,
      height: _chevronSize * 2,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: () {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(message), duration: _toastDuration),
          );
        },
        child: Transform.rotate(
          angle: angle,
          child: CustomPaint(painter: _ChevronPainter(color: color)),
        ),
      ),
    );
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
      out.add(
        Positioned(
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
        ),
      );
    }
    return out;
  }

  /// Schedule a SnackBar without re-firing during build. errorBuilder is
  /// called on every rebuild while the asset stays missing; without the
  /// `_toastScheduled` latch the user would see a stuck toast loop.
  void _scheduleToast(BuildContext ctx, String text, {required String key}) {
    if (_toastScheduled) return;
    _toastScheduled = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final messenger = ScaffoldMessenger.maybeOf(ctx);
      if (messenger == null) return;
      messenger.showSnackBar(
        SnackBar(content: Text(text), duration: _toastDuration),
      );
    });
  }
}

/// Top-level projection used by both the painter and the widget hit-boxes.
/// Single source of truth: if you change one, change the painter together.
Offset? _project(num? la, num? lo, _Bbox bbox, Size size) {
  if (la == null || lo == null) return null;
  final lat = la.toDouble();
  final lon = lo.toDouble();
  if (!lat.isFinite || !lon.isFinite) return null;
  final cosLat = math.max(math.cos(bbox.midLat * math.pi / 180.0).abs(), 0.01);
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

/// Adapter: BaseImageExtents (public) → _Bbox (private to map_panel).
_Bbox _bboxFromExtents(BaseImageExtents e) =>
    _Bbox(e.latMin, e.latMax, e.lonMin, e.lonMax);

/// Map a scenario-side path (`sim/fixtures/base_images/X.jpg`, the wire
/// format on `egs.state.base_image_path`) onto the Flutter asset bundle
/// path (`assets/base_images/X.jpg`, the path Image.asset expects).
///
/// Why the indirection exists: Flutter's asset bundler can't reach files
/// outside `frontend/flutter_dashboard/`, so the static aerial lives in
/// two places — `sim/fixtures/base_images/` (source of truth, where the
/// fetch script writes and the LICENSES.md lives) and the bundled copy
/// under `frontend/flutter_dashboard/assets/base_images/`. The two are
/// kept byte-identical by `scripts/sync_flutter_base_images.py` +
/// `scripts/tests/test_flutter_asset_sync.py`. The wire format stays
/// repo-rooted (so debug logs / scenario YAMLs are self-describing); the
/// dashboard maps to its bundle namespace at the rendering boundary.
///
/// Pass-through for paths that don't match the prefix — defensive against
/// scenarios that publish a Flutter-relative path directly (allows test
/// fixtures and future scenarios to opt out of the indirection cleanly).
@visibleForTesting
String resolveBaseImageAssetPath(String wirePath) =>
    _resolveAssetPath(wirePath);

const _simBaseImagesPrefix = "sim/fixtures/base_images/";
const _flutterBaseImagesPrefix = "assets/base_images/";

String _resolveAssetPath(String wirePath) {
  if (wirePath.startsWith(_simBaseImagesPrefix)) {
    return _flutterBaseImagesPrefix +
        wirePath.substring(_simBaseImagesPrefix.length);
  }
  return wirePath;
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
  final padLat =
      (lats.reduce(math.max) - lats.reduce(math.min)).abs() * 0.2 + 1e-4;
  final padLon =
      (lons.reduce(math.max) - lons.reduce(math.min)).abs() * 0.2 + 1e-4;
  return _Bbox(
    lats.reduce(math.min) - padLat,
    lats.reduce(math.max) + padLat,
    lons.reduce(math.min) - padLon,
    lons.reduce(math.max) + padLon,
  );
}

// Off-extents helpers (D1 follow-on). Behavior is tested through the
// chevron-tap SnackBar widget test (toast text round-trips the math).

/// Latitude on the bbox edge nearest [droneLat]. If the drone is N of the
/// bbox returns lat_max; S returns lat_min; otherwise the drone's own lat.
double _bboxNearestLat(double droneLat, _Bbox bbox) {
  if (droneLat > bbox.maxLat) return bbox.maxLat;
  if (droneLat < bbox.minLat) return bbox.minLat;
  return droneLat;
}

/// Longitude on the bbox edge nearest [droneLon].
double _bboxNearestLon(double droneLon, _Bbox bbox) {
  if (droneLon > bbox.maxLon) return bbox.maxLon;
  if (droneLon < bbox.minLon) return bbox.minLon;
  return droneLon;
}

/// Haversine great-circle distance in meters. Used only for the chevron
/// distance toast — accuracy is fine to the nearest meter at sub-km
/// distances, well within "drone1 is 247m east" precision.
double _haversineMeters(double lat1, double lon1, double lat2, double lon2) {
  const earthRadiusM = 6_371_000.0;
  double toRad(double deg) => deg * math.pi / 180.0;
  final dLat = toRad(lat2 - lat1);
  final dLon = toRad(lon2 - lon1);
  final a =
      math.sin(dLat / 2) * math.sin(dLat / 2) +
      math.cos(toRad(lat1)) *
          math.cos(toRad(lat2)) *
          math.sin(dLon / 2) *
          math.sin(dLon / 2);
  final c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a));
  return earthRadiusM * c;
}

/// Returns "north" / "south" / "east" / "west" — the dominant cardinal
/// of the drone relative to [bbox]. Diagonals snap to whichever axis has
/// the larger off-extent overshoot in degrees.
String _cardinalFromBbox(double droneLat, double droneLon, _Bbox bbox) {
  final dLat = droneLat > bbox.maxLat
      ? droneLat - bbox.maxLat
      : (droneLat < bbox.minLat ? bbox.minLat - droneLat : 0.0);
  final dLon = droneLon > bbox.maxLon
      ? droneLon - bbox.maxLon
      : (droneLon < bbox.minLon ? bbox.minLon - droneLon : 0.0);
  // Compare degrees-of-arc directly. cos(midLat) compression is small for
  // chevron purposes (we just want the dominant axis); skip it.
  if (dLat == 0 && dLon == 0) return "here";
  if (dLat >= dLon) {
    return droneLat > bbox.maxLat ? "north" : "south";
  }
  return droneLon > bbox.maxLon ? "east" : "west";
}

/// Background grid painter — extracted from _ProjectionPainter so the
/// procedural grid can render synchronously on first paint while the
/// aerial overlay (if any) fades in on top (LOCKED DESIGN DECISION D2).
class _GridBackgroundPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
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
  }

  @override
  bool shouldRepaint(covariant _GridBackgroundPainter old) => false;
}

class _ProjectionPainter extends CustomPainter {
  final List<Map<String, dynamic>> drones;
  final List<Map<String, dynamic>> findings;
  final _Bbox bbox;
  final Map<String, Color> colors;
  final Map<String, List<List<double>>> trails;

  _ProjectionPainter({
    required this.drones,
    required this.findings,
    required this.bbox,
    required this.colors,
    this.trails = const {},
  });

  @override
  void paint(Canvas canvas, Size size) {
    // No background — _GridBackgroundPainter renders the grid one layer
    // below this one (D2). This painter is foreground-only.

    Offset? project(num? la, num? lo) => _project(la, lo, bbox, size);

    // Tier-2: per-drone breadcrumb trails painted first (under everything
    // else). Each segment fades with age so the operator sees direction
    // at a glance. Oldest segment ~30% opacity, newest 100%; thicker
    // stroke + thin white outline make trails legible over the photographic
    // aerial overlay.
    for (final entry in trails.entries) {
      final droneId = entry.key;
      final pts = entry.value;
      if (pts.length < 2) continue;
      final color = colors[droneId] ?? Colors.indigo;
      for (int i = 1; i < pts.length; i++) {
        final p0 = project(pts[i - 1][0], pts[i - 1][1]);
        final p1 = project(pts[i][0], pts[i][1]);
        if (p0 == null || p1 == null) continue;
        final ageFrac = i / pts.length; // 0..1, newer = larger
        final alpha = 0.30 + 0.70 * ageFrac;
        // White halo behind colored stroke for marker contrast on
        // photographic backgrounds.
        canvas.drawLine(
          p0, p1,
          Paint()
            ..color = Colors.white.withValues(alpha: alpha * 0.7)
            ..strokeWidth = 5.0
            ..strokeCap = StrokeCap.round
            ..isAntiAlias = true,
        );
        canvas.drawLine(
          p0, p1,
          Paint()
            ..color = color.withValues(alpha: alpha)
            ..strokeWidth = 3.0
            ..strokeCap = StrokeCap.round
            ..isAntiAlias = true,
        );
      }
    }

    // Findings under drones.
    for (final f in findings) {
      final loc = f["location"] as Map<String, dynamic>?;
      final p = project(loc?["lat"] as num?, loc?["lon"] as num?);
      if (p == null) continue;
      final color = _findingColor((f["type"] as String?) ?? "");
      // D3: 7px white halo before the 6px colored disk so finding markers
      // stay legible on a JPEG photographic background.
      canvas.drawCircle(p, 7, Paint()..color = Colors.white);
      canvas.drawCircle(p, 6, Paint()..color = color);
    }

    // Drones on top. Drone-id labels are NOT painted here — they're real
    // widgets (white pills) rendered by _MapPanelState._buildDroneMarkers
    // (D3) so they antialias correctly over photographic backgrounds and
    // are a11y-discoverable.
    for (final d in drones) {
      final id = (d["drone_id"] as String?) ?? "?";
      final pos = d["position"] as Map<String, dynamic>?;
      final p = project(pos?["lat"] as num?, pos?["lon"] as num?);
      if (p == null) continue;
      final color = colors[id] ?? Colors.indigo;
      // Skip drones rendered as off-extent chevrons — those have their
      // own widget. Painter checks the same bounds the widget uses.
      if (p.dx < 0 || p.dx > size.width || p.dy < 0 || p.dy > size.height) {
        continue;
      }
      canvas.drawCircle(p, 9, Paint()..color = Colors.white);
      canvas.drawCircle(p, 8, Paint()..color = color);
    }
  }

  Color _findingColor(String type) {
    switch (type) {
      case "victim":
        return Colors.red.shade700;
      case "fire":
        return Colors.deepOrange.shade700;
      case "smoke":
        return Colors.orange.shade400;
      case "damaged_structure":
        return Colors.grey.shade700;
      case "blocked_route":
        return Colors.blue.shade700;
      default:
        return Colors.purple.shade700;
    }
  }

  @override
  bool shouldRepaint(covariant _ProjectionPainter old) {
    return drones != old.drones || findings != old.findings || bbox != old.bbox || trails != old.trails;
  }
}

/// Filled equilateral-ish triangle for off-extent chevrons (D1 follow-on).
/// The triangle's tip points "right" in its local frame; rotation is
/// applied by the parent Transform.rotate so it points toward the
/// off-canvas drone position.
class _ChevronPainter extends CustomPainter {
  final Color color;
  _ChevronPainter({required this.color});

  @override
  void paint(Canvas canvas, Size size) {
    final cx = size.width / 2;
    final cy = size.height / 2;
    final r = math.min(size.width, size.height) / 2;
    final path = Path()
      ..moveTo(cx + r, cy) // tip
      ..lineTo(cx - r * 0.7, cy - r * 0.7)
      ..lineTo(cx - r * 0.7, cy + r * 0.7)
      ..close();
    canvas.drawPath(path, Paint()..color = color);
    // White outline for marker contrast on photographic backgrounds (D3).
    canvas.drawPath(
      path,
      Paint()
        ..color = Colors.white
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2,
    );
  }

  @override
  bool shouldRepaint(covariant _ChevronPainter old) => old.color != color;
}
