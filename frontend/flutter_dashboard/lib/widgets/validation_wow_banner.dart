/// Beat 3c "wow moment" banner — surfaces the EGS replan retry loop live.
///
/// Mirrors `EgsLinkSeveredBanner` (main.dart): full-width strip mounted in
/// the dashboard shell's outer Column, hidden via `SizedBox.shrink()` when
/// there is nothing to show. Populated from
/// `MissionState.replanInFlightAttemptLog`, which is itself sourced from
/// `egs_state.replan_in_flight_attempt_log` (Contract 3 transient field
/// introduced in VERSION 1.1.0).
///
/// Render rules per the rev-2 plan (`docs/plans/2026-05-12-gate4-wow-moment.md`):
///
/// - One row per attempt.
/// - Outcome chip: red FAILED for `valid=false`, green PASSED for `valid=true`.
/// - `correctiveText` rendered verbatim. No Flutter-side rule_id → text map
///   (single source of truth lives in `shared/contracts/rules.py:RULE_REGISTRY`).
/// - 250 ms fade+slide entry via `AnimatedSwitcher` using only Flutter
///   primitives (no new pubspec deps).
///
/// Semantics identifiers (load-bearing for Phase 4 Playwright E2E and the
/// capture-day MCP verification):
///   `validation-wow-banner`
///   `validation-attempt-${n}`
///   `validation-attempt-${n}-outcome`
///   `validation-attempt-${n}-text`
library;

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/mission_state.dart';

class ValidationWowBanner extends StatelessWidget {
  const ValidationWowBanner({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<MissionState>(
      builder: (_, mission, _) {
        final log = mission.replanInFlightAttemptLog;
        return AnimatedSwitcher(
          duration: const Duration(milliseconds: 250),
          switchInCurve: Curves.easeOut,
          switchOutCurve: Curves.easeIn,
          transitionBuilder: (child, animation) {
            // Fade + small slide-from-top. Built-in primitives only.
            final slide = Tween<Offset>(
              begin: const Offset(0, -0.08),
              end: Offset.zero,
            ).animate(animation);
            return FadeTransition(
              opacity: animation,
              child: SlideTransition(position: slide, child: child),
            );
          },
          child: log.isEmpty
              ? const SizedBox.shrink(key: ValueKey('validation-wow-empty'))
              : _ValidationBannerBody(
                  key: const ValueKey('validation-wow-populated'),
                  attempts: log,
                ),
        );
      },
    );
  }
}

class _ValidationBannerBody extends StatelessWidget {
  final List<ReplanAttempt> attempts;
  const _ValidationBannerBody({super.key, required this.attempts});

  @override
  Widget build(BuildContext context) {
    return Semantics(
      identifier: 'validation-wow-banner',
      label: 'Validation loop — ${attempts.length} attempt(s)',
      container: true,
      child: Container(
        width: double.infinity,
        color: Colors.indigo.shade50,
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Row(
              children: [
                Icon(Icons.science_outlined, size: 14, color: Colors.indigo),
                SizedBox(width: 6),
                Text(
                  'VALIDATION LOOP',
                  style: TextStyle(
                    color: Colors.indigo,
                    fontWeight: FontWeight.w600,
                    fontSize: 11,
                    letterSpacing: 0.8,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 4),
            for (final a in attempts)
              _AttemptRow(key: ValueKey('attempt-${a.attemptN}'), attempt: a),
          ],
        ),
      ),
    );
  }
}

class _AttemptRow extends StatelessWidget {
  final ReplanAttempt attempt;
  const _AttemptRow({super.key, required this.attempt});

  @override
  Widget build(BuildContext context) {
    final n = attempt.attemptN;
    final outcomeLabel = attempt.valid ? 'PASSED' : 'FAILED';
    final outcomeColor = attempt.valid
        ? Colors.green.shade600
        : Colors.red.shade700;

    return Semantics(
      identifier: 'validation-attempt-$n',
      label: 'Attempt $n $outcomeLabel',
      container: true,
      explicitChildNodes: true,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            _SmallChip(
              label: 'Attempt $n',
              background: Colors.indigo.shade100,
              foreground: Colors.indigo.shade900,
            ),
            const SizedBox(width: 6),
            Semantics(
              identifier: 'validation-attempt-$n-outcome',
              label: outcomeLabel,
              container: true,
              child: _SmallChip(
                label: outcomeLabel,
                background: outcomeColor,
                foreground: Colors.white,
                bold: true,
              ),
            ),
            const SizedBox(width: 8),
            if (attempt.ruleId != null) ...[
              Text(
                attempt.ruleId!,
                style: const TextStyle(
                  fontFamily: 'monospace',
                  fontSize: 11,
                  fontWeight: FontWeight.w500,
                ),
              ),
              const SizedBox(width: 8),
            ],
            Expanded(
              child: Semantics(
                identifier: 'validation-attempt-$n-text',
                label: attempt.correctiveText ?? '',
                container: true,
                child: attempt.correctiveText != null
                    ? Text(
                        attempt.correctiveText!,
                        style: const TextStyle(
                          fontSize: 12,
                          fontStyle: FontStyle.italic,
                          color: Colors.black87,
                        ),
                        overflow: TextOverflow.ellipsis,
                        maxLines: 2,
                      )
                    // Empty-but-present text slot keeps the per-row
                    // Semantics identifier set complete and predictable
                    // (e.g. for the success_first_try row). Using an
                    // explicit empty Text instead of SizedBox.shrink so
                    // the Semantics node still materializes.
                    : const Text(''),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SmallChip extends StatelessWidget {
  final String label;
  final Color background;
  final Color foreground;
  final bool bold;
  const _SmallChip({
    required this.label,
    required this.background,
    required this.foreground,
    this.bold = false,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: foreground,
          fontSize: 11,
          fontWeight: bold ? FontWeight.bold : FontWeight.w500,
          letterSpacing: 0.4,
        ),
      ),
    );
  }
}
