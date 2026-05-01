"""Component logger setup and ValidationEventLogger.

Per Contract 11: every agent logs to /tmp/gemma_guardian_logs/<component>.log
and every validation event lands in /tmp/gemma_guardian_logs/validation_events.jsonl
in the shape of shared/schemas/validation_event.json.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Union

from . import VERSION

Layer = Literal["drone", "egs", "operator"]
Outcome = Literal[
    "success_first_try", "corrected_after_retry",
    "failed_after_retries", "in_progress",
]


def setup_logging(
    component_name: str,
    base_dir: Union[Path, str] = "/tmp/gemma_guardian_logs",
) -> logging.Logger:
    """Create a per-component file logger at <base_dir>/<component_name>.log."""
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(component_name)
    if not logger.handlers:
        handler = logging.FileHandler(base / f"{component_name}.log")
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def _now_iso_ms() -> str:
    """Produce an ISO 8601 UTC timestamp with millisecond precision and trailing Z.

    Matches _common.json#/$defs/iso_timestamp_utc_ms pattern:
        ^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class ValidationEventLogger:
    """Append-only JSONL writer for validation events.

    Each line conforms to shared/schemas/validation_event.json (Contract 11).
    """

    def __init__(
        self,
        path: Union[Path, str] = "/tmp/gemma_guardian_logs/validation_events.jsonl",
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        *,
        agent_id: str,
        layer: Layer,
        function_or_command: str,
        attempt: int,
        valid: bool,
        rule_id: Optional[str],
        outcome: Outcome,
        raw_call: Optional[Dict[str, Any]],
    ) -> None:
        record = {
            "timestamp": _now_iso_ms(),
            "agent_id": agent_id,
            "layer": layer,
            "function_or_command": function_or_command,
            "attempt": attempt,
            "valid": valid,
            "rule_id": rule_id,
            "outcome": outcome,
            "raw_call": raw_call,
            "contract_version": VERSION,
        }
        with self.path.open("a") as f:
            f.write(json.dumps(record) + "\n")
