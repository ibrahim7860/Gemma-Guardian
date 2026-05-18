// Path γ-MAX++: horizontal strip of live drone camera feeds with bounding-box
// detection overlays, freeze-on-finding behavior, and a GEMMA E2B chip that
// flashes when each drone fires a finding. Frames update at ≤ 1 fps per
// drone (throttled at the bridge broadcaster). When a finding fires, the
// source drone's camera tile freezes for 4 seconds on that frame so the
// operator (and the video viewer) sees the visual that produced the
// `report_finding(...)` call.
import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../state/mission_state.dart';

class CameraStrip extends StatefulWidget {
  const CameraStrip({super.key});

  @override
  State<CameraStrip> createState() => _CameraStripState();
}

class _CameraStripState extends State<CameraStrip> {
  // Force a periodic rebuild so freeze-state and chip flash transition
  // out cleanly even when no new frames arrive.
  Timer? _rebuildTimer;
  @override
  void initState() {
    super.initState();
    _rebuildTimer = Timer.periodic(const Duration(milliseconds: 250),
        (_) { if (mounted) setState(() {}); });
  }

  @override
  void dispose() {
    _rebuildTimer?.cancel();
    super.dispose();
  }

  static const List<String> _expectedDrones = ["drone1", "drone2", "drone3"];

  @override
  Widget build(BuildContext context) {
    return Consumer<MissionState>(
      builder: (context, mission, _) {
        return Container(
          height: 200,
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
          decoration: BoxDecoration(
            color: Colors.grey.shade100,
            border: Border(
              bottom: BorderSide(color: Colors.grey.shade300, width: 1),
            ),
          ),
          child: Row(
            children: [
              for (final droneId in _expectedDrones) ...[
                Expanded(child: _CameraTile(droneId: droneId, mission: mission)),
                const SizedBox(width: 8),
              ],
            ]..removeLast(),
          ),
        );
      },
    );
  }
}

class _CameraTile extends StatelessWidget {
  final String droneId;
  final MissionState mission;
  const _CameraTile({required this.droneId, required this.mission});

  @override
  Widget build(BuildContext context) {
    final isFrozen = mission.isFrozen(droneId);
    final frame = isFrozen ? mission.frozenFrame(droneId) : mission.latestCameraFrame(droneId);
    final detections = isFrozen
        ? mission.frozenDetections(droneId)
        : mission.latestDetections(droneId);
    final sinceFire = mission.sinceLastFindingFire(droneId);
    final chipFlashing = sinceFire != null && sinceFire.inMilliseconds < 1500;

    return LayoutBuilder(
      builder: (context, constraints) {
        return Container(
          decoration: BoxDecoration(
            color: Colors.black,
            borderRadius: BorderRadius.circular(6),
            border: Border.all(
              color: isFrozen ? Colors.red.shade400 : Colors.grey.shade400,
              width: isFrozen ? 2.5 : 1,
            ),
          ),
          clipBehavior: Clip.antiAlias,
          child: Stack(
            children: [
              if (frame != null)
                Positioned.fill(
                  child: Image.memory(
                    frame,
                    fit: BoxFit.cover,
                    gaplessPlayback: true,
                    errorBuilder: (_, _, _) => const Center(
                      child: Text("decode error",
                          style: TextStyle(color: Colors.red, fontSize: 11)),
                    ),
                  ),
                )
              else
                const Center(
                  child: Text("no camera feed yet",
                      style: TextStyle(color: Colors.white54, fontSize: 11)),
                ),
              // γ-MAX++ — bounding box overlays scaled to tile dimensions.
              // bbox coords are in the 1024×576 frame space; rescale to tile.
              if (frame != null && detections.isNotEmpty)
                ...detections.map((det) => _DetectionBox(
                      detection: det,
                      tileWidth: constraints.maxWidth,
                      tileHeight: constraints.maxHeight,
                    )),
              // Drone label (top-left)
              Positioned(
                top: 6,
                left: 6,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: Colors.black.withValues(alpha: 0.6),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(droneId,
                      style: const TextStyle(
                          color: Colors.white,
                          fontSize: 11,
                          fontWeight: FontWeight.w600,
                          letterSpacing: 0.3)),
                ),
              ),
              // γ-MAX++ — GEMMA E2B chip flashes when a finding fires.
              // Static chip is dim; during 1.5s flash window it glows teal.
              Positioned(
                top: 6,
                right: 6,
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 300),
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: chipFlashing
                        ? const Color(0xFF00E1B0)
                        : Colors.black.withValues(alpha: 0.6),
                    borderRadius: BorderRadius.circular(4),
                    boxShadow: chipFlashing
                        ? [BoxShadow(color: const Color(0xFF00E1B0).withValues(alpha: 0.6), blurRadius: 8)]
                        : null,
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        chipFlashing ? Icons.bolt : Icons.memory,
                        color: chipFlashing ? Colors.black : Colors.white,
                        size: 10,
                      ),
                      const SizedBox(width: 3),
                      Text("gemma4:e2b",
                          style: TextStyle(
                              color: chipFlashing ? Colors.black : Colors.white,
                              fontSize: 9,
                              fontWeight: FontWeight.w700,
                              letterSpacing: 0.5)),
                    ],
                  ),
                ),
              ),
              // γ-MAX++ — FROZEN indicator while showing the detection frame
              if (isFrozen)
                Positioned(
                  bottom: 6,
                  left: 6,
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                    decoration: BoxDecoration(
                      color: Colors.red.shade700,
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: const Text("DETECTION FRAME",
                        style: TextStyle(
                            color: Colors.white,
                            fontSize: 9,
                            fontWeight: FontWeight.w800,
                            letterSpacing: 0.6)),
                  ),
                ),
            ],
          ),
        );
      },
    );
  }
}

/// Renders a single detection bounding box scaled from 1024×576 frame space
/// onto the tile's actual rendered dimensions. The bbox coords come straight
/// from the bridge's bbox sidecar — they represent where the model detected
/// the object in the source frame.
class _DetectionBox extends StatelessWidget {
  final Map<String, dynamic> detection;
  final double tileWidth;
  final double tileHeight;
  const _DetectionBox({required this.detection, required this.tileWidth, required this.tileHeight});

  static const double _frameW = 1024.0;
  static const double _frameH = 576.0;

  @override
  Widget build(BuildContext context) {
    final bbox = detection["bbox"];
    if (bbox is! List || bbox.length != 4) return const SizedBox.shrink();
    final x = (bbox[0] as num).toDouble();
    final y = (bbox[1] as num).toDouble();
    final w = (bbox[2] as num).toDouble();
    final h = (bbox[3] as num).toDouble();
    // BoxFit.cover scales source frame to FILL the tile, preserving aspect.
    // Compute the actual rendered scale + offset so the bbox lands correctly.
    final scale = (tileWidth / _frameW > tileHeight / _frameH)
        ? tileWidth / _frameW
        : tileHeight / _frameH;
    final renderedW = _frameW * scale;
    final renderedH = _frameH * scale;
    final offX = (tileWidth - renderedW) / 2;
    final offY = (tileHeight - renderedH) / 2;
    final boxX = offX + x * scale;
    final boxY = offY + y * scale;
    final boxW = w * scale;
    final boxH = h * scale;
    final labelText = "${detection["label"] ?? "?"} ${((detection["confidence"] ?? 0) as num).toStringAsFixed(2)}";
    // source: "gemma_c2a" = real model-emitted bbox (Gemma 4 detect person)
    //         "sard_gt"   = SARD ground-truth sidecar overlay
    final source = detection["source"]?.toString() ?? "";
    final isModel = source == "gemma_c2a";
    // Teal for model output (matches GEMMA chip color), red for fixture GT.
    final boxColor = isModel ? const Color(0xFF00E1B0) : Colors.red.shade400;
    final ribbonColor = isModel ? const Color(0xFF00E1B0) : Colors.red.shade600;
    final ribbonText = isModel ? "GEMMA · $labelText" : "GT · $labelText";

    return Positioned.fill(
      child: IgnorePointer(
        child: Stack(
          clipBehavior: Clip.none,
          children: [
            // The bounding rectangle itself.
            Positioned(
              left: boxX,
              top: boxY,
              width: boxW,
              height: boxH,
              child: Container(
                decoration: BoxDecoration(
                  border: Border.all(color: boxColor, width: 2.5),
                  boxShadow: [
                    BoxShadow(color: boxColor.withValues(alpha: 0.45), blurRadius: 6),
                  ],
                ),
              ),
            ),
            // Label rendered as a separate Positioned with no width
            // constraint — sits above the box so narrow boxes don't wrap
            // the "VICTIM 0.85" text into two lines.
            Positioned(
              left: boxX,
              top: (boxY - 16).clamp(0.0, double.infinity),
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
                color: ribbonColor,
                child: Text(
                  ribbonText,
                  maxLines: 1,
                  softWrap: false,
                  overflow: TextOverflow.visible,
                  style: TextStyle(
                    color: isModel ? Colors.black : Colors.white,
                    fontSize: 10,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
