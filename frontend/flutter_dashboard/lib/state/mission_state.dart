import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../generated/contract_version.dart' as gen;

/// Per-finding state machine for operator approve/dismiss interactions.
///
/// "Idle" is represented by the finding_id being absent from
/// `_findingActions` — there is no enum value for it.
///
/// (absent) → pending (operator clicked) → received (bridge ack) → confirmed (EGS echo)
///                                       → dismissed (bridge ack for dismiss)
///                                       → failed (bridge error or WS drop)
enum ApprovalState { pending, received, confirmed, dismissed, failed }

/// Mission state held in memory; updated by every WebSocket state_update
/// message and by operator actions.
///
/// This is intentionally loose-typed (`Map<String, dynamic>`) for the upstream
/// frames — the bridge validates on the publisher side, so the dashboard
/// trusts shape on `state_update`.
class MissionState extends ChangeNotifier {
  String? lastTimestamp;
  String? contractVersion;
  Map<String, dynamic>? egsState;
  List<dynamic> activeFindings = const [];
  List<dynamic> activeDrones = const [];
  String connectionStatus = "disconnected";

  // ---- outbound + per-finding state ----------------------------------------

  WebSocketSink? _sink;
  final Map<String, ApprovalState> _findingActions = {};
  // Tracks command_id → action so we know whether an ack means received or dismissed.
  final Map<String, String> _pendingActions = {};
  // Tracks command_id → finding_id so we can resolve echoes that omit finding_id.
  final Map<String, String> _commandToFinding = {};
  final StreamController<String> _snackbarController =
      StreamController<String>.broadcast();
  Stream<String> get snackbarStream => _snackbarController.stream;

  // command_id generator: ${sessionId4}-${ms}-${counter}
  final String _sessionId = _generateSessionId();
  int _counter = 0;

  static String _generateSessionId() {
    final r = Random.secure();
    const alphabet = "abcdefghijklmnopqrstuvwxyz0123456789";
    return List<String>.generate(4, (_) => alphabet[r.nextInt(alphabet.length)]).join();
  }

  String _nextCommandId() {
    final ms = DateTime.now().millisecondsSinceEpoch;
    _counter += 1;
    return "$_sessionId-$ms-$_counter";
  }

  ApprovalState? findingState(String findingId) => _findingActions[findingId];

  void attachSink(WebSocketSink sink) {
    _sink = sink;
  }

  /// Called when the WS connection drops. Any approvals still in `pending`
  /// transition to `failed` (button re-enables) and a single SnackBar event
  /// prompts the operator to re-tap.
  void detachSink() {
    _sink = null;
    final flipped = <String>[];
    _findingActions.forEach((id, state) {
      if (state == ApprovalState.pending) flipped.add(id);
    });
    if (flipped.isEmpty) {
      notifyListeners();
      return;
    }
    for (final id in flipped) {
      _findingActions[id] = ApprovalState.failed;
    }
    _snackbarController.add("Reconnect: please re-tap any pending approvals");
    notifyListeners();
  }

  /// Encode and write [envelope] to the attached sink. No-op if sink is null
  /// or connectionStatus is not "connected".
  void sendOutbound(Map<String, dynamic> envelope) {
    if (connectionStatus != "connected" || _sink == null) {
      if (kDebugMode) {
        debugPrint("[MissionState] sendOutbound dropped: status=$connectionStatus sink=${_sink != null}");
      }
      return;
    }
    _sink!.add(jsonEncode(envelope));
  }

  /// Operator clicked APPROVE or DISMISS on a finding row.
  void markFinding(String findingId, String action) {
    assert(action == "approve" || action == "dismiss");
    final commandId = _nextCommandId();
    _findingActions[findingId] = ApprovalState.pending;
    _pendingActions[commandId] = action;
    _commandToFinding[commandId] = findingId;
    notifyListeners();
    sendOutbound({
      "type": "finding_approval",
      "command_id": commandId,
      "finding_id": findingId,
      "action": action,
      "contract_version": gen.contractVersion,
    });
  }

  /// Handle an echo frame from the bridge.
  void handleEcho(Map<String, dynamic> envelope) {
    if (envelope["type"] != "echo") return;
    final commandId = envelope["command_id"] as String?;
    String? findingId = envelope["finding_id"] as String?;
    if (findingId == null && commandId != null) {
      findingId = _commandToFinding[commandId];
    }
    if (findingId == null) return;
    if (envelope["ack"] == "finding_approval") {
      final action = commandId != null ? _pendingActions[commandId] : null;
      _findingActions[findingId] = action == "dismiss"
          ? ApprovalState.dismissed
          : ApprovalState.received;
    } else if (envelope["error"] != null) {
      _findingActions[findingId] = ApprovalState.failed;
      _snackbarController.add("Approval not delivered — retry");
    }
    if (commandId != null) {
      _pendingActions.remove(commandId);
      _commandToFinding.remove(commandId);
    }
    notifyListeners();
  }

  // ---- inbound state_update -----------------------------------------------

  void applyStateUpdate(Map<String, dynamic> envelope) {
    if (envelope["type"] != "state_update") return;
    lastTimestamp = envelope["timestamp"] as String?;
    contractVersion = envelope["contract_version"] as String?;
    egsState = envelope["egs_state"] as Map<String, dynamic>?;
    activeFindings = (envelope["active_findings"] as List?) ?? const [];
    activeDrones = (envelope["active_drones"] as List?) ?? const [];
    // Promote received → confirmed when upstream marks the finding approved.
    for (final raw in activeFindings) {
      if (raw is! Map<String, dynamic>) continue;
      final id = raw["finding_id"] as String?;
      if (id == null) continue;
      if (_findingActions[id] == ApprovalState.received && raw["approved"] == true) {
        _findingActions[id] = ApprovalState.confirmed;
      }
    }
    notifyListeners();
  }

  void setConnectionStatus(String status) {
    connectionStatus = status;
    notifyListeners();
  }

  /// Try to parse a raw text frame; route by `type` field.
  void applyRawFrame(String raw) {
    try {
      final decoded = jsonDecode(raw);
      if (decoded is Map<String, dynamic>) {
        if (decoded["type"] == "echo") {
          handleEcho(decoded);
        } else {
          applyStateUpdate(decoded);
        }
      }
    } catch (e) {
      if (kDebugMode) {
        debugPrint("[MissionState] failed to decode frame: $e");
      }
    }
  }

  /// Findings that the operator has acted on but that have left
  /// `active_findings` upstream. Rendered as "archived" rows in FindingsPanel.
  List<String> archivedFindingIds() {
    final upstream = activeFindings
        .whereType<Map<String, dynamic>>()
        .map((f) => f["finding_id"] as String?)
        .where((id) => id != null)
        .toSet();
    return _findingActions.entries
        .where((e) =>
            e.value != ApprovalState.pending &&
            e.value != ApprovalState.failed &&
            !upstream.contains(e.key))
        .map((e) => e.key)
        .toList();
  }

  @override
  void dispose() {
    _snackbarController.close();
    super.dispose();
  }
}
