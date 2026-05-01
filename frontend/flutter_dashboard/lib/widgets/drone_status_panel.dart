import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../state/mission_state.dart';

class DroneStatusPanel extends StatelessWidget {
  const DroneStatusPanel({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<MissionState>(
      builder: (_, mission, __) {
        if (mission.activeDrones.isEmpty) {
          return const _EmptyPanel(label: "Drone Status", hint: "No drones online");
        }
        return ListView.separated(
          padding: const EdgeInsets.all(12),
          itemCount: mission.activeDrones.length,
          separatorBuilder: (_, __) => const Divider(),
          itemBuilder: (_, i) {
            final d = mission.activeDrones[i] as Map<String, dynamic>;
            return ListTile(
              title: Text("${d["drone_id"]} — ${d["agent_status"]}"),
              subtitle: Text(
                "Battery ${d["battery_pct"]}% · "
                "Task: ${d["current_task"] ?? "idle"} · "
                "Findings: ${d["findings_count"]} · "
                "Validation fails: ${d["validation_failures_total"]}",
              ),
            );
          },
        );
      },
    );
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
