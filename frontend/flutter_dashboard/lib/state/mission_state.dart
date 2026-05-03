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

/// Per-command state machine for operator command translation.
///
/// (absent) → sending → translating → ready → dispatching → dispatched
///                                                       └→ ready (on redis_publish_failed echo, finding #5)
///                                          → (rephrase resets to absent)
///         → failed (on bridge error, WS drop, or 15s timeout)
///         → (orphaned: dropped from map entirely on second submit, finding #4)
enum CommandState { sending, translating, ready, dispatching, dispatched, failed }

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

  // ---- command translation state ------------------------------------------

  final Map<String, CommandState> _commandActions = {};
  final Map<String, Map<String, dynamic>> _commandTranslations = {};
  final Map<String, Timer> _commandTimers = {};
  String? _activeCommandId;

  String? get activeCommandId => _activeCommandId;
  CommandState? commandState(String commandId) => _commandActions[commandId];
  Map<String, dynamic>? commandTranslation(String commandId) =>
      _commandTranslations[commandId];

  /// Operator submitted a command for translation. Returns the command_id
  /// generated for this submission so the caller can correlate later.
  ///
  /// Single-slot: a fresh submit replaces the active id. **Adversarial
  /// finding #4 — orphan rule:** the prior cid is *dropped* from
  /// `_commandActions`, `_commandTranslations`, and `_commandTimers` so its
  /// Timer cannot fire later (no misleading snackbar) and so memory does not
  /// grow under aggressive resubmit cycles. Late ack/translation frames for
  /// the orphan find no entry and are silently dropped.
  String submitOperatorCommand({
    required String rawText,
    required String language,
    Duration translationTimeout = const Duration(seconds: 15),
  }) {
    // Orphan the prior active command (if any) before overwriting.
    final prior = _activeCommandId;
    if (prior != null && _commandActions.containsKey(prior)) {
      _commandTimers[prior]?.cancel();
      _commandTimers.remove(prior);
      _commandActions.remove(prior);
      _commandTranslations.remove(prior);
    }

    final commandId = _nextCommandId();
    _activeCommandId = commandId;
    _commandActions[commandId] = CommandState.sending;
    _commandTimers[commandId] = Timer(translationTimeout, () {
      // Promote to failed only if still in a non-terminal pre-ready state.
      final cur = _commandActions[commandId];
      if (cur == CommandState.sending || cur == CommandState.translating) {
        _commandActions[commandId] = CommandState.failed;
        _snackbarController.add("Translation lost — retry");
        notifyListeners();
      }
    });
    notifyListeners();
    sendOutbound({
      "type": "operator_command",
      "command_id": commandId,
      "language": language,
      "raw_text": rawText,
      "contract_version": gen.contractVersion,
    });
    return commandId;
  }

  /// Apply a `command_translation` frame. Drops late frames for terminal-state
  /// commands (1B) AND for orphaned commands no longer in the map (finding #4).
  void applyTranslation(Map<String, dynamic> envelope) {
    if (envelope["type"] != "command_translation") return;
    final cid = envelope["command_id"] as String?;
    if (cid == null) return;
    final cur = _commandActions[cid];
    if (cur == null) {
      // Orphaned cid — silent drop (finding #4).
      if (kDebugMode) {
        debugPrint("[MissionState] dropped translation for orphaned $cid");
      }
      return;
    }
    if (cur == CommandState.failed || cur == CommandState.dispatched ||
        cur == CommandState.dispatching) {
      // Late arrival on terminal/in-flight-dispatch state — log and drop.
      if (kDebugMode) {
        debugPrint("[MissionState] dropped late translation for $cid (state=$cur)");
      }
      return;
    }
    _commandTranslations[cid] = Map<String, dynamic>.from(envelope);
    _commandActions[cid] = CommandState.ready;
    _commandTimers[cid]?.cancel();
    _commandTimers.remove(cid);
    notifyListeners();
  }

  /// Operator clicked DISPATCH on the active command's preview pane.
  ///
  /// Adversarial finding #5 — non-optimistic: transition to `dispatching`
  /// (button shows spinner, REPHRASE disabled) and wait for the bridge ack
  /// before advancing to `dispatched`. On `redis_publish_failed` we return
  /// to `ready` so the operator can re-tap without re-translating.
  void dispatchActiveCommand() {
    final cid = _activeCommandId;
    if (cid == null) return;
    if (_commandActions[cid] != CommandState.ready) return;
    final translation = _commandTranslations[cid];
    if (translation == null || translation["valid"] != true) return;
    _commandActions[cid] = CommandState.dispatching;
    notifyListeners();
    sendOutbound({
      "type": "operator_command_dispatch",
      "command_id": cid,
      "contract_version": gen.contractVersion,
    });
  }

  /// Operator clicked REPHRASE — clear the active command from the foreground.
  /// The bookkeeping for the prior cid stays so a late ack/translation that
  /// arrives can be dropped via the late-arrival rule.
  void rephraseActiveCommand() {
    _activeCommandId = null;
    notifyListeners();
  }

  /// Called by detachSink — flip in-flight commands to failed.
  ///
  /// Includes `dispatching` (review finding): on WS drop while waiting for
  /// the dispatch ack, the cid would otherwise be stranded in `dispatching`
  /// forever, leaving a permanent spinner with no recovery path (REPHRASE
  /// is hidden during dispatching).
  void _failInFlightCommands() {
    final flipped = <String>[];
    _commandActions.forEach((id, st) {
      if (st == CommandState.sending ||
          st == CommandState.translating ||
          st == CommandState.dispatching) {
        flipped.add(id);
      }
    });
    for (final id in flipped) {
      _commandActions[id] = CommandState.failed;
      _commandTimers[id]?.cancel();
      _commandTimers.remove(id);
    }
    if (flipped.isNotEmpty) {
      _snackbarController.add("Connection lost — translation cancelled");
    }
  }

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
    // Drop the in-flight command bookkeeping — the bridge will never ack
    // these, and a reconnect's bridge starts fresh. Without this, the maps
    // grow unbounded under heavy disconnect/reconnect cycles.
    _pendingActions.clear();
    _commandToFinding.clear();
    _failInFlightCommands();
    if (flipped.isNotEmpty) {
      for (final id in flipped) {
        _findingActions[id] = ApprovalState.failed;
      }
      _snackbarController.add("Reconnect: please re-tap any pending approvals");
    }
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
  ///
  /// Idempotent against double-clicks: if the finding already has a
  /// non-failed terminal/pending state, this is a no-op. Without the guard,
  /// a fast double-tap (two pointerup events before the disabled-button
  /// rebuild lands) would publish two approvals to Redis with different
  /// command_ids — the EGS would see duplicate decisions for one finding.
  void markFinding(String findingId, String action) {
    assert(action == "approve" || action == "dismiss");
    final existing = _findingActions[findingId];
    if (existing != null && existing != ApprovalState.failed) {
      // Already pending or terminal — ignore the duplicate click.
      return;
    }
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
    final ack = envelope["ack"];
    final error = envelope["error"];

    // ---- command translation echoes ----
    if (commandId != null && _commandActions.containsKey(commandId)) {
      if (ack == "operator_command_received") {
        if (_commandActions[commandId] == CommandState.sending) {
          _commandActions[commandId] = CommandState.translating;
          notifyListeners();
        }
        return;
      }
      if (ack == "operator_command_dispatch") {
        // Adversarial finding #5: this is the canonical transition to
        // dispatched (no longer optimistic). Only transition from dispatching.
        if (_commandActions[commandId] == CommandState.dispatching) {
          _commandActions[commandId] = CommandState.dispatched;
          notifyListeners();
        }
        return;
      }
      if (error != null) {
        // Adversarial finding #5: redis_publish_failed during dispatching
        // must NOT burn the translation. Return to ready so operator can
        // re-tap. For non-dispatch errors, fall through to the failed path.
        if (error == "redis_publish_failed" &&
            _commandActions[commandId] == CommandState.dispatching) {
          _commandActions[commandId] = CommandState.ready;
          _snackbarController.add("Dispatch send failed — retry");
          notifyListeners();
          return;
        }
        _commandActions[commandId] = CommandState.failed;
        _commandTimers[commandId]?.cancel();
        _commandTimers.remove(commandId);
        if (error == "redis_publish_failed") {
          _snackbarController.add("Bridge could not reach Redis — retry");
        } else {
          _snackbarController.add("Command rejected — rephrase");
        }
        notifyListeners();
        return;
      }
    }

    // ---- finding approval echoes (existing Phase 3 path) ----
    String? findingId = envelope["finding_id"] as String?;
    if (findingId == null && commandId != null) {
      findingId = _commandToFinding[commandId];
    }
    if (findingId == null) return;
    if (ack == "finding_approval") {
      final action = commandId != null ? _pendingActions[commandId] : null;
      _findingActions[findingId] = action == "dismiss"
          ? ApprovalState.dismissed
          : ApprovalState.received;
    } else if (error != null) {
      _findingActions[findingId] = ApprovalState.failed;
      if (error == "unknown_finding_id") {
        _snackbarController.add("Finding aged out — refresh and retry");
      } else {
        _snackbarController.add("Approval not delivered — retry");
      }
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
    // Promote any non-confirmed/non-dismissed state to confirmed when
    // upstream marks the finding approved. Forward-compat: if the EGS
    // echo (via state_update with approved=true) arrives BEFORE the
    // bridge ack (or after a `failed` state from a transient error),
    // we still recognize the finding as confirmed instead of stranding
    // the row in pending/failed forever.
    for (final raw in activeFindings) {
      if (raw is! Map<String, dynamic>) continue;
      final id = raw["finding_id"] as String?;
      if (id == null) continue;
      if (raw["approved"] == true) {
        final cur = _findingActions[id];
        if (cur != null &&
            cur != ApprovalState.confirmed &&
            cur != ApprovalState.dismissed) {
          _findingActions[id] = ApprovalState.confirmed;
        }
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
        final t = decoded["type"];
        if (t == "echo") {
          handleEcho(decoded);
        } else if (t == "command_translation") {
          applyTranslation(decoded);
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
    for (final t in _commandTimers.values) {
      t.cancel();
    }
    _commandTimers.clear();
    _snackbarController.close();
    super.dispose();
  }
}
