"""Mesh simulator main loop.

Subscribes to ``drones.*.state`` (psubscribe) to maintain a position cache,
to ``swarm.broadcasts.*`` to forward peer broadcasts to in-range recipients,
to ``drones.*.findings`` to gate-and-republish onto
``drones.<id>.findings.delivered``, and to ``sim.scripted_events`` for
operator-driven egs_link_drop / egs_link_restore overrides.

The findings gate (Wave 2 Lane D) drops a drone's findings when EITHER:
  (a) the drone is geometrically beyond ``egs_link_range_m`` of the EGS, OR
  (b) the drone is in the scripted-override set ``_link_down_overrides``.
Findings still flow byte-identical through the .delivered channel when the
effective link is up.

The mesh sim is also the sole publisher of ``mesh.link_status`` events:
  - on geometric range crossings (per-drone state ingest triggers the check),
  - on scripted egs_link_drop / egs_link_restore events,
  - and as a 1 Hz heartbeat per known drone (liveness signal that lets the
    drone-side LinkStateMonitor's staleness fallback engage if events are
    missed).

It also publishes a JSON adjacency snapshot on ``mesh.adjacency_matrix`` once
per second (configurable). The snapshot is debug-only.

Public surface for tests:
    MeshSimulator(redis, range_m, egs_link_range_m)
    sim.ingest_state(state_dict)
    sim.set_egs_position(lat, lon)
    sim.forward_broadcast(sender_id, raw_bytes)
    sim.forward_finding(sender_id, raw_bytes)
    sim.apply_scripted_event(event_dict)
    sim.emit_link_status(drone_id, link, reason)
    sim.publish_adjacency()
    sim.publish_link_heartbeats()

The CLI entry point ``main()`` wires these methods to redis-py pubsub and
spins a blocking loop.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

# Add project root to sys.path for direct-script invocation.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import redis

from agents.mesh_simulator.range_filter import (
    EGS_NODE_ID,
    filter_recipients,
    in_range_pairs,
    is_drone_in_egs_link_range,
)
from shared.contracts.config import CONFIG
from shared.contracts.logging import now_iso_ms
from shared.contracts.schemas import validate_or_raise
from shared.contracts.topics import (
    MESH_ADJACENCY,
    MESH_LINK_STATUS,
    PER_DRONE_FINDINGS,
    PER_DRONE_STATE,
    SIM_SCRIPTED_EVENTS,
    SWARM_BROADCAST,
    per_drone_findings_delivered_channel,
    swarm_visible_to_channel,
)

# psubscribe patterns derived from the channel templates (single source of truth).
_STATE_PATTERN = PER_DRONE_STATE.replace("{drone_id}", "*")
_BROADCAST_PATTERN = SWARM_BROADCAST.replace("{drone_id}", "*")
_FINDINGS_PATTERN = PER_DRONE_FINDINGS.replace("{drone_id}", "*")

LatLon = Tuple[float, float]


_STATE_CHANNEL_RE = re.compile(r"^drones\.(drone\d+)\.state$")
_BROADCAST_CHANNEL_RE = re.compile(r"^swarm\.broadcasts\.(drone\d+)$")
_FINDINGS_CHANNEL_RE = re.compile(r"^drones\.(drone\d+)\.findings$")


def drone_id_from_state_channel(channel: str) -> Optional[str]:
    m = _STATE_CHANNEL_RE.match(channel)
    return m.group(1) if m else None


def drone_id_from_broadcast_channel(channel: str) -> Optional[str]:
    m = _BROADCAST_CHANNEL_RE.match(channel)
    return m.group(1) if m else None


def drone_id_from_findings_channel(channel: str) -> Optional[str]:
    m = _FINDINGS_CHANNEL_RE.match(channel)
    return m.group(1) if m else None


class MeshSimulator:
    """Distance-gated republisher for swarm broadcasts."""

    def __init__(
        self,
        redis_client: redis.Redis,
        *,
        range_m: float,
        egs_link_range_m: float,
    ) -> None:
        self.redis = redis_client
        self.range_m = range_m
        self.egs_link_range_m = egs_link_range_m
        self._positions: Dict[str, LatLon] = {}
        # Drones force-overridden into "link down" by sim.scripted_events. The
        # effective link state for a drone is `geometric_up AND drone_id NOT IN
        # _link_down_overrides`.
        self._link_down_overrides: set[str] = set()
        # Per-drone effective link state (last value emitted on mesh.link_status,
        # or implicitly "up" until the first transition). Used to detect
        # transitions and to populate heartbeat payloads.
        self._effective_link_up: Dict[str, bool] = {}
        # Per-drone geometric range membership (last computed value). We track
        # this separately so transitions are computed on the *effective* state
        # (geometry AND override), but the geometric component is recomputed
        # incrementally on every position update.
        self._geometric_link_up: Dict[str, bool] = {}
        # Latest scenario tick observed on sim.scripted_events. Used as the `t`
        # field on every emitted mesh.link_status payload. Design choice: there
        # is no other reliable source of scenario tick at the mesh sim — the
        # waypoint runner is the authority. Falls back to 0 until the first
        # scripted event is seen. Any geometric/heartbeat emissions before the
        # first scripted event tag with t=0; this is acceptable because the
        # drone-side monitor keys off (link, reason), not t.
        self._last_scenario_tick: int = 0

    # --- Position cache management -------------------------------------------------

    def ingest_state(self, payload: dict) -> None:
        try:
            drone_id = payload["drone_id"]
            lat = payload["position"]["lat"]
            lon = payload["position"]["lon"]
        except (KeyError, TypeError):
            return  # malformed; drop silently — drones publish at 2 Hz, we'll catch up
        self._positions[drone_id] = (lat, lon)
        # Recompute geometric link state for this drone and emit a transition if
        # the *effective* state flipped. Only meaningful once an EGS position is
        # known.
        self._recompute_geometric_for(drone_id)

    def set_egs_position(self, lat: float, lon: float) -> None:
        self._positions[EGS_NODE_ID] = (lat, lon)
        # An EGS reposition can flip every drone's geometric membership.
        for drone_id in list(self._positions.keys()):
            if drone_id == EGS_NODE_ID:
                continue
            self._recompute_geometric_for(drone_id)

    def known_positions(self) -> Dict[str, LatLon]:
        return dict(self._positions)

    # --- Broadcast forwarding ------------------------------------------------------

    def forward_broadcast(self, sender_id: str, raw_message: bytes) -> int:
        """Forward a raw broadcast payload to every in-range recipient.

        Returns the number of recipients the message was actually published to.
        Drops silently if the sender's position is unknown — we cannot range-gate
        without it.
        """
        sender_pos = self._positions.get(sender_id)
        if sender_pos is None:
            return 0
        recipients = filter_recipients(
            sender_id=sender_id,
            sender_pos=sender_pos,
            drone_positions=self._positions,
            range_m=self.range_m,
        )
        published = 0
        for rid in recipients:
            # EGS node receives via the regular per-drone forwarding too; range
            # gating here uses the wider radius if this is a drone↔EGS pair.
            self.redis.publish(swarm_visible_to_channel(rid), raw_message)
            published += 1
        return published

    # --- Findings gate (Wave 2 Lane D) -------------------------------------------

    def forward_finding(self, sender_id: str, raw_message: bytes) -> int:
        """Gate-and-republish a raw findings payload onto `.delivered`.

        Drops if any of:
          - sender position unknown (cannot range-gate; defensive default),
          - EGS position unknown (cannot compute distance),
          - drone is in the scripted-override set ``_link_down_overrides``,
          - drone is geometrically beyond ``egs_link_range_m`` of the EGS.

        Otherwise publishes the raw bytes verbatim. Returns the receiver count
        from PUBLISH (best effort).
        """
        if sender_id in self._link_down_overrides:
            return 0
        sender_pos = self._positions.get(sender_id)
        if sender_pos is None:
            # Defensive: cannot gate without a position. The drone publishes
            # state at 2 Hz so this is rare in practice.
            return 0
        egs_pos = self._positions.get(EGS_NODE_ID)
        if egs_pos is None:
            return 0
        if not is_drone_in_egs_link_range(
            sender_pos, egs_pos, self.egs_link_range_m,
        ):
            return 0
        channel = per_drone_findings_delivered_channel(sender_id)
        result = self.redis.publish(channel, raw_message)
        try:
            return int(result)
        except (TypeError, ValueError):  # pragma: no cover — defensive
            return 0

    # --- Effective link state + emission -----------------------------------------

    def _compute_effective_up(self, drone_id: str) -> Optional[bool]:
        """Return the effective link state for ``drone_id``, or None if unknown.

        Effective = geometric_up AND drone NOT in _link_down_overrides. Returns
        None when we lack the data to decide (no drone position OR no EGS
        position) — heartbeat / transition logic skips these cases.
        """
        if drone_id == EGS_NODE_ID:
            return None
        sender_pos = self._positions.get(drone_id)
        egs_pos = self._positions.get(EGS_NODE_ID)
        if sender_pos is None or egs_pos is None:
            return None
        geometric_up = is_drone_in_egs_link_range(
            sender_pos, egs_pos, self.egs_link_range_m,
        )
        self._geometric_link_up[drone_id] = geometric_up
        return geometric_up and (drone_id not in self._link_down_overrides)

    def _recompute_geometric_for(self, drone_id: str) -> None:
        """Recompute effective link state for ``drone_id``; emit on transition.

        Reason for emit is "geometric" (caller is the position-update path).
        The override-driven path uses ``apply_scripted_event`` which emits with
        reason="scripted".
        """
        effective = self._compute_effective_up(drone_id)
        if effective is None:
            return
        prior = self._effective_link_up.get(drone_id)
        if prior is None:
            # First definitive observation: record it without emitting a
            # transition (the drone's initial state is treated as the baseline).
            self._effective_link_up[drone_id] = effective
            return
        if prior == effective:
            return
        self._effective_link_up[drone_id] = effective
        self.emit_link_status(
            drone_id,
            "up" if effective else "down",
            reason="geometric",
        )

    def emit_link_status(
        self,
        drone_id: str,
        link: str,
        *,
        reason: str,
    ) -> None:
        """Publish a mesh.link_status event for ``drone_id``.

        ``link`` is "up" or "down"; ``reason`` is "geometric" | "scripted" |
        "heartbeat". Validates against shared/schemas/mesh_link_status.json
        before publish so malformed payloads are caught at the source.
        """
        payload = {
            "drone_id": drone_id,
            "link": link,
            "t": int(self._last_scenario_tick),
            "wall_clock_iso_ms": now_iso_ms(),
            "reason": reason,
        }
        validate_or_raise("mesh_link_status", payload)
        self.redis.publish(MESH_LINK_STATUS, json.dumps(payload))

    def apply_scripted_event(self, event: dict) -> None:
        """Handle a sim.scripted_events payload.

        Recognized types:
          - egs_link_drop <drone_id>: add to override set; emit link=down.
          - egs_link_restore <drone_id>: remove from override set; emit link=up
            (subject to current geometric state).
        Any other type is a no-op. Cache the latest tick for downstream
        emissions.
        """
        event_t = event.get("t")
        if isinstance(event_t, int) and event_t >= 0:
            self._last_scenario_tick = event_t
        etype = event.get("type")
        drone_id = event.get("drone_id")
        if etype not in {"egs_link_drop", "egs_link_restore"}:
            return
        if not isinstance(drone_id, str) or not drone_id:
            return
        prior_effective = self._effective_link_up.get(drone_id)
        if etype == "egs_link_drop":
            self._link_down_overrides.add(drone_id)
        else:  # egs_link_restore
            self._link_down_overrides.discard(drone_id)

        # Recompute effective state *after* updating overrides.
        new_effective = self._compute_effective_up(drone_id)
        if new_effective is None:
            # No EGS / no position: still emit the scripted intent so drones
            # subscribed to mesh.link_status get the override signal. Default
            # the implied state from override membership only.
            implied_up = drone_id not in self._link_down_overrides
            self._effective_link_up[drone_id] = implied_up
            self.emit_link_status(
                drone_id, "up" if implied_up else "down", reason="scripted",
            )
            return

        self._effective_link_up[drone_id] = new_effective
        if prior_effective is None or prior_effective != new_effective:
            self.emit_link_status(
                drone_id, "up" if new_effective else "down", reason="scripted",
            )

    def publish_link_heartbeats(self) -> None:
        """Emit the current effective link state for every known drone.

        Called once per second from the heartbeat thread. Drones consume
        these to keep their LinkStateMonitor's staleness fallback armed.
        """
        for drone_id in list(self._positions.keys()):
            if drone_id == EGS_NODE_ID:
                continue
            effective = self._compute_effective_up(drone_id)
            if effective is None:
                # Without an EGS position we have no link state to report; if
                # the drone is overridden we still want subscribers to see the
                # forced-down state, so fall back to override-only inference.
                if drone_id in self._link_down_overrides:
                    self._effective_link_up[drone_id] = False
                    self.emit_link_status(drone_id, "down", reason="heartbeat")
                continue
            self._effective_link_up[drone_id] = effective
            self.emit_link_status(
                drone_id,
                "up" if effective else "down",
                reason="heartbeat",
            )

    # --- Adjacency snapshot --------------------------------------------------------

    def adjacency_snapshot(self) -> Dict[str, list]:
        return in_range_pairs(
            self._positions,
            range_m=self.range_m,
            egs_link_range_m=self.egs_link_range_m,
        )

    def publish_adjacency(self) -> None:
        snap = self.adjacency_snapshot()
        self.redis.publish(MESH_ADJACENCY, json.dumps(snap))

    # --- CLI loop ------------------------------------------------------------------

    def run_forever(self, *, adjacency_hz: float = 1.0) -> None:
        """Blocking loop: psubscribe, dispatch, periodically publish adjacency.

        Also runs a 1 Hz link-status heartbeat thread (Wave 2 Lane D). The two
        background threads share a single ``stop`` event so SIGINT cleans both
        up. Heartbeat is fixed at 1 Hz per the plan; we don't expose it on the
        CLI to keep the contract stable.
        """
        pubsub = self.redis.pubsub()
        pubsub.psubscribe(_STATE_PATTERN, _BROADCAST_PATTERN, _FINDINGS_PATTERN)
        pubsub.subscribe(SIM_SCRIPTED_EVENTS)
        # drain initial subscribe acks (3 psubscribe + 1 subscribe)
        for _ in range(4):
            pubsub.get_message(timeout=0.5)

        stop = threading.Event()
        period = 1.0 / adjacency_hz

        def _adjacency_thread():
            while not stop.is_set():
                try:
                    self.publish_adjacency()
                except Exception as e:  # pragma: no cover — defensive
                    print(f"[mesh] adjacency publish failed: {e}", flush=True)
                stop.wait(period)

        def _heartbeat_thread():
            # 1 Hz per plan §4 Component 3 acceptance criteria. Decoupled from
            # adjacency_hz so heartbeat cadence is stable across config tweaks.
            while not stop.is_set():
                try:
                    self.publish_link_heartbeats()
                except Exception as e:  # pragma: no cover — defensive
                    print(f"[mesh] link heartbeat failed: {e}", flush=True)
                stop.wait(1.0)

        t_adj = threading.Thread(target=_adjacency_thread, daemon=True)
        t_hb = threading.Thread(target=_heartbeat_thread, daemon=True)
        t_adj.start()
        t_hb.start()

        try:
            for msg in pubsub.listen():
                msg_type = msg.get("type")
                if msg_type not in ("pmessage", "message"):
                    continue
                channel = msg["channel"].decode() if isinstance(msg["channel"], bytes) else msg["channel"]
                data = msg["data"]
                if channel == SIM_SCRIPTED_EVENTS:
                    try:
                        payload = json.loads(data)
                    except Exception:
                        continue
                    self.apply_scripted_event(payload)
                    continue
                drone_id = drone_id_from_state_channel(channel)
                if drone_id is not None:
                    try:
                        payload = json.loads(data)
                    except Exception:
                        continue
                    self.ingest_state(payload)
                    continue
                drone_id = drone_id_from_broadcast_channel(channel)
                if drone_id is not None:
                    raw = data if isinstance(data, (bytes, bytearray)) else str(data).encode()
                    self.forward_broadcast(drone_id, bytes(raw))
                    continue
                drone_id = drone_id_from_findings_channel(channel)
                if drone_id is not None:
                    raw = data if isinstance(data, (bytes, bytearray)) else str(data).encode()
                    self.forward_finding(drone_id, bytes(raw))
                    continue
        except KeyboardInterrupt:
            print("[mesh_simulator] stopped via SIGINT", flush=True)
        finally:
            stop.set()
            t_adj.join(timeout=2.0)
            t_hb.join(timeout=2.0)
            pubsub.close()


def _parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mesh simulator — Euclidean range dropout for swarm broadcasts.")
    parser.add_argument("--redis-url", default=CONFIG.transport.redis_url)
    parser.add_argument("--range-meters", type=float, default=200.0)
    parser.add_argument("--egs-link-range-meters", type=float, default=500.0)
    parser.add_argument("--egs-lat", type=float, default=None, help="EGS latitude (defaults to omitted = no EGS)")
    parser.add_argument("--egs-lon", type=float, default=None)
    parser.add_argument("--adjacency-hz", type=float, default=1.0)
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = _parse_args(argv)
    redis_client = redis.Redis.from_url(args.redis_url)
    sim = MeshSimulator(
        redis_client,
        range_m=args.range_meters,
        egs_link_range_m=args.egs_link_range_meters,
    )
    if args.egs_lat is not None and args.egs_lon is not None:
        sim.set_egs_position(args.egs_lat, args.egs_lon)
    print(
        f"[mesh_simulator] range_m={args.range_meters} egs_link_range_m={args.egs_link_range_meters} "
        f"redis={args.redis_url}",
        flush=True,
    )
    sim.run_forever(adjacency_hz=args.adjacency_hz)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
