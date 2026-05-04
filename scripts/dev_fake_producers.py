"""Dev-only Redis fake-producer for the Phase 2 WebSocket bridge.

This script is scaffolding so Ibrahim (Frontend + Demo) can develop and
Playwright-test the WS bridge before Hazim (sim) and Qasim (EGS) ship
their real producers. It connects to Redis and emits contract-valid messages
on the channels the bridge subscribes to:

    egs.state                       (every 2s, schema: egs_state)
    drones.<drone_id>.state         (every 1s, schema: drone_state)
    drones.<drone_id>.findings      (every 8s, schema: finding)

WARNING: This is dev-only scaffolding, not production code. It hardcodes
fixture-derived payloads, has no real disaster logic, and must not be wired
into the demo pipeline. In real runs, sim/waypoint_runner.py and the EGS
coordinator replace this script entirely. Channel and schema bindings come
from shared.contracts.topics and shared.contracts.validate; do not hardcode
channel strings or payload shapes.

drone_id default note (deviation from spec):
    The Phase 2 design spec proposed `dev_drone1` as the default to avoid
    collision with Hazim's `drone1`. However the locked v1 contract
    schema (`shared/schemas/_common.json`) requires drone_id to match
    `^drone\\d+$`, which excludes any `dev_` prefix. To keep the script's
    output schema-valid by default while still avoiding collision with
    Hazim's `drone1`/`drone2`/`drone3` IDs, the default is `drone99`.
    Override with --drone-id at the CLI if you need a specific value (e.g.
    matching a Playwright test fixture).

Usage:
    python scripts/dev_fake_producers.py
    python scripts/dev_fake_producers.py --drone-id drone98 --tick-s 0.5
    python scripts/dev_fake_producers.py --redis-url redis://localhost:6379
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import redis

# When invoked as `python scripts/dev_fake_producers.py` (not `python -m`),
# the project root is not on sys.path, so the `shared` package import
# would fail. Adding the project root explicitly keeps both invocations
# working.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from shared.contracts import validate  # noqa: E402  (post-sys.path)
from shared.contracts.topics import (  # noqa: E402
    EGS_STATE,
    per_drone_findings_channel,
    per_drone_state_channel,
)


# Locked discrimination of finding types per the contract enum. The script
# rotates through this list deterministically so test assertions can predict
# what comes next.
_FINDING_TYPE_ROTATION: List[str] = [
    "victim",
    "fire",
    "smoke",
    "damaged_structure",
    "blocked_route",
]


# Allowed tokens for --emit. Each value enables one channel family. Default
# (all three) keeps backwards compatibility with existing dev workflows
# that did not pass --emit.
_EMIT_CHANNEL_TOKENS: List[str] = ["state", "egs", "findings"]


# Default schema-valid drone_id for the dev producer. See module docstring
# for the rationale (regex constraint vs. avoiding Hazim collision).
_DEFAULT_DRONE_ID: str = "drone99"


_FIXTURES_ROOT: Path = (
    Path(__file__).resolve().parent.parent
    / "shared" / "schemas" / "fixtures" / "valid"
)


# Drone ids must match ^drone\d+$ per the v1 contract. We validate the CLI
# argument up front to fail fast with a clear error rather than wait for the
# first publish-time validation failure.
_DRONE_ID_PATTERN: re.Pattern = re.compile(r"^drone\d+$")


def _load_fixture(name: str, filename: str) -> Dict[str, Any]:
    """Load a valid fixture JSON file as the seed template for a payload type."""
    path = _FIXTURES_ROOT / name / filename
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)  # type: ignore[no-any-return]


def _now_iso_ms() -> str:
    """Return the current UTC time as an ISO-8601 string with ms precision.

    Format matches `_common.json#/$defs/iso_timestamp_utc_ms`:
    `^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$`.
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _build_drone_state(drone_id: str, tick: int) -> Dict[str, Any]:
    """Build a drone_state payload for the given drone_id and tick.

    Battery decreases by 1% every 10 ticks, floored at 5% so the producer
    never emits a value the dashboard interprets as a critical-failure
    fixture. Position is static (the dashboard's map panel does not yet
    require movement); heading is fixed.
    """
    template = _load_fixture("drone_state", "01_active.json")
    payload: Dict[str, Any] = deepcopy(template)
    payload["drone_id"] = drone_id
    payload["timestamp"] = _now_iso_ms()
    # Battery: start at 95, drop 1% every 10 ticks, floor 5.
    payload["battery_pct"] = max(5, 95 - (tick // 10))
    # Drop fixture-bound optional/contextual fields that don't apply to a
    # placeholder dev producer; keep only what's required + cleanly scoped.
    payload["last_action"] = "report_finding"
    payload["last_action_timestamp"] = _now_iso_ms()
    payload["assigned_survey_points_remaining"] = max(0, 12 - (tick // 4))
    payload["findings_count"] = tick // 8
    payload["in_mesh_range_of"] = ["egs"]
    return payload


def _build_egs_state(tick: int) -> Dict[str, Any]:
    """Build an egs_state payload with stable mission_id and fresh timestamp."""
    template = _load_fixture("egs_state", "01_active.json")
    payload: Dict[str, Any] = deepcopy(template)
    payload["mission_id"] = "dev_mission"
    payload["timestamp"] = _now_iso_ms()
    return payload


def _build_finding(drone_id: str, counter: int) -> Dict[str, Any]:
    """Build a finding payload with rotating type and unique finding_id.

    `finding_id` format `f_<drone_id>_<counter>` — counter is monotonic per
    script run. Because the contract regex is `^f_drone\\d+_\\d+$`, the
    drone_id portion must itself match `^drone\\d+$`; we rely on
    `_DRONE_ID_PATTERN` validation at CLI parse time to keep that invariant.
    """
    template = _load_fixture("finding", "01_victim.json")
    payload: Dict[str, Any] = deepcopy(template)
    finding_type = _FINDING_TYPE_ROTATION[counter % len(_FINDING_TYPE_ROTATION)]
    payload["finding_id"] = f"f_{drone_id}_{counter}"
    payload["source_drone_id"] = drone_id
    payload["timestamp"] = _now_iso_ms()
    payload["type"] = finding_type
    payload["validated"] = True
    payload["validation_retries"] = 0
    payload["operator_status"] = "pending"
    return payload


def _validate_or_die(schema_name: str, payload: Dict[str, Any]) -> None:
    """Validate `payload` against `schema_name`, exit non-zero on failure.

    Per the spec: a fixture-derived payload that fails validation is a real
    bug worth surfacing. Print errors and exit with code 2 so callers (and
    CI) see the failure immediately rather than streaming garbage to Redis.
    """
    outcome = validate(schema_name, payload)
    if not outcome.valid:
        print(
            f"[fake_producer] FATAL: generated {schema_name} payload failed "
            f"validation. errors={outcome.errors}",
            file=sys.stderr,
        )
        sys.exit(2)


def _parse_emit_csv(value: str) -> List[str]:
    """argparse type-converter for --emit. Splits on comma, strips whitespace,
    and rejects unknown tokens with argparse.ArgumentTypeError so the parser
    exits with a clear message instead of failing later at publish time."""
    tokens = [t.strip() for t in value.split(",") if t.strip()]
    if not tokens:
        raise argparse.ArgumentTypeError(
            "--emit must contain at least one of: "
            f"{','.join(_EMIT_CHANNEL_TOKENS)}"
        )
    bad = [t for t in tokens if t not in _EMIT_CHANNEL_TOKENS]
    if bad:
        raise argparse.ArgumentTypeError(
            f"--emit got unknown token(s): {bad}. "
            f"Valid tokens: {_EMIT_CHANNEL_TOKENS}"
        )
    return tokens


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Dev-only Redis fake-producer for the Phase 2 WS bridge. "
            "Emits contract-valid egs.state, drones.<id>.state, and "
            "drones.<id>.findings messages so Ibrahim can develop and "
            "Playwright-test the dashboard before Hazim and Qasim ship "
            "their real producers. NOT for production use."
        ),
    )
    parser.add_argument(
        "--redis-url",
        default="redis://localhost:6379",
        help="Redis connection URL (default: redis://localhost:6379).",
    )
    parser.add_argument(
        "--drone-id",
        default=_DEFAULT_DRONE_ID,
        help=(
            "drone_id for the synthetic drone. Must match ^drone\\d+$ per "
            f"the v1 contract. Default {_DEFAULT_DRONE_ID!r} avoids "
            "collision with Hazim's drone1/drone2/drone3."
        ),
    )
    parser.add_argument(
        "--tick-s",
        type=float,
        default=1.0,
        help=(
            "Seconds between ticks (default: 1.0). Drone state publishes "
            "every tick; egs.state every 2 ticks; finding every 8 ticks."
        ),
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help=(
            "Skip pre-publish schema validation. Default is to validate "
            "every payload and exit non-zero on failure."
        ),
    )
    parser.add_argument(
        "--emit",
        type=_parse_emit_csv,
        default=list(_EMIT_CHANNEL_TOKENS),
        help=(
            "Comma-separated subset of channel families to emit. "
            "Tokens: state (drones.<id>.state, every tick), "
            "egs (egs.state, every 2 ticks), "
            "findings (drones.<id>.findings, every 8 ticks). "
            "Default: all three. Hybrid demo mode runs one --emit=state "
            "instance disabled (sim owns it) and one --emit=egs,findings "
            "instance enabled until Qasim/Kaleel ship real producers."
        ),
    )
    return parser.parse_args(argv)


def _publish(
    client: "redis.Redis[Any]",
    channel: str,
    payload: Dict[str, Any],
) -> None:
    """Publish a JSON-encoded payload on a Redis pub/sub channel."""
    client.publish(channel, json.dumps(payload))


def _run(args: argparse.Namespace) -> int:
    if not _DRONE_ID_PATTERN.match(args.drone_id):
        print(
            f"[fake_producer] FATAL: --drone-id={args.drone_id!r} does not "
            f"match the v1 contract pattern ^drone\\d+$.",
            file=sys.stderr,
        )
        return 2

    validate_payloads: bool = not args.no_validate
    drone_id: str = args.drone_id
    tick_s: float = args.tick_s

    client: "redis.Redis[Any]" = redis.Redis.from_url(args.redis_url)

    print(
        f"[fake_producer] starting redis_url={args.redis_url} "
        f"drone_id={drone_id} tick_s={tick_s} validate={validate_payloads}"
    )

    drone_state_channel: str = per_drone_state_channel(drone_id)
    finding_channel: str = per_drone_findings_channel(drone_id)

    tick: int = 0
    finding_counter: int = 0

    try:
        while True:
            # Drone state: every tick.
            ds_payload = _build_drone_state(drone_id, tick)
            if validate_payloads:
                _validate_or_die("drone_state", ds_payload)
            _publish(client, drone_state_channel, ds_payload)
            print(
                f"[fake_producer] tick={tick} channel={drone_state_channel} "
                f"battery={ds_payload['battery_pct']}"
            )

            # EGS state: every 2 ticks.
            if tick % 2 == 0:
                egs_payload = _build_egs_state(tick)
                if validate_payloads:
                    _validate_or_die("egs_state", egs_payload)
                _publish(client, EGS_STATE, egs_payload)
                print(
                    f"[fake_producer] tick={tick} channel={EGS_STATE} "
                    f"mission_id={egs_payload['mission_id']}"
                )

            # Finding: every 8 ticks.
            if tick % 8 == 0:
                finding_payload = _build_finding(drone_id, finding_counter)
                if validate_payloads:
                    _validate_or_die("finding", finding_payload)
                _publish(client, finding_channel, finding_payload)
                print(
                    f"[fake_producer] tick={tick} channel={finding_channel} "
                    f"finding_id={finding_payload['finding_id']} "
                    f"type={finding_payload['type']}"
                )
                finding_counter += 1

            tick += 1
            time.sleep(tick_s)
    except KeyboardInterrupt:
        print("[fake_producer] shutting down")
        return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
