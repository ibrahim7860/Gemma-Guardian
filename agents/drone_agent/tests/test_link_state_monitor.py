"""Unit tests for LinkStateMonitor (Beat 5 Component 2 / Wave 2 Lane E).

Pure logic — no Redis, no asyncio. Clock is injected via `now_fn` so the
staleness fallback can be exercised without real-time waits.
"""
from __future__ import annotations

from agents.drone_agent.link_state_monitor import LinkStateMonitor


class _FakeClock:
    """Monotonic-ish clock controlled by tests."""

    def __init__(self, t0: float = 1000.0):
        self._t = t0

    def now(self) -> float:
        return self._t

    def advance(self, dt: float) -> None:
        self._t += dt


def test_initially_standalone_until_first_event():
    """A fresh monitor reports standalone (defensive default) until a 'up'
    event arrives. The opposite default would silently lose findings during
    a startup race with the mesh sim.
    """
    clock = _FakeClock()
    monitor = LinkStateMonitor("drone1", now_fn=clock.now)
    assert monitor.is_standalone() is True


def test_active_after_link_up_event():
    clock = _FakeClock()
    monitor = LinkStateMonitor("drone1", now_fn=clock.now)
    monitor.note_event("up")
    assert monitor.is_standalone() is False


def test_standalone_after_link_down_event():
    """After 'up' then 'down', monitor must report standalone again."""
    clock = _FakeClock()
    monitor = LinkStateMonitor("drone1", now_fn=clock.now)
    monitor.note_event("up")
    assert monitor.is_standalone() is False
    monitor.note_event("down")
    assert monitor.is_standalone() is True


def test_staleness_fallback_after_threshold():
    """If no event arrives for longer than staleness_threshold_s, the
    monitor falls back to standalone even if the last event was 'up'.
    Critical: this is the defense against a mid-emit mesh-sim crash.
    """
    clock = _FakeClock()
    monitor = LinkStateMonitor(
        "drone1", staleness_threshold_s=10.0, now_fn=clock.now,
    )
    monitor.note_event("up")
    assert monitor.is_standalone() is False
    # Just under threshold — still active.
    clock.advance(9.5)
    assert monitor.is_standalone() is False
    # Past threshold — fallback engages.
    clock.advance(1.0)  # total elapsed: 10.5s
    assert monitor.is_standalone() is True


def test_invalid_link_value_ignored():
    """note_event with an invalid string (anything other than 'up'/'down')
    must be ignored — not crash and not corrupt state. Defense-in-depth
    in case a non-subscriber caller wires this up.
    """
    clock = _FakeClock()
    monitor = LinkStateMonitor("drone1", now_fn=clock.now)
    monitor.note_event("up")
    assert monitor.is_standalone() is False
    # Garbage value: ignored, state unchanged.
    monitor.note_event("flapping")
    assert monitor.is_standalone() is False
    monitor.note_event("")
    assert monitor.is_standalone() is False


def test_missed_event_recovery():
    """REGRESSION: ensures the staleness fallback engages when the mesh sim
    crashes mid-emit. After a single 'up' event, no further events arrive;
    after the threshold elapses the monitor must report standalone again
    so the BufferedPublisher starts buffering rather than firing into the
    void.
    """
    clock = _FakeClock()
    monitor = LinkStateMonitor(
        "drone1", staleness_threshold_s=10.0, now_fn=clock.now,
    )
    monitor.note_event("up")
    assert monitor.is_standalone() is False
    # Mesh sim "crashes" — no more events. 11 s elapse.
    clock.advance(11.0)
    assert monitor.is_standalone() is True
    # If the mesh sim recovers and emits another 'up', monitor returns to
    # active immediately.
    monitor.note_event("up")
    assert monitor.is_standalone() is False
