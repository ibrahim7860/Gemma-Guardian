// Path γ-MAX++: prominent "Survivors located" stat with optional progress
// bar. Connects the abstract finding count to lives. Renders in a banner
// above the four-panel grid so judges (and operators) see it immediately.
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../state/mission_state.dart';

class SurvivorStat extends StatelessWidget {
  const SurvivorStat({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<MissionState>(
      builder: (context, mission, _) {
        final found = mission.survivorsLocated;
        final total = mission.survivorsEstimatedTotal;
        final pct = (total != null && total > 0)
            ? (found / total).clamp(0.0, 1.0)
            : null;
        return Container(
          color: const Color(0xFF0E1117),
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Icon(Icons.favorite, color: Colors.red.shade400, size: 22),
              const SizedBox(width: 10),
              const Text(
                "SURVIVORS LOCATED",
                style: TextStyle(
                  color: Colors.white70,
                  fontWeight: FontWeight.w700,
                  fontSize: 12,
                  letterSpacing: 1.2,
                ),
              ),
              const SizedBox(width: 14),
              Text(
                "$found",
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 30,
                  fontWeight: FontWeight.w900,
                  height: 1,
                ),
              ),
              if (total != null) ...[
                const SizedBox(width: 6),
                Text(
                  "/ ~$total at risk",
                  style: const TextStyle(
                    color: Colors.white54,
                    fontSize: 14,
                    fontWeight: FontWeight.w500,
                  ),
                ),
              ],
              const SizedBox(width: 24),
              if (pct != null)
                Expanded(
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(4),
                    child: LinearProgressIndicator(
                      value: pct,
                      minHeight: 10,
                      backgroundColor: Colors.white12,
                      color: Colors.red.shade400,
                    ),
                  ),
                )
              else
                const Expanded(
                  child: SizedBox.shrink(),
                ),
              const SizedBox(width: 12),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  border: Border.all(color: Colors.white24),
                  borderRadius: BorderRadius.circular(4),
                ),
                child: const Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(Icons.memory, color: Color(0xFF7AD9C8), size: 12),
                    SizedBox(width: 4),
                    Text("gemma4 · on-device",
                        style: TextStyle(
                            color: Colors.white,
                            fontSize: 10,
                            fontWeight: FontWeight.w700,
                            letterSpacing: 0.6)),
                  ],
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}
