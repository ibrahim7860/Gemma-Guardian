"""LinkStateMonitor — event-driven standalone detection for the drone agent.

Beat 5 Path A-full Component 2 (Wave 2 Lane E). Pure logic, clock-injectable
for tests. Consumes `mesh.link_status` events (filtered by drone_id by the
LinkStatusSubscriber) and exposes a single `is_standalone()` predicate the
runtime consults to drive `BufferedPublisher.set_standalone(...)` and to
write `agent_status` into the republished drone state.

Design rationale:
  - Defensive default: a fresh monitor reports `is_standalone() == True`
    until it has seen at least one `link="up"` event. This is the
    correctness-preserving choice — if the mesh sim is silent for any
    reason, the drone behaves as if it were standalone (buffers findings
    rather than fire-and-forget) and the buffer drains the moment the
    first `up` event arrives. The opposite default (assume active) would
    silently lose findings during a startup race.
  - Staleness fallback: if the most recent event is older than
    `staleness_threshold_s` (default 10.0 s), fall back to standalone.
    Lane D publishes `mesh.link_status` heartbeats at 1 Hz, so a 10 s
    threshold means ~10 missed heartbeats before the drone defensively
    assumes the mesh sim has crashed. The threshold is a tuneable knob;
    keep it loose enough to absorb a Redis hiccup but tight enough that
    the operator notices the dashboard banner within ~10 s of an actual
    mesh-sim crash.
  - Clock injection: tests fast-forward synthetic time via `now_fn`
    instead of `time.sleep(11)`. Production callers omit `now_fn` and
    get `time.monotonic` by default.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class LinkStateMonitor:
    """Event-driven standalone detection with staleness fallback.

    Primary signal: `note_event(link)` calls (link in {"up", "down"}).
    Fallback: stale beyond `staleness_threshold_s` → assume standalone.
    """

    def __init__(
        self,
        drone_id: str,
        staleness_threshold_s: float = 10.0,
        now_fn: Optional[Callable[[], float]] = None,
    ):
        self._drone_id = drone_id
        self._staleness_threshold_s = staleness_threshold_s
        self._now_fn = now_fn if now_fn is not None else time.monotonic
        # None until the first valid event arrives. Defensive default
        # below treats "no event yet" as standalone.
        self._last_link: Optional[str] = None
        self._last_event_ts: Optional[float] = None

    def note_event(self, link: str) -> None:
        """Record a link transition. `link` must be 'up' or 'down'.

        Invalid values are logged and ignored — the subscriber that calls
        this is the contract-validation layer, but defense-in-depth keeps
        the monitor honest in case it's wired up by other callers.
        """
        if link not in ("up", "down"):
            logger.warning(
                "LinkStateMonitor[%s]: ignoring invalid link value %r",
                self._drone_id,
                link,
            )
            return
        self._last_link = link
        self._last_event_ts = self._now_fn()

    def is_standalone(self) -> bool:
        """True if standalone, False if active.

        Standalone iff:
          - No event has ever arrived (defensive default), OR
          - The last event was 'down', OR
          - The last event is older than `staleness_threshold_s`.
        """
        if self._last_link is None or self._last_event_ts is None:
            return True
        if self._last_link == "down":
            return True
        # last_link == "up" — check staleness
        age = self._now_fn() - self._last_event_ts
        if age > self._staleness_threshold_s:
            return True
        return False
