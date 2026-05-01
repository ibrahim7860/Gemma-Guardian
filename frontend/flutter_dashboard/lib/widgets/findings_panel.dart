import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../state/mission_state.dart';

class FindingsPanel extends StatelessWidget {
  const FindingsPanel({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<MissionState>(
      builder: (_, mission, __) {
        if (mission.activeFindings.isEmpty) {
          return const Center(child: Text("Findings — no findings yet"));
        }
        // Newest first.
        final reversed = mission.activeFindings.reversed.toList();
        return ListView.separated(
          padding: const EdgeInsets.all(12),
          itemCount: reversed.length,
          separatorBuilder: (_, __) => const Divider(),
          itemBuilder: (_, i) {
            final f = reversed[i] as Map<String, dynamic>;
            return ListTile(
              title: Text(
                "${(f["type"] as String).toUpperCase()} "
                "(severity ${f["severity"]}, conf ${f["confidence"]})",
              ),
              subtitle: Text(
                "${f["source_drone_id"]} · ${f["timestamp"]}\n"
                "${f["visual_description"]}",
              ),
              isThreeLine: true,
            );
          },
        );
      },
    );
  }
}
