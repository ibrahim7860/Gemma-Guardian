import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../state/mission_state.dart';

class MapPanel extends StatelessWidget {
  const MapPanel({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<MissionState>(
      builder: (_, mission, __) {
        final droneCount = mission.activeDrones.length;
        return Container(
          color: Colors.grey.shade200,
          alignment: Alignment.center,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text("Map View — placeholder",
                  style: TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              Text("$droneCount drone(s) active"),
              const SizedBox(height: 4),
              Text("Last update: ${mission.lastTimestamp ?? "—"}",
                  style: Theme.of(context).textTheme.bodySmall),
            ],
          ),
        );
      },
    );
  }
}
