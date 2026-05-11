"""Pure in-memory aggregator for the Phase 2 WebSocket bridge.

Holds three buckets that together compose the `state_update` envelope from
Contract 8 of `docs/20-integration-contracts.md`:

- ``_egs``: latest payload from the ``egs.state`` channel. Seeded from the
  `egs_state` block of a known-good `state_update` fixture so that `snapshot()`
  remains schema-valid even before the EGS coordinator publishes anything.
- ``_drones``: ``drone_id -> latest drone_state payload``. New drone_ids are
  appended; subsequent updates for the same id replace in place.
- ``_findings``: ``OrderedDict[finding_id -> finding payload]`` capped at
  ``max_findings``. Insertion order is the dashboard's display order. Re-adding
  an existing ``finding_id`` replaces the value in place WITHOUT moving it to
  the end (so an upgraded severity does not jump to the top of the list).
  When inserting a new finding while at the cap, the oldest entry is evicted
  via ``popitem(last=False)`` (FIFO).

This module is pure logic — no I/O, no asyncio. The Redis subscriber writes
into it and the emit loop reads from it; concurrency is owned by the caller
(currently a single asyncio.Lock in `main.py`).
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from typing import Any, Dict

from shared.contracts import VERSION


class StateAggregator:
    """Three-bucket aggregator for `state_update` envelopes.

    Buckets:
      * ``_egs`` — latest ``egs_state`` payload (seeded from ``seed_envelope``).
      * ``_drones`` — ``Dict[drone_id, drone_state]``, latest wins.
      * ``_findings`` — ``OrderedDict[finding_id, finding]``, FIFO-capped at
        ``max_findings``. Duplicate ``finding_id`` replaces in place (preserves
        position).

    Lifecycle: ``__init__`` seeds the egs bucket and stashes a fresh copy of
    the seed envelope so ``snapshot()`` always returns a schema-valid scaffold.
    Subsequent ``update_*`` / ``add_finding`` calls mutate the buckets;
    ``snapshot(timestamp_iso=...)`` produces a new envelope dict per emit tick.
    """

    def __init__(self, *, max_findings: int, seed_envelope: Dict[str, Any]) -> None:
        self._max_findings: int = max_findings
        # Deep-copy the seed so external mutation of the caller's dict cannot
        # corrupt our scaffold or initial egs payload.
        self._seed: Dict[str, Any] = deepcopy(seed_envelope)
        self._egs: Dict[str, Any] = deepcopy(seed_envelope["egs_state"])
        self._drones: Dict[str, Dict[str, Any]] = {}
        self._findings: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()

    # ---- writers -----------------------------------------------------------

    def update_egs_state(self, payload: Dict[str, Any]) -> None:
        """Replace the egs bucket with a deep copy of ``payload``."""
        self._egs = deepcopy(payload)

    def update_drone_state(self, drone_id: str, payload: Dict[str, Any]) -> None:
        """Insert or replace the per-drone bucket entry with a deep copy."""
        self._drones[drone_id] = deepcopy(payload)

    def add_finding(self, payload: Dict[str, Any]) -> None:
        """Append or in-place-replace a finding by ``finding_id``.

        Cap behavior: when inserting a new finding while at ``max_findings``,
        the oldest entry is evicted via ``popitem(last=False)`` before insert.
        """
        finding_id = payload["finding_id"]
        if finding_id in self._findings:
            # Dict assignment to an existing key preserves OrderedDict position.
            # See https://docs.python.org/3.9/library/collections.html#ordereddict-objects
            self._findings[finding_id] = deepcopy(payload)
            return
        if len(self._findings) >= self._max_findings:
            self._findings.popitem(last=False)
        self._findings[finding_id] = deepcopy(payload)

    # ---- reader ------------------------------------------------------------

    def has_finding(self, finding_id: str) -> bool:
        """Return True iff the aggregator currently holds a finding with this id.

        Used by the bridge's finding_approval allowlist guard (Phase 4) to
        reject inbound approvals for unknown or aged-out finding_ids before
        republishing them onto egs.operator_actions. The check is O(1) on the
        OrderedDict.
        """
        return finding_id in self._findings

    def snapshot(self, *, timestamp_iso: str) -> Dict[str, Any]:
        """Return a fresh ``state_update`` envelope reflecting current buckets.

        ``timestamp_iso`` is stamped onto the envelope and onto the embedded
        ``egs_state.timestamp``. ``contract_version`` is set to the locked
        floor from ``shared.contracts.VERSION``; ``main.py``'s emit loop
        overwrites this on the way out so the value travels through one source
        of truth at runtime — seeding it here keeps the aggregator output
        schema-valid in isolation (regression-tested in ``test_aggregator``).

        LDD-2 (2026-05-11 finding-approval plan): joins Qasim's PR #45 field
        ``egs_state.approved_findings`` (a ``{finding_id: "approved"|
        "dismissed"}`` map) against the active_findings bucket. Findings whose
        id appears in the map with value ``"approved"`` get
        ``approved: True`` + ``operator_status: "approved"`` stamped on the
        output dict; with value ``"dismissed"`` get ``approved: False`` +
        ``operator_status: "dismissed"``. Findings absent from the map (or
        when the entire field is missing/None, which is schema-valid because
        the field is OPTIONAL) pass through untouched — ``operator_status``
        stays at whatever the drone published, typically ``"pending"``. The
        mutation applies only to the deep-copied output; ``self._findings``
        is never touched.

        Returned dict is independent: caller mutation does not affect internal
        buckets.
        """
        egs_copy = deepcopy(self._egs)
        egs_copy["timestamp"] = timestamp_iso
        approved_map = egs_copy.get("approved_findings") or {}
        active_findings = []
        for v in self._findings.values():
            f = deepcopy(v)
            status = approved_map.get(f.get("finding_id"))
            if status == "approved":
                f["approved"] = True
                f["operator_status"] = "approved"
            elif status == "dismissed":
                f["approved"] = False
                f["operator_status"] = "dismissed"
            active_findings.append(f)
        return {
            "type": "state_update",
            "timestamp": timestamp_iso,
            "contract_version": VERSION,
            "egs_state": egs_copy,
            "active_findings": active_findings,
            "active_drones": [deepcopy(v) for v in self._drones.values()],
        }
