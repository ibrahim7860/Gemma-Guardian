import 'dart:convert';
import 'package:flutter/foundation.dart';

/// Mission state held in memory; updated by every WebSocket state_update message.
///
/// This is intentionally loose-typed (Map<String, dynamic>) for Phase 1B —
/// the schema validates on the publisher side, so the dashboard trusts shape.
/// Phase 3 may introduce typed Dart models as the dashboard grows.
class MissionState extends ChangeNotifier {
  String? lastTimestamp;
  String? contractVersion;
  Map<String, dynamic>? egsState;
  List<dynamic> activeFindings = const [];
  List<dynamic> activeDrones = const [];
  String connectionStatus = "disconnected";

  /// Update from a raw `state_update` envelope.
  void applyStateUpdate(Map<String, dynamic> envelope) {
    if (envelope["type"] != "state_update") return;
    lastTimestamp = envelope["timestamp"] as String?;
    contractVersion = envelope["contract_version"] as String?;
    egsState = envelope["egs_state"] as Map<String, dynamic>?;
    activeFindings = (envelope["active_findings"] as List?) ?? const [];
    activeDrones = (envelope["active_drones"] as List?) ?? const [];
    notifyListeners();
  }

  void setConnectionStatus(String status) {
    connectionStatus = status;
    notifyListeners();
  }

  /// Try to parse a raw text frame; ignore non-JSON or unknown types.
  void applyRawFrame(String raw) {
    try {
      final decoded = jsonDecode(raw);
      if (decoded is Map<String, dynamic>) {
        applyStateUpdate(decoded);
      }
    } catch (e) {
      if (kDebugMode) {
        // ignore: avoid_print
        print("[MissionState] failed to decode frame: $e");
      }
    }
  }
}
