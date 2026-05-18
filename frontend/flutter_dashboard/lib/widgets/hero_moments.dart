// Feature C: Hero Moments timeline.
//
// A narrative banner that announces demo beats as they happen. This is
// what turns a "wall of stats" into a "story the judge can follow." Each
// beat has a trigger condition derived from MissionState, a short title,
// and a teal pulse animation that draws the eye exactly when the beat
// fires.
//
// Beats (in order of likely fire):
//   1. First victim located         (first finding type=victim arrives)
//   2. Multilingual command live    (command_translation env != null)
//   3. EGS link severed             (egsLinkSevered transitions true)
//   4. Standalone autonomy holding  (any drone agent_status=="standalone")
//   5. Link restored                (egsLinkSevered transitions false after severed)
//
// Each beat triggers exactly once per page load (state held in this
// widget). After firing, it remains "lit" for 12 seconds, then fades to
// a quiet "completed" indicator that stays visible to show progress.
import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../state/mission_state.dart';

class HeroMoments extends StatefulWidget {
  const HeroMoments({super.key});
  @override
  State<HeroMoments> createState() => _HeroMomentsState();
}

class _Beat {
  final String id;
  final String title;
  final IconData icon;
  bool fired = false;
  DateTime? firedAt;
  _Beat({required this.id, required this.title, required this.icon});
}

class _HeroMomentsState extends State<HeroMoments> {
  final List<_Beat> _beats = [
    _Beat(id: "victim", title: "Survivor located by Gemma 4 + C2A LoRA", icon: Icons.favorite),
    _Beat(id: "cmd", title: "Multilingual command translated by Gemma 4 E4B", icon: Icons.translate),
    _Beat(id: "severed", title: "EGS link severed — drones operating standalone", icon: Icons.link_off),
    _Beat(id: "standalone", title: "Standalone autonomy holding (Gemma running on-device)", icon: Icons.flash_on),
    _Beat(id: "restored", title: "Link restored — buffered findings drained", icon: Icons.link),
  ];

  bool _severedSeen = false;
  Timer? _refresh;

  @override
  void initState() {
    super.initState();
    // Periodic rebuild so the "12s lit window" decays even when no new
    // state_update fires.
    _refresh = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _refresh?.cancel();
    super.dispose();
  }

  void _maybeFire(String id, bool trigger) {
    if (!trigger) return;
    final beat = _beats.firstWhere((b) => b.id == id);
    if (beat.fired) return;
    beat.fired = true;
    beat.firedAt = DateTime.now();
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<MissionState>(
      builder: (_, mission, _) {
        // Beat triggers — pure functions of state, no side effects in build.
        _maybeFire("victim", mission.recentFindings.any((f) => f["type"] == "victim"));
        _maybeFire(
          "cmd",
          mission.commandTranslationCount > 0,
        );
        final severed = mission.egsLinkSevered;
        if (severed) _severedSeen = true;
        _maybeFire("severed", severed);
        _maybeFire(
          "standalone",
          mission.activeDrones.any((d) => d is Map && d["agent_status"] == "standalone"),
        );
        _maybeFire("restored", _severedSeen && !severed);

        // Most recent fired beat = the "live" one shown big.
        final active = _beats.where((b) => b.fired).toList()
          ..sort((a, b) => (b.firedAt ?? DateTime(0)).compareTo(a.firedAt ?? DateTime(0)));
        final live = active.isNotEmpty ? active.first : null;
        final isHot = live != null &&
            DateTime.now().difference(live.firedAt!) < const Duration(seconds: 12);
        return Container(
          width: double.infinity,
          color: const Color(0xFF0E1117),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
          child: Row(
            children: [
              // Step pips for all beats — show progress at a glance.
              for (final b in _beats) ...[
                _BeatPip(beat: b),
                const SizedBox(width: 6),
              ],
              const SizedBox(width: 12),
              if (live != null) ...[
                AnimatedContainer(
                  duration: const Duration(milliseconds: 300),
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    color: isHot ? const Color(0xFF00E1B0) : const Color(0xFF1B2230),
                    borderRadius: BorderRadius.circular(4),
                    boxShadow: isHot
                        ? [BoxShadow(color: const Color(0xFF00E1B0).withValues(alpha: 0.55), blurRadius: 10)]
                        : null,
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(live.icon, color: isHot ? Colors.black : const Color(0xFF7AD9C8), size: 14),
                      const SizedBox(width: 6),
                      Text(
                        live.title,
                        style: TextStyle(
                          color: isHot ? Colors.black : Colors.white,
                          fontWeight: FontWeight.w700,
                          fontSize: 12,
                          letterSpacing: 0.3,
                        ),
                      ),
                    ],
                  ),
                ),
              ] else
                const Text(
                  "Hero moments will light up as the mission unfolds…",
                  style: TextStyle(color: Colors.white54, fontSize: 11),
                ),
            ],
          ),
        );
      },
    );
  }
}

class _BeatPip extends StatelessWidget {
  final _Beat beat;
  const _BeatPip({required this.beat});
  @override
  Widget build(BuildContext context) {
    final hot = beat.firedAt != null &&
        DateTime.now().difference(beat.firedAt!) < const Duration(seconds: 12);
    final color = !beat.fired
        ? Colors.white24
        : (hot ? const Color(0xFF00E1B0) : const Color(0xFF7AD9C8).withValues(alpha: 0.6));
    return Tooltip(
      message: beat.title,
      child: Container(
        width: 18,
        height: 18,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: color,
          border: Border.all(color: Colors.black.withValues(alpha: 0.4), width: 0.6),
        ),
        child: Icon(beat.icon, size: 10, color: beat.fired ? Colors.black : Colors.white60),
      ),
    );
  }
}
