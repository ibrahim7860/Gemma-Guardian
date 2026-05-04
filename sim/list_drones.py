"""Tiny CLI helper: print a scenario's drone roster as comma-separated ids.

Used by ``scripts/launch_swarm.sh`` to derive ``--drones=auto`` rather than
parsing YAML in bash. Resolves a scenario the same way ``waypoint_runner.py``
does — accepts either a path or a scenario_id under ``sim/scenarios/``.

Output (stdout): a single line, e.g. ``drone1,drone2,drone3``. No trailing
newline by design — bash captures it verbatim into a variable.

Usage:
    python3 sim/list_drones.py disaster_zone_v1
    python3 sim/list_drones.py sim/scenarios/single_drone_smoke.yaml
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sim.scenario import load_scenario


def _resolve_scenario_path(arg: str) -> Path:
    p = Path(arg)
    if p.exists():
        return p
    candidate = _PROJECT_ROOT / "sim" / "scenarios" / f"{arg}.yaml"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"scenario not found: {arg!r} (also looked at {candidate})")


def list_drone_ids(scenario_arg: str) -> list[str]:
    scenario = load_scenario(_resolve_scenario_path(scenario_arg))
    return [d.drone_id for d in scenario.drones]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if len(args) != 1:
        print("usage: python3 sim/list_drones.py <scenario>", file=sys.stderr)
        return 2
    try:
        ids = list_drone_ids(args[0])
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 1
    sys.stdout.write(",".join(ids))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
