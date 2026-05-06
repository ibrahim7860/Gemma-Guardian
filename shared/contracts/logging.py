"""Component logger setup and ValidationEventLogger.

Per Contract 11: every agent logs to <GG_LOG_DIR>/<component>.log
and every validation event lands in <GG_LOG_DIR>/validation_events.jsonl
in the shape of shared/schemas/validation_event.json.

GG_LOG_DIR defaults to /tmp/gemma_guardian_logs and is honored by the shell
entry points (launch_swarm.sh, run_full_demo.sh) AND by the Python defaults
in this module so test isolation via env-var override actually works.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Union

from . import VERSION

Layer = Literal["drone", "egs", "operator"]
Outcome = Literal[
    "success_first_try", "corrected_after_retry",
    "failed_after_retries", "in_progress",
]


def default_log_dir() -> Path:
    """Resolve the canonical log/data dir, honoring GG_LOG_DIR env var.

    All component logs, validation events, frames, and memory go under here.
    Shell entry points (launch_swarm.sh, run_full_demo.sh) read this var and
    callers from Python should too — otherwise test-isolation pass-through
    via `env={"GG_LOG_DIR": ...}` is a silent no-op.
    """
    return Path(os.environ.get("GG_LOG_DIR", "/tmp/gemma_guardian_logs"))


def setup_logging(
    component_name: str,
    base_dir: Union[Path, str, None] = None,
) -> logging.Logger:
    """Create a per-component file logger at <base_dir>/<component_name>.log.

    `base_dir` defaults to `default_log_dir()` (honors GG_LOG_DIR env var).
    """
    base = Path(base_dir) if base_dir is not None else default_log_dir()
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


def now_iso_ms() -> str:
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
        path: Union[Path, str, None] = None,
    ):
        self.path = (
            Path(path) if path is not None
            else default_log_dir() / "validation_events.jsonl"
        )
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
            "timestamp": now_iso_ms(),
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
