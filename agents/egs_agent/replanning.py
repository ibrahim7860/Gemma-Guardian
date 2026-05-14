import asyncio
import json
import logging
from typing import Any, Callable, Dict, List, Optional

import httpx

from shared.contracts import (
    CONFIG, RuleID, normalize, validate, AssignSurveyPoints, ReplanMission,
    AdapterError, RULE_REGISTRY
)
from shared.contracts.logging import ValidationEventLogger, now_iso_ms
from agents.egs_agent.validation import EGSValidationNode

logger = logging.getLogger(__name__)


# GH #32 / Phase D follow-up (2026-05-13, Hazim VRAM-constrained re-run):
# per-attempt httpx timeout on the Ollama call. Constraint pinned by
# `agents/egs_agent/tests/test_coordinator_replan_hang.py::
# test_per_attempt_timeout_fits_inside_outer_guard`:
#
#   EGS_HTTPX_PER_ATTEMPT_TIMEOUT_S × (CONFIG.validation.max_retries + 1)
#       + REPLAN_FALLBACK_HEADROOM_S
#       <= coordinator.REPLAN_OVERALL_TIMEOUT_S
#
# Why this matters: the deterministic round-robin fallback at the bottom
# of `assign_survey_points` only runs if the retry loop *exhausts*. On a
# VRAM-stalled box (Ollama hangs waiting for eviction) every retry hits its
# full per-attempt timeout. If retry-loop worst-case wall time exceeds the
# coordinator's outer `wait_for(REPLAN_OVERALL_TIMEOUT_S)` guard, the outer
# guard cancels the inner task mid-retry and the fallback is unreachable —
# which is exactly what `docs/sim-resilience-run-notes.md` §"2026-05-13"
# captures live (940 `skipped (already in flight)` lines, 0 `drones.*.tasks`
# publishes during a 240 s `resilience_v1` run with `timeout=180.0`).
#
# 30 s is 3× the typical first-call eviction latency Ibrahim measured in
# `scripts/measure_e4b_replan_latency.py`; with `max_retries=3` (4 attempts)
# the retry-loop worst-case is 30 × 4 = 120 s, well under the 240 s outer
# guard, leaving 120 s for the fallback path itself to run.
EGS_HTTPX_PER_ATTEMPT_TIMEOUT_S: float = 120.0


# Callback signature for the per-attempt sink the coordinator passes in.
# We pass a plain dict (already-validated by ReplanAttempt semantics on the
# coordinator side) rather than the model so this module stays decoupled from
# the Pydantic schema. The coordinator owns conversion + storage.
ReplanLogSink = Callable[[Dict[str, Any]], None]


def _build_attempt_record(
    *,
    attempt_n: int,
    valid: bool,
    rule_id: Optional[str],
    corrective_text: Optional[str],
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Construct a ReplanAttempt-shaped dict for the coordinator sink."""
    return {
        "timestamp": now_iso_ms(),
        "attempt_n": attempt_n,
        "valid": valid,
        "rule_id": rule_id,
        "corrective_text": corrective_text,
        "details": details or {},
    }


async def assign_survey_points(
    egs_state: Dict[str, Any],
    validation_node: EGSValidationNode,
    *,
    validation_logger: Optional[ValidationEventLogger] = None,
    log_sink: Optional[ReplanLogSink] = None,
) -> Dict[str, Any]:
    """Generates the survey point assignment using Gemma 4 E4B.

    Algorithm-1 corrective retry loop. Every per-attempt branch logs (a) a
    Contract 11 ValidationEvent line via ``validation_logger`` and (b) a
    transient ReplanAttempt dict via ``log_sink`` so the dashboard can render
    the wow-moment banner. Both sinks are optional (production wires them in;
    legacy callers and most existing tests don't provide them).
    """

    survey_points = egs_state.get("survey_points", [])
    drones = egs_state.get("drones_summary", {})

    active_drones = [d for d, info in drones.items() if info.get("status") == "active"]
    available_points = [p["id"] for p in survey_points if p.get("status") in ("unassigned", "failed")]

    if not available_points or not active_drones:
        return {}

    system_prompt = f"""You are the swarm coordinator.
Assign the following survey points to the active drones.
Active Drones: {active_drones}
Survey Points: {available_points}

Rules:
1. Every point must be assigned to exactly one drone.
2. Balance the workload so drones have approximately the same number of points.
3. No duplicate points.
"""

    endpoint = f"{CONFIG.inference.ollama_egs_endpoint}/api/chat"
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "Generate the assignment."}
    ]

    retries = 0
    max_retries = CONFIG.validation.max_retries

    def _log_in_progress(
        *, attempt_n: int, valid: bool, rule_id: Optional[str],
        corrective_text: Optional[str], canonical: Optional[Dict[str, Any]],
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        if validation_logger is not None:
            validation_logger.log(
                agent_id="egs",
                layer="egs",
                function_or_command="assign_survey_points",
                attempt=attempt_n,
                valid=valid,
                rule_id=rule_id,
                outcome="in_progress",
                raw_call=canonical,
            )
        if log_sink is not None:
            log_sink(_build_attempt_record(
                attempt_n=attempt_n,
                valid=valid,
                rule_id=rule_id,
                corrective_text=corrective_text,
                details=details,
            ))

    while retries <= max_retries:
        attempt_n = retries + 1
        payload = {
            "model": CONFIG.inference.egs_model,
            "messages": messages,
            "stream": False,
            "format": "json"
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    endpoint, json=payload,
                    timeout=EGS_HTTPX_PER_ATTEMPT_TIMEOUT_S,
                )
                resp.raise_for_status()
                data = resp.json()

                # Normalize
                canonical = normalize(data, layer="egs")

                # Structural Validation
                val_res = validation_node.validate_egs_function_call(canonical)
                if not val_res.valid:
                    rule = RULE_REGISTRY.get(val_res.failure_reason)
                    correction = rule.corrective_template.format(
                        field_path="", message=val_res.detail
                    ) if rule else val_res.detail
                    rule_id_str = (
                        val_res.failure_reason.value
                        if val_res.failure_reason is not None else None
                    )
                    _log_in_progress(
                        attempt_n=attempt_n, valid=False,
                        rule_id=rule_id_str,
                        corrective_text=correction,
                        canonical=canonical,
                        details={"detail": val_res.detail},
                    )
                    messages.append({"role": "assistant", "content": json.dumps(canonical)})
                    messages.append({"role": "user", "content": correction})
                    retries += 1
                    continue

                # Semantic / Stateful Validation
                if canonical.get("function") != "assign_survey_points":
                    correction = "You must use the assign_survey_points function."
                    _log_in_progress(
                        attempt_n=attempt_n, valid=False,
                        rule_id=None,
                        corrective_text=correction,
                        canonical=canonical,
                    )
                    messages.append({"role": "assistant", "content": json.dumps(canonical)})
                    messages.append({"role": "user", "content": correction})
                    retries += 1
                    continue

                args = canonical.get("arguments", {})
                assignments = args.get("assignments", [])

                # ASSIGNMENT_TOTAL_MISMATCH
                assigned_pts = sum([len(a.get("survey_point_ids", [])) for a in assignments])
                if assigned_pts != len(available_points):
                    rule = RULE_REGISTRY[RuleID.ASSIGNMENT_TOTAL_MISMATCH]
                    correction = rule.corrective_template.format(assigned=assigned_pts, total=len(available_points))
                    _log_in_progress(
                        attempt_n=attempt_n, valid=False,
                        rule_id=RuleID.ASSIGNMENT_TOTAL_MISMATCH.value,
                        corrective_text=correction,
                        canonical=canonical,
                        details={"assigned": assigned_pts, "total": len(available_points)},
                    )
                    messages.append({"role": "assistant", "content": json.dumps(canonical)})
                    messages.append({"role": "user", "content": correction})
                    retries += 1
                    continue

                # ASSIGNMENT_DUPLICATE_POINT
                all_assigned = []
                for a in assignments:
                    all_assigned.extend(a.get("survey_point_ids", []))
                if len(all_assigned) != len(set(all_assigned)):
                    rule = RULE_REGISTRY[RuleID.ASSIGNMENT_DUPLICATE_POINT]
                    # We could find the actual duplicate, but just use template
                    seen = set()
                    duplicate_id = "some_point"
                    for pid in all_assigned:
                        if pid in seen:
                            duplicate_id = pid
                            break
                        seen.add(pid)
                    correction = rule.corrective_template.format(point_id=duplicate_id)
                    _log_in_progress(
                        attempt_n=attempt_n, valid=False,
                        rule_id=RuleID.ASSIGNMENT_DUPLICATE_POINT.value,
                        corrective_text=correction,
                        canonical=canonical,
                        details={"duplicate_point_id": duplicate_id},
                    )
                    messages.append({"role": "assistant", "content": json.dumps(canonical)})
                    messages.append({"role": "user", "content": correction})
                    retries += 1
                    continue

                # ASSIGNMENT_DRONE_MISSING
                assigned_drones = [a.get("drone_id") for a in assignments]
                missing = [d for d in active_drones if d not in assigned_drones]
                if missing:
                    rule = RULE_REGISTRY[RuleID.ASSIGNMENT_DRONE_MISSING]
                    correction = rule.corrective_template.format(drone_id=missing[0])
                    _log_in_progress(
                        attempt_n=attempt_n, valid=False,
                        rule_id=RuleID.ASSIGNMENT_DRONE_MISSING.value,
                        corrective_text=correction,
                        canonical=canonical,
                        details={"missing_drone_id": missing[0]},
                    )
                    messages.append({"role": "assistant", "content": json.dumps(canonical)})
                    messages.append({"role": "user", "content": correction})
                    retries += 1
                    continue

                # Everything valid! Emit terminal logs.
                terminal_outcome = (
                    "success_first_try" if attempt_n == 1 else "corrected_after_retry"
                )
                if validation_logger is not None:
                    validation_logger.log(
                        agent_id="egs",
                        layer="egs",
                        function_or_command="assign_survey_points",
                        attempt=attempt_n,
                        valid=True,
                        rule_id=None,
                        outcome=terminal_outcome,
                        raw_call=canonical,
                    )
                if log_sink is not None:
                    log_sink(_build_attempt_record(
                        attempt_n=attempt_n,
                        valid=True,
                        rule_id=None,
                        corrective_text=None,
                    ))
                return canonical

        except AdapterError as e:
            correction = f"Return a proper JSON object. Error: {e}"
            _log_in_progress(
                attempt_n=attempt_n, valid=False,
                rule_id=None,
                corrective_text=correction,
                canonical=None,
                details={"adapter_error": str(e)},
            )
            messages.append({"role": "assistant", "content": "I failed to generate valid json."})
            messages.append({"role": "user", "content": correction})
            retries += 1
        except (httpx.HTTPError, asyncio.TimeoutError, json.JSONDecodeError) as e:
            # GH #32 / Bug 2 fix (Phase D resilience-scenario blocker): treat
            # transport-level failures and malformed JSON as retryable so the
            # deterministic fallback at the end of this function is reachable.
            # Pre-fix this was `except Exception: raise e`, which propagated
            # httpx.ReadTimeout / ConnectError up into _replan_impl, which
            # combined with Bug 3 (in-flight guard stuck) starved every
            # drone_failure-triggered replan during 240 s resilience runs.
            #
            # We don't append corrective messages here — the LLM didn't fail
            # to follow instructions, the transport did. Just retry with the
            # same messages so the LLM sees the same prompt on the retry.
            # After max_retries, fall through to the deterministic
            # round-robin fallback below.
            logger.warning(
                "Replanning attempt %d/%d failed (%s: %s); will retry or fall back",
                retries + 1, max_retries + 1, type(e).__name__, e,
            )
            retries += 1
        # Note: no bare `except Exception` here. Genuinely unexpected errors
        # (e.g. NameError, attribute errors from a refactor) should propagate
        # to _replan_impl's exception handler so they're not silently
        # swallowed by the fallback path. Add narrow except clauses above as
        # new retryable error classes surface.

    # Failed after retries - fallback deterministic (round robin)
    logger.error("LLM Replanning failed after retries, using deterministic fallback.")
    if validation_logger is not None:
        validation_logger.log(
            agent_id="egs",
            layer="egs",
            function_or_command="assign_survey_points",
            attempt=retries,
            valid=False,
            rule_id=None,
            outcome="failed_after_retries",
            raw_call=None,
        )
    if log_sink is not None:
        log_sink(_build_attempt_record(
            attempt_n=retries,
            valid=False,
            rule_id=None,
            corrective_text="Maximum retries exceeded — using deterministic round-robin fallback.",
            details={"fallback": "round_robin", "max_retries": max_retries},
        ))
    fallback_assignments = [{"drone_id": d, "survey_point_ids": []} for d in active_drones]
    for i, pt in enumerate(available_points):
        fallback_assignments[i % len(active_drones)]["survey_point_ids"].append(pt)

    return {
        "function": "assign_survey_points",
        "arguments": {
            "assignments": fallback_assignments
        }
    }
