import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../state/mission_state.dart';

class FindingsPanel extends StatelessWidget {
  const FindingsPanel({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<MissionState>(
      builder: (context, mission, _) {
        // Defensive shape check: drop entries missing a string finding_id
        // before mapping to tiles. The bridge validates upstream, but a
        // single malformed entry slipping through would otherwise crash
        // the entire panel via `as String` non-null casts below.
        final upstream = mission.activeFindings
            .whereType<Map<String, dynamic>>()
            .where((f) => f["finding_id"] is String)
            .toList()
            .reversed
            .toList();
        final archivedIds = mission.archivedFindingIds();

        if (upstream.isEmpty && archivedIds.isEmpty) {
          return const Center(child: Text("Findings — no findings yet"));
        }

        final tiles = <Widget>[];
        for (final f in upstream) {
          tiles.add(_FindingTile(finding: f));
        }
        for (final id in archivedIds) {
          tiles.add(_ArchivedTile(findingId: id, state: mission.findingState(id)!));
        }

        return ListView.separated(
          padding: const EdgeInsets.all(12),
          itemCount: tiles.length,
          separatorBuilder: (_, i) => const Divider(),
          itemBuilder: (_, i) => tiles[i],
        );
      },
    );
  }
}

class _FindingTile extends StatelessWidget {
  final Map<String, dynamic> finding;
  const _FindingTile({required this.finding});

  @override
  Widget build(BuildContext context) {
    // watch (not read) so the tile rebuilds when the per-finding state
    // changes even if the parent Consumer is bypassed (e.g., a future
    // refactor to ListView.builder without re-creating tiles).
    final mission = context.watch<MissionState>();
    final id = finding["finding_id"] as String;
    final state = mission.findingState(id);
    final disabled = state == ApprovalState.pending ||
        state == ApprovalState.received ||
        state == ApprovalState.confirmed ||
        state == ApprovalState.dismissed;

    final Color borderColor;
    switch (state) {
      case ApprovalState.confirmed:
        borderColor = Colors.green;
      case ApprovalState.dismissed:
        borderColor = Colors.grey.shade400;
      case ApprovalState.failed:
        borderColor = Colors.red.shade300;
      case ApprovalState.pending:
      case ApprovalState.received:
      case null:
        borderColor = Colors.transparent;
    }

    final titleStyle = state == ApprovalState.dismissed
        ? const TextStyle(decoration: TextDecoration.lineThrough)
        : null;

    final isSelected = mission.selectedFindingId == id;
    return Semantics(
      identifier: 'finding-tile-$id',
      label: '${(finding["type"] as String).toUpperCase()} '
          'severity ${finding["severity"]} from ${finding["source_drone_id"]}',
      child: Container(
        key: isSelected
            ? ValueKey('findings-row-highlight-$id')
            : null,
        decoration: BoxDecoration(
          color: isSelected ? Colors.blue.withValues(alpha: 0.08) : null,
          border: Border(left: BorderSide(color: borderColor, width: 4)),
        ),
        child: Opacity(
          opacity: state == ApprovalState.dismissed ? 0.5 : 1.0,
          child: ListTile(
            title: Text(
              "${(finding["type"] as String).toUpperCase()} "
              "(severity ${finding["severity"]}, conf ${finding["confidence"]})",
              style: titleStyle,
            ),
            subtitle: Text(
              "${finding["source_drone_id"]} · ${finding["timestamp"]}\n"
              "${finding["visual_description"]}",
            ),
            isThreeLine: true,
            trailing: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                _ApprovalIcon(state: state, findingId: id),
                const SizedBox(width: 8),
                ElevatedButton(
                  onPressed: disabled ? null : () => mission.markFinding(id, "approve"),
                  style: ElevatedButton.styleFrom(backgroundColor: Colors.green.shade600),
                  child: const Text("APPROVE"),
                ),
                const SizedBox(width: 4),
                OutlinedButton(
                  onPressed: disabled ? null : () => mission.markFinding(id, "dismiss"),
                  child: const Text("DISMISS"),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ArchivedTile extends StatelessWidget {
  final String findingId;
  final ApprovalState state;
  const _ArchivedTile({required this.findingId, required this.state});

  @override
  Widget build(BuildContext context) {
    final String label;
    switch (state) {
      case ApprovalState.dismissed:
        label = "dismissed";
      case ApprovalState.received:
      case ApprovalState.confirmed:
        label = "approved";
      case ApprovalState.pending:
      case ApprovalState.failed:
        // archivedFindingIds() filters these out, so reaching here is a
        // contract violation in MissionState rather than user-facing data.
        assert(false, "archived tile rendered with non-archivable state: $state");
        label = "approved";
    }
    return ListTile(
      title: Text(
        "$findingId (archived)",
        style: const TextStyle(fontStyle: FontStyle.italic),
      ),
      subtitle: Text("$label — archived from EGS state"),
      leading: _ApprovalIcon(state: state, findingId: findingId),
    );
  }
}

class _ApprovalIcon extends StatelessWidget {
  final ApprovalState? state;
  final String findingId;
  const _ApprovalIcon({required this.state, required this.findingId});

  @override
  Widget build(BuildContext context) {
    switch (state) {
      case ApprovalState.pending:
        return SizedBox(
          key: ValueKey("approval-icon-pending-$findingId"),
          width: 16, height: 16,
          child: const CircularProgressIndicator(strokeWidth: 2),
        );
      case ApprovalState.received:
        return Tooltip(
          message: "Received by bridge",
          child: Icon(
            Icons.check, size: 18, color: Colors.grey.shade600,
            key: ValueKey("approval-icon-received-$findingId"),
          ),
        );
      case ApprovalState.confirmed:
        return Tooltip(
          message: "Confirmed by EGS",
          child: Icon(
            Icons.check_circle, size: 18, color: Colors.green.shade700,
            key: ValueKey("approval-icon-confirmed-$findingId"),
          ),
        );
      case ApprovalState.dismissed:
        return Icon(
          Icons.close, size: 18, color: Colors.grey.shade600,
          key: ValueKey("approval-icon-dismissed-$findingId"),
        );
      case ApprovalState.failed:
        return Tooltip(
          message: "Not delivered — try again",
          child: Icon(
            Icons.error_outline, size: 18, color: Colors.red.shade700,
            key: ValueKey("approval-icon-failed-$findingId"),
          ),
        );
      case null:
        return SizedBox(key: ValueKey("approval-icon-idle-$findingId"));
    }
  }
}
