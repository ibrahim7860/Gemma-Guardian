"""Tail the validation event log (Contract 11) and surface the last N entries.

The log file is JSONL; we read it bottom-up, parse, and return up to N entries
in chronological order. This is the EGS-side consumer of what every agent
writes via shared.contracts.logging.ValidationEventLogger.
"""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any, Dict, List

from shared.contracts import CONFIG, validate

LOG_PATH = Path(CONFIG.logging.base_dir) / "validation_events.jsonl"


def tail(n: int = 10, path: Path | None = None) -> List[Dict[str, Any]]:
    """Return the last n schema-valid validation events as parsed dicts,
    oldest-first.

    Per eng-review Q3 (2026-05-07), each parsed event is run through
    `validate("validation_event", evt)` before inclusion. This protects
    `egs_state.recent_validation_events` (which is itself in Contract 3) from
    being poisoned by a malformed-but-JSON-valid line, which would otherwise
    fail `validate("egs_state", ...)` downstream and break the dashboard
    publish path.

    Returns [] if the file does not exist or is empty. Lines that fail JSON
    parse OR schema validation are skipped silently (best-effort read of a
    live log).

    `path` defaults to the module-level `LOG_PATH`. We resolve it at call
    time (not as a function default) so tests can monkeypatch
    `agents.egs_agent.validation_log_tail.LOG_PATH` and have the change take
    effect on the next call.
    """
    if path is None:
        path = LOG_PATH
    if not path.exists():
        return []
    buf: deque[Dict[str, Any]] = deque(maxlen=n)
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not validate("validation_event", evt).valid:
                continue
            buf.append(evt)
    return list(buf)
