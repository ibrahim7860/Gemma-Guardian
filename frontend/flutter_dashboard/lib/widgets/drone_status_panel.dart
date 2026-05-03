import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../state/mission_state.dart';

class DroneStatusPanel extends StatelessWidget {
  const DroneStatusPanel({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<MissionState>(
      builder: (context, mission, child) {
        if (mission.activeDrones.isEmpty) {
          return const _EmptyPanel(label: "Drone Status", hint: "No drones online");
        }
        final events = _validationEventsByDrone(mission.egsState);
        return ListView.separated(
          padding: const EdgeInsets.all(12),
          itemCount: mission.activeDrones.length,
          separatorBuilder: (_, _) => const Divider(),
          itemBuilder: (_, i) {
            final d = mission.activeDrones[i] as Map<String, dynamic>;
            final droneId = d["drone_id"] as String? ?? "drone?";
            final perDrone = events[droneId] ?? const <Map<String, dynamic>>[];
            return ListTile(
              isThreeLine: true,
              title: Text("$droneId — ${d["agent_status"]}"),
              subtitle: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    "Battery ${d["battery_pct"]}% · "
                    "Task: ${d["current_task"] ?? "idle"} · "
                    "Findings: ${d["findings_count"]} · "
                    "Validation fails: ${d["validation_failures_total"]}",
                  ),
                  const SizedBox(height: 2),
                  Text(
                    _tickerLine(perDrone),
                    style: TextStyle(
                      fontSize: 11,
                      color: perDrone.isEmpty ? Colors.grey[600] : Colors.orange[800],
                    ),
                  ),
                ],
              ),
            );
          },
        );
      },
    );
  }

  /// Group recent_validation_events by agent (drone_id). Returns empty map
  /// when egs_state is null (reconnect window) so the panel renders cleanly.
  Map<String, List<Map<String, dynamic>>> _validationEventsByDrone(Map<String, dynamic>? egs) {
    if (egs == null) return const {};
    final raw = egs["recent_validation_events"];
    if (raw is! List) return const {};
    final result = <String, List<Map<String, dynamic>>>{};
    for (final entry in raw) {
      if (entry is! Map<String, dynamic>) continue;
      final agent = entry["agent"] as String?;
      if (agent == null) continue;
      result.putIfAbsent(agent, () => []).add(entry);
    }
    return result;
  }

  String _tickerLine(List<Map<String, dynamic>> events) {
    if (events.isEmpty) return "Validation: 0 fails";
    final last = events.first;
    final ts = (last["timestamp"] as String?) ?? "";
    final shortTs = ts.length >= 19 ? ts.substring(11, 19) : ts;
    final issue = last["issue"] ?? "?";
    return "Validation: ${events.length} fails (last: $shortTs — $issue)";
  }
}

class _EmptyPanel extends StatelessWidget {
  final String label;
  final String hint;
  const _EmptyPanel({required this.label, required this.hint});
  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Text(label, style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          Text(hint, style: Theme.of(context).textTheme.bodySmall),
        ],
      ),
    );
  }
}
