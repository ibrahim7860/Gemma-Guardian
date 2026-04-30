"""Memory store — short-term ring buffer + long-term log persisted to disk."""
from __future__ import annotations

import json
import time
from collections import deque
from pathlib import Path
from typing import Iterable


SHORT_TERM_WINDOW_S = 60.0
PERSIST_INTERVAL_S = 10.0


class MemoryStore:
    def __init__(self, drone_id: str, persist_dir: str | Path = "/tmp/gemma_guardian_logs"):
        self.drone_id = drone_id
        self.persist_path = Path(persist_dir) / f"{drone_id}_memory.jsonl"
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        self.short_term: deque[dict] = deque(maxlen=200)
        self.findings: list[dict] = []
        self.peer_broadcasts: list[dict] = []
        self.decisions: list[dict] = []
        self._last_persist = 0.0

    def record_decision(self, call: dict, validation_result, attempt: int) -> None:
        entry = {
            "ts": time.time(),
            "type": "decision",
            "call": call,
            "valid": getattr(validation_result, "valid", None),
            "failure_reason": getattr(validation_result, "failure_reason", None),
            "attempt": attempt,
        }
        self.short_term.append(entry)
        self.decisions.append(entry)
        if call and call.get("function") == "report_finding" and getattr(validation_result, "valid", False):
            self.findings.append({"ts": entry["ts"], **(call.get("arguments") or {})})
        self._maybe_persist()

    def record_peer_broadcast(self, broadcast: dict) -> None:
        entry = {"ts": time.time(), "type": "peer_broadcast", "broadcast": broadcast}
        self.short_term.append(entry)
        self.peer_broadcasts.append(broadcast)
        self._maybe_persist()

    def recent_peer_broadcasts(self, window_s: float = SHORT_TERM_WINDOW_S) -> Iterable[dict]:
        cutoff = time.time() - window_s
        return [b for b in self.peer_broadcasts if b.get("ts", 0) >= cutoff]

    def next_finding_id(self) -> str:
        """Return f_<drone_id>_<counter> with a per-drone monotonic counter.

        Format matches _common.json#/$defs/finding_id pattern:
            ^f_drone\\d+_\\d+$
        """
        self._finding_counter = getattr(self, "_finding_counter", 0) + 1
        return f"f_{self.drone_id}_{self._finding_counter}"

    def _maybe_persist(self) -> None:
        now = time.time()
        if now - self._last_persist < PERSIST_INTERVAL_S:
            return
        self._last_persist = now
        with self.persist_path.open("a") as f:
            while self.short_term:
                entry = self.short_term.popleft()
                f.write(json.dumps(entry) + "\n")


# Alias so tests and callers can use either name.
DroneMemory = MemoryStore
