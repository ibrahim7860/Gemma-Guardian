"""FindingBuffer — FIFO ring buffer with JSONL persistence for standalone-window findings.

The drone agent uses this when its EGS link is severed so that findings produced
during the disconnection window survive a process crash AND are replayed in
order on link restore. Pure logic + filesystem; not coupled to MemoryStore (per
/plan-eng-review finding #5 — keep concerns separate so Wave 2's link-state
monitor and Lane B's counter durability evolve independently).

Persistence format: one JSON object per line (JSONL), each shaped as
    {"channel": <str>, "payload": <dict>, "ts_iso": <str>}

Overflow behavior: deque(maxlen=N) drops the OLDEST entry. In a standalone
window long enough to overflow (1000 findings × 1/min ≈ 16+ minutes), early
findings are lost. This is documented intentionally — the alternative
(unbounded growth) is worse for memory and process-restart recovery time.
The storyboard footnote calls this out (handled by Wave 3b).
"""
from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class FindingBuffer:
    """FIFO ring buffer for findings produced while standalone, with JSONL persistence.

    Append → in-memory deque AND one JSON line on disk.
    Drain → return all entries in FIFO order, clear the deque, truncate the file.
    Restore → on (re)start, read the JSONL back into the deque so a process
        crash does not lose buffered findings.
    """

    def __init__(self, persist_path: Path, maxlen: int = 1000):
        self._persist_path = Path(persist_path)
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        self._maxlen = maxlen
        # NOTE: deque(maxlen=N) drops the OLDEST entry on overflow. See module
        # docstring for the implication on multi-hour standalone windows.
        self._deque: deque[tuple[str, dict, str]] = deque(maxlen=maxlen)

    def append(self, channel: str, payload: dict) -> None:
        """Append to the in-memory deque AND persist one JSON line.

        At maxlen, the oldest in-memory entry is dropped (deque behavior).
        The on-disk JSONL is append-only between drains, which can therefore
        contain MORE lines than the deque holds during the same standalone
        window. The next drain truncates the file, so this drift is bounded
        to a single window. The drain replays only the in-memory deque, so
        the dropped-oldest semantics are preserved end-to-end.
        """
        ts_iso = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        )
        self._deque.append((channel, payload, ts_iso))
        line = json.dumps({"channel": channel, "payload": payload, "ts_iso": ts_iso})
        with self._persist_path.open("a") as f:
            f.write(line + "\n")

    def drain(self) -> list[tuple[str, dict]]:
        """Return all entries in FIFO order. Clear the deque AND truncate the file.

        Atomicity: the in-memory clear and file truncate happen in this method
        only. A crash mid-drain (after some entries have been replayed by the
        caller but before truncate) will replay the same JSONL on next start;
        EGS dedup (Component 4) is the safety net for that race.
        """
        entries = [(channel, payload) for (channel, payload, _ts) in self._deque]
        self._deque.clear()
        # Truncate by writing empty content. open("w") truncates atomically
        # on POSIX (single syscall to O_TRUNC).
        self._persist_path.write_text("")
        return entries

    def __len__(self) -> int:
        return len(self._deque)

    def restore_from_disk(self) -> int:
        """Read persist_path and rehydrate the deque.

        Returns the number of entries restored. Idempotent: missing file or
        empty file → returns 0 with no side effects on the deque. Corrupted
        lines are skipped with a warning so a single bad write doesn't take
        out the entire buffer.
        """
        if not self._persist_path.exists():
            return 0
        text = self._persist_path.read_text()
        if not text.strip():
            return 0
        restored = 0
        for lineno, raw in enumerate(text.splitlines(), start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
                channel = obj["channel"]
                payload = obj["payload"]
                ts_iso = obj.get("ts_iso", "")
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.warning(
                    "FindingBuffer.restore: skipping corrupted line %d in %s: %s",
                    lineno,
                    self._persist_path,
                    e,
                )
                continue
            self._deque.append((channel, payload, ts_iso))
            restored += 1
        return restored
