// Feature A: Algorithm 1 transparency panel.
//
// Surfaces the hallucination retry loop (Nguyen et al. 2026 Algorithm 1)
// that gates every Gemma function call. Without this panel, judges can't
// see the safety net the paper describes — they only see "the model said
// something and we acted on it." This panel proves we validated every
// emission against a hard schema + corrective re-prompt.
//
// Layout: left "stats" block (first-try success %, total validations,
// rejected count) and right scrolling list of last ~4 events with the
// most recent rejection (rule_id + corrective hint) emphasized.
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../state/mission_state.dart';

class ValidationTicker extends StatelessWidget {
  const ValidationTicker({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<MissionState>(
      builder: (context, mission, _) {
        final ticks = mission.validationTicks;
        final total = ticks.length;
        final passed = ticks.where((t) => t["valid"] == true).length;
        final firstTry = ticks
            .where((t) => t["outcome"] == "success_first_try" || t["outcome"] == "c2a_adapter_victim")
            .length;
        final rejected = total - passed;
        final firstTryPct = total > 0 ? (firstTry * 100 / total).round() : 0;
        // Most recent rejection (for the highlighted "saved you from" card).
        final lastReject = ticks.firstWhere(
          (t) => t["valid"] != true,
          orElse: () => const {},
        );

        return Container(
          height: 92,
          color: const Color(0xFF0B0E13),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // --- LEFT: header + stats -----------------------------------
              SizedBox(
                width: 200,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: const [
                        Icon(Icons.verified_user, color: Color(0xFF7AD9C8), size: 14),
                        SizedBox(width: 4),
                        Text(
                          "ALGORITHM 1 VALIDATION",
                          style: TextStyle(
                            color: Color(0xFF7AD9C8),
                            fontSize: 9,
                            fontWeight: FontWeight.w800,
                            letterSpacing: 1.2,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 6),
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        Text(
                          "$firstTryPct%",
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 22,
                            fontWeight: FontWeight.w900,
                            height: 1,
                          ),
                        ),
                        const SizedBox(width: 6),
                        const Padding(
                          padding: EdgeInsets.only(bottom: 2),
                          child: Text(
                            "first-try valid",
                            style: TextStyle(color: Colors.white60, fontSize: 10),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 2),
                    Text(
                      "$total checks · $rejected re-prompted",
                      style: const TextStyle(color: Colors.white38, fontSize: 9),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 10),
              // --- MIDDLE: rolling event log -----------------------------
              Expanded(
                child: ticks.isEmpty
                    ? const Center(
                        child: Text(
                          "(waiting for Gemma calls…)",
                          style: TextStyle(
                            color: Colors.white38,
                            fontSize: 11,
                            fontFamily: "Menlo",
                          ),
                        ),
                      )
                    : ListView.builder(
                        scrollDirection: Axis.vertical,
                        itemCount: ticks.length.clamp(0, 5),
                        itemBuilder: (_, i) {
                          final t = ticks[i];
                          final valid = t["valid"] == true;
                          final agent = t["agent_id"]?.toString() ?? "?";
                          final func = t["function_or_command"]?.toString() ?? "?";
                          final rule = t["rule_id"]?.toString() ?? "";
                          final outcome = t["outcome"]?.toString() ?? "";
                          final shortFunc = func.length > 50 ? "${func.substring(0, 50)}…" : func;
                          final tagText = valid
                              ? (outcome == "c2a_adapter_victim" ? "C2A·OK" : outcome.replaceAll("_", " "))
                              : "REJECT";
                          return Padding(
                            padding: const EdgeInsets.symmetric(vertical: 1),
                            child: Row(
                              children: [
                                Container(
                                  padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
                                  decoration: BoxDecoration(
                                    color: valid
                                        ? const Color(0xFF7AD9C8).withValues(alpha: 0.15)
                                        : Colors.red.shade400.withValues(alpha: 0.20),
                                    borderRadius: BorderRadius.circular(2),
                                  ),
                                  child: Text(
                                    tagText.toUpperCase(),
                                    style: TextStyle(
                                      color: valid ? const Color(0xFF7AD9C8) : Colors.red.shade300,
                                      fontSize: 8,
                                      fontWeight: FontWeight.w800,
                                      letterSpacing: 0.6,
                                      fontFamily: "Menlo",
                                    ),
                                  ),
                                ),
                                const SizedBox(width: 6),
                                Expanded(
                                  child: Text(
                                    "$agent · $shortFunc${rule.isNotEmpty ? '  [$rule]' : ''}",
                                    overflow: TextOverflow.ellipsis,
                                    style: TextStyle(
                                      color: valid ? Colors.white70 : Colors.red.shade200,
                                      fontSize: 10,
                                      fontFamily: "Menlo",
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          );
                        },
                      ),
              ),
              // --- RIGHT: last rejected highlight (the safety-net story) -
              if (lastReject.isNotEmpty) ...[
                const SizedBox(width: 10),
                Container(
                  width: 260,
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
                  decoration: BoxDecoration(
                    color: Colors.red.shade900.withValues(alpha: 0.30),
                    borderRadius: BorderRadius.circular(4),
                    border: Border.all(color: Colors.red.shade400.withValues(alpha: 0.6), width: 0.8),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Row(
                        children: [
                          Icon(Icons.shield, color: Colors.red.shade300, size: 11),
                          const SizedBox(width: 4),
                          const Text(
                            "BLOCKED HALLUCINATION",
                            style: TextStyle(
                              color: Colors.white,
                              fontSize: 9,
                              fontWeight: FontWeight.w800,
                              letterSpacing: 1.0,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 2),
                      Text(
                        "rule_id: ${lastReject["rule_id"] ?? "?"}",
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 9,
                          fontWeight: FontWeight.w700,
                          fontFamily: "Menlo",
                        ),
                      ),
                      Text(
                        "${lastReject["agent_id"] ?? "?"} attempted: ${lastReject["function_or_command"] ?? "?"}",
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          color: Colors.white70,
                          fontSize: 9,
                          fontFamily: "Menlo",
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ],
          ),
        );
      },
    );
  }
}
