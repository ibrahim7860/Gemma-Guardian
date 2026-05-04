"""Waypoint-driven drone state publisher.

Reads a scenario YAML, interpolates each drone along its waypoint track at the
configured speed, and publishes a contract-conformant ``drone_state`` message
on Redis channel ``drones.<id>.state`` at 2 Hz.

Per Contract 2 (docs/20-integration-contracts.md), the sim owns *kinematic*
fields; Person 2's drone_agent overwrites the agent-state fields on the same
channel as a merged record. To stay schema-valid in the meantime, this runner
emits safe defaults for those fields:

    current_task=null, last_action="none", last_action_timestamp=null,
    validation_failures_total=0, findings_count=0, in_mesh_range_of=[],
    agent_status="active"

Scripted events fire when the simulation clock crosses ``event.t`` seconds.
``drone_failure`` flips the affected drone's ``agent_status`` to ``"offline"``
and freezes its position. ``mission_complete`` is informational; the runner
keeps publishing held-position state until the process is killed.

Designed to be deterministic under test: the public interface is
``WaypointRunner.tick(t_seconds)``. Tests drive it with discrete time values
and inspect what landed on fakeredis. The CLI ``main()`` loops with a real
wall-clock at the configured tick rate.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

# Add project root to sys.path so this works whether invoked as
# `python sim/waypoint_runner.py` or `python -m sim.waypoint_runner`.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import redis

from shared.contracts.config import CONFIG
from shared.contracts.topics import per_drone_state_channel
from sim.geo import haversine_meters, interpolate
from sim.scenario import Drone, Scenario, ScriptedEvent, load_scenario


def _now_iso_ms() -> str:
    """ISO-8601 UTC timestamp with millisecond precision per _common.json."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _bearing_deg(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    """Initial-bearing in degrees from p1 to p2 (lat, lon)."""
    lat1, lon1 = math.radians(p1[0]), math.radians(p1[1])
    lat2, lon2 = math.radians(p2[0]), math.radians(p2[1])
    dlon = lon2 - lon1
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


@dataclass
class _DroneState:
    drone: Drone
    position: tuple[float, float, float]
    battery_pct: float
    heading_deg: float = 0.0
    failed: bool = False
    # Index of the *next* waypoint we're heading toward. When at end, equals len(waypoints).
    next_idx: int = 0
    # Previous (lat, lon, alt) for velocity computation between ticks.
    prev_position: tuple[float, float, float] = field(default=(0.0, 0.0, 0.0))
    last_t: float = 0.0


class WaypointRunner:
    """Pure-logic drone position/state publisher. CLI-driven loop wraps it.

    Parameters
    ----------
    scenario:
        Parsed Scenario model.
    redis_client:
        Synchronous redis-py client. fakeredis works for tests.
    battery_drain_pct_per_sec:
        Linear decay rate for battery_pct (default 0.1%/s — gentle for the
        ~5-minute demo runs).
    """

    def __init__(
        self,
        scenario: Scenario,
        redis_client: redis.Redis,
        *,
        battery_drain_pct_per_sec: float = 0.1,
    ) -> None:
        self.scenario = scenario
        self.redis = redis_client
        self.battery_drain = battery_drain_pct_per_sec
        self._fired_events: set[int] = set()  # by id(event)
        self._drones: dict[str, _DroneState] = {}
        for d in scenario.drones:
            home = (d.home.lat, d.home.lon, d.home.alt)
            self._drones[d.drone_id] = _DroneState(
                drone=d,
                position=home,
                prev_position=home,
                battery_pct=100.0,
                heading_deg=self._initial_heading(d),
                next_idx=0,
            )

    @staticmethod
    def _initial_heading(d: Drone) -> float:
        if not d.waypoints:
            return 0.0
        first = d.waypoints[0]
        return _bearing_deg((d.home.lat, d.home.lon), (first.lat, first.lon))

    def _advance_drone(self, ds: _DroneState, t_seconds: float) -> None:
        if ds.failed:
            return
        # Walk along the polyline home → wp[0] → wp[1] → ... at speed_mps.
        # We compute target position from cumulative arc length at this time.
        speed = ds.drone.speed_mps
        total_traveled_m = max(0.0, speed * t_seconds)

        track: list[tuple[float, float, float]] = [
            (ds.drone.home.lat, ds.drone.home.lon, ds.drone.home.alt)
        ]
        track.extend((w.lat, w.lon, w.alt) for w in ds.drone.waypoints)

        # Find which segment we're on.
        accumulated = 0.0
        new_pos = track[-1]
        new_next_idx = len(ds.drone.waypoints)  # past end → hold at last
        for i in range(len(track) - 1):
            a = track[i]
            b = track[i + 1]
            seg_len = haversine_meters((a[0], a[1]), (b[0], b[1]))
            if total_traveled_m <= accumulated + seg_len:
                frac = (total_traveled_m - accumulated) / seg_len if seg_len > 0 else 0.0
                new_pos = interpolate(a, b, frac)
                new_next_idx = i  # waypoint index we're heading toward (0 = first wp)
                ds.heading_deg = _bearing_deg((a[0], a[1]), (b[0], b[1]))
                break
            accumulated += seg_len

        ds.prev_position = ds.position
        ds.position = new_pos
        ds.next_idx = new_next_idx
        # Battery drain (clamped at 0).
        ds.battery_pct = max(0.0, 100.0 - self.battery_drain * t_seconds)

    def _apply_scripted_events(self, t_seconds: float) -> None:
        for event in self.scenario.scripted_events:
            key = id(event)
            if key in self._fired_events:
                continue
            if t_seconds + 1e-9 < event.t:
                continue
            self._fire(event)
            self._fired_events.add(key)

    def _fire(self, event: ScriptedEvent) -> None:
        if event.type == "drone_failure" and event.drone_id in self._drones:
            self._drones[event.drone_id].failed = True
        # zone_update / fire_spread / egs_link_drop / egs_link_restore /
        # mission_complete are observational for the sim — they don't change
        # kinematics. Mesh sim and EGS handle the operational consequences.

    def _build_state_message(self, ds: _DroneState, t_seconds: float) -> dict:
        d = ds.drone
        # Velocity from delta-position over delta-time. First tick: zero.
        dt = max(1e-6, t_seconds - ds.last_t)
        if t_seconds <= 0:
            vx = vy = vz = 0.0
        else:
            # Approximate vx/vy in m/s via flat-Earth projection.
            from sim.geo import meters_to_lat_degrees, meters_to_lon_degrees  # local to avoid cycle
            dlat_deg = ds.position[0] - ds.prev_position[0]
            dlon_deg = ds.position[1] - ds.prev_position[1]
            # Convert degrees back to meters for velocity reporting.
            mpd_lat = 1.0 / meters_to_lat_degrees(1.0)
            mpd_lon = 1.0 / meters_to_lon_degrees(1.0, ds.position[0])
            vy = (dlat_deg * mpd_lat) / dt  # north positive
            vx = (dlon_deg * mpd_lon) / dt  # east positive
            vz = (ds.position[2] - ds.prev_position[2]) / dt
        ds.last_t = t_seconds

        # Round battery to integer for schema compliance (battery_pct: integer 0–100).
        battery_pct = int(round(ds.battery_pct))

        agent_status = "offline" if ds.failed else "active"
        # current_waypoint_id: id of the waypoint we're heading to, or last one if past end.
        if ds.next_idx >= len(d.waypoints):
            current_waypoint_id = d.waypoints[-1].id if d.waypoints else None
            remaining = 0
        else:
            current_waypoint_id = d.waypoints[ds.next_idx].id
            remaining = len(d.waypoints) - ds.next_idx

        return {
            "drone_id": d.drone_id,
            "timestamp": _now_iso_ms(),
            "position": {"lat": ds.position[0], "lon": ds.position[1], "alt": ds.position[2]},
            "velocity": {"vx": vx, "vy": vy, "vz": vz},
            "battery_pct": battery_pct,
            "heading_deg": ds.heading_deg,
            "current_task": None,
            "current_waypoint_id": current_waypoint_id,
            "assigned_survey_points_remaining": remaining,
            "last_action": "none",
            "last_action_timestamp": None,
            "validation_failures_total": 0,
            "findings_count": 0,
            "in_mesh_range_of": [],
            "agent_status": agent_status,
        }

    def tick(self, *, t_seconds: float) -> None:
        """Advance simulation to ``t_seconds`` and publish all drone states.

        Idempotent for repeated identical t_seconds values (positions are
        recomputed from absolute time, not accumulated). Tests call this
        directly with synthetic times.
        """
        self._apply_scripted_events(t_seconds)
        for ds in self._drones.values():
            self._advance_drone(ds, t_seconds)
            payload = self._build_state_message(ds, t_seconds)
            self.redis.publish(per_drone_state_channel(ds.drone.drone_id), json.dumps(payload))


def _parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sim waypoint runner — publishes drones.<id>.state at 2 Hz.")
    parser.add_argument("--scenario", required=True, help="Scenario YAML path or scenario_id under sim/scenarios/")
    parser.add_argument("--redis-url", default=CONFIG.transport.redis_url)
    parser.add_argument("--tick-hz", type=float, default=2.0)
    parser.add_argument("--battery-drain", type=float, default=0.1, help="Battery %% drain per second")
    return parser.parse_args(list(argv) if argv is not None else None)


def _resolve_scenario_path(arg: str) -> Path:
    p = Path(arg)
    if p.exists():
        return p
    # Try sim/scenarios/<arg>.yaml
    candidate = _PROJECT_ROOT / "sim" / "scenarios" / f"{arg}.yaml"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"scenario not found: {arg!r} (also looked at {candidate})")


def _check_drone_count(scenario: Scenario) -> None:
    """Fail fast if shared/config.yaml's mission.drone_count disagrees with
    the scenario's len(drones). The two are always supposed to match — a
    silent mismatch over- or under-provisions the swarm and confuses every
    downstream component (drone agents, EGS, dashboard).
    """
    expected = CONFIG.mission.drone_count
    actual = len(scenario.drones)
    if expected != actual:
        raise SystemExit(
            f"[waypoint_runner] mission.drone_count={expected} from "
            f"shared/config.yaml disagrees with scenario {scenario.scenario_id!r} "
            f"len(drones)={actual}. Reconcile the two before launching: "
            f"either edit shared/config.yaml or add/remove drones in the scenario YAML."
        )


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = _parse_args(argv)
    scenario = load_scenario(_resolve_scenario_path(args.scenario))
    _check_drone_count(scenario)
    redis_client = redis.Redis.from_url(args.redis_url)
    runner = WaypointRunner(scenario, redis_client, battery_drain_pct_per_sec=args.battery_drain)

    period = 1.0 / args.tick_hz
    print(
        f"[waypoint_runner] scenario={scenario.scenario_id} drones={[d.drone_id for d in scenario.drones]} "
        f"tick_hz={args.tick_hz} redis={args.redis_url}",
        flush=True,
    )
    start = time.monotonic()
    try:
        while True:
            t = time.monotonic() - start
            runner.tick(t_seconds=t)
            # Sleep until next tick boundary.
            next_boundary = start + (math.floor(t / period) + 1) * period
            time.sleep(max(0.0, next_boundary - time.monotonic()))
    except KeyboardInterrupt:
        print("[waypoint_runner] stopped via SIGINT", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
