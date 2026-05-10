"""Memory store — short-term ring buffer + long-term log persisted to disk."""
from __future__ import annotations

import json
import logging
import time
from collections import deque
from pathlib import Path
from typing import Iterable


SHORT_TERM_WINDOW_S = 60.0
PERSIST_INTERVAL_S = 10.0

logger = logging.getLogger(__name__)


class MemoryStore:
    def __init__(self, drone_id: str, persist_dir: str | Path | None = None):
        from shared.contracts.logging import default_log_dir
        self.drone_id = drone_id
        base = Path(persist_dir) if persist_dir is not None else default_log_dir()
        self.persist_path = base / f"{drone_id}_memory.jsonl"
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        self.short_term: deque[dict] = deque(maxlen=200)
        self.findings: list[dict] = []
        self.peer_broadcasts: list[dict] = []
        self.decisions: list[dict] = []
        self._last_persist = 0.0

        # Durable per-drone finding_id counter. Restarting the drone-agent
        # process must NOT collide finding_ids with previously-emitted ones,
        # because EGS dedup (Component 4) keys on finding_id and a collision
        # would silently drop a real new finding as "already seen".
        self._counter_path = base / f"{drone_id}_finding_counter.txt"
        self._finding_counter = self._load_counter(self._counter_path)

    @staticmethod
    def _load_counter(path: Path) -> int:
        """Read the persisted counter. Tolerate empty/whitespace/garbage files
        by treating them as 0 and logging a warning. We don't want a single
        corrupted file to brick the drone — losing monotonicity at boot is
        a smaller harm than refusing to start."""
        if not path.exists():
            return 0
        try:
            raw = path.read_text()
        except OSError as e:
            logger.warning(
                "finding-counter file %s unreadable (%s); resetting to 0",
                path, e,
            )
            return 0
        stripped = raw.strip()
        if not stripped:
            # Empty or whitespace-only file: treat as 0 silently (this is the
            # post-write-truncate state during a crash window; not corruption).
            return 0
        try:
            return int(stripped)
        except ValueError:
            logger.warning(
                "finding-counter file %s contains non-integer %r; resetting to 0",
                path, stripped,
            )
            return 0

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
        """Return f_<drone_id>_<counter> with a per-drone monotonic counter,
        durable across process restart.

        Format matches _common.json#/$defs/finding_id pattern:
            ^f_drone\\d+_\\d+$

        Persistence note (no fsync — hackathon scope):
            write_text() returns before the kernel flushes the dirty page to
            stable storage. A power loss between write() and the kernel's
            background flush could lose the most recent increment, causing
            ONE finding_id to be reused after reboot. Acceptable for hackathon
            scale; if we ever ship to real edge hardware, swap in
            os.fsync(fd) on the directory + tempfile-rename for true durability.
        """
        self._finding_counter += 1
        self._counter_path.write_text(str(self._finding_counter))
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
