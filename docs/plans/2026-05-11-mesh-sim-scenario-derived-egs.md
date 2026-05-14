# Plan — Mesh sim scenario-derived EGS coordinates

**Date:** 2026-05-11 (Day 11) · **Owner:** Ibrahim · **Closes:** `TODOS.md` "Derive EGS lat/lon from active scenario YAML"

## Goal

Add `--scenario <name>` to `agents/mesh_simulator/main.py`. Pull `origin.lat/.lon` via `sim/scenario.py:load_scenario`. Strip hardcoded `34.0000/-118.5000` from real-scenario callers. Single source of truth.

Surfaced 2026-05-10 as 6 CI Playwright failures after PR #41 made the mesh sim the required findings gateway. PRs #42 and #43 papered over it by hardcoding scenario-origin coords in 7 callers — same value duplicated 7 times. Plan kills the duplication permanently.

## Design decisions (locked by /plan-eng-review 2026-05-11)

1. **`--scenario` added; `--egs-lat/--egs-lon` kept as explicit override.** Why: 4 of the 8 callers (`test_e2e_phase3`, `test_e2e_playwright`, `test_e2e_playwright_multi_drone`, `test_e2e_playwright_egs_findings`) use synthetic positions `34.1234/-118.5678` that match no real scenario — these stay on explicit flags.
2. **Precedence: explicit flags override scenario** + stderr WARN. Predictable for tests, no silent overrides.
3. **Scenario resolution is a shared helper in `sim/scenario.py`** (DRY: `list_drones.py` and mesh sim both import). [Eng-review 1A]
4. **No flags at all → exit 2 with clear stderr ERROR.** Prevents silent-zero-findings bug class. [Eng-review 2A]
5. **Locked stderr strings:** [Eng-review 3A]
   - Override warning: `[mesh_simulator] WARN: --egs-lat/--egs-lon override --scenario origin`
   - No-flags error: `[mesh_simulator] ERROR: no EGS configured — pass --scenario or both --egs-lat/--egs-lon`

## Out of scope

- Changing `forward_finding` drop-if-no-EGS semantics (defensive default stays; fail-fast at startup means it never triggers in production)
- Drone agent or EGS scenario loaders (already correct)
- Non-LA-origin scenarios (none exist)

## What already exists (reused)

- `sim/scenario.py:252 load_scenario(path)` — Pydantic-validated `Scenario` with `origin: GpsPoint2D`
- `sim/list_drones.py:27 _resolve_scenario_path()` — being promoted to `sim/scenario.py:resolve_scenario_path()` (public)
- `agents/mesh_simulator/main.py:482 sim.set_egs_position()` — already takes lat/lon
- `scripts/tests/test_launch_scripts.py:576` regression guard — TODO comment at line 588 literally anticipates this migration

## Implementation

### A. `sim/scenario.py`

Add public helper:

```python
def resolve_scenario_path(arg: str) -> Path:
    """Resolve a scenario_id or path to an absolute Path.

    Accepts either:
      - a path that exists (returned as-is),
      - or a scenario_id resolved to `sim/scenarios/<id>.yaml`.

    Raises FileNotFoundError with the path it tried.
    """
    p = Path(arg)
    if p.exists():
        return p
    _PROJECT_ROOT = Path(__file__).resolve().parent.parent
    candidate = _PROJECT_ROOT / "sim" / "scenarios" / f"{arg}.yaml"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(
        f"scenario not found: {arg!r} (also looked at {candidate})"
    )
```

### B. `sim/list_drones.py`

Replace local `_resolve_scenario_path` with `from sim.scenario import resolve_scenario_path`. Update call site. Existing tests stay green.

### C. `agents/mesh_simulator/main.py`

1. Add `from sim.scenario import load_scenario, resolve_scenario_path` (project root is already on sys.path at lines 51–53).
2. `_parse_args`: add `--scenario` (default `None`).
3. `main()` precedence logic:

```python
explicit_lat = args.egs_lat is not None and args.egs_lon is not None
if explicit_lat:
    if args.scenario is not None:
        print("[mesh_simulator] WARN: --egs-lat/--egs-lon override --scenario origin", file=sys.stderr, flush=True)
    sim.set_egs_position(args.egs_lat, args.egs_lon)
elif args.scenario is not None:
    scenario = load_scenario(resolve_scenario_path(args.scenario))
    sim.set_egs_position(scenario.origin.lat, scenario.origin.lon)
else:
    print("[mesh_simulator] ERROR: no EGS configured — pass --scenario or both --egs-lat/--egs-lon", file=sys.stderr, flush=True)
    return 2
```

### D. Callers — migrate 4 real-scenario callers

| File | Line | Change |
|---|---|---|
| `scripts/launch_swarm.sh` | 152 | `--egs-lat 34.0000 --egs-lon -118.5000` → `--scenario "$SCENARIO"` |
| `scripts/run_beat5_capture.sh` | 189 | same |
| `frontend/ws_bridge/tests/test_e2e_playwright_real_drone_findings.py` | 114 | `--egs-lat`/`--egs-lon` args → `--scenario disaster_zone_v1` |
| `frontend/ws_bridge/tests/test_e2e_playwright_dom_render.py` | 129 | same |

**Untouched** (synthetic positions, no real scenario): `test_e2e_phase3.py`, `test_e2e_playwright.py`, `test_e2e_playwright_multi_drone.py`, `test_e2e_playwright_egs_findings.py`.

### E. Regression guards — `scripts/tests/test_launch_scripts.py`

Replace the single-script test at line 576 with a parametrized walker:

```python
@pytest.mark.parametrize("script_name", _shell_launchers_that_invoke_mesh_sim())
def test_shell_launcher_passes_egs_config_to_mesh_simulator(script_name):
    """Every shell launcher in scripts/ that invokes mesh_simulator MUST pass
    EITHER --scenario OR both --egs-lat AND --egs-lon. Otherwise
    `forward_finding` silently drops every finding (PR #41 made the mesh sim
    the required findings gateway). This guard fails fast with one clear
    message if any launcher drops the flags."""
    # ... run --dry-run, scan mesh_simulator lines, assert
```

`_shell_launchers_that_invoke_mesh_sim()` greps `scripts/*.sh` for `mesh_simulator` and returns the matching script names. Catches `launch_swarm.sh`, `run_beat5_capture.sh`, and any future launcher.

### F. New CLI tests — `agents/mesh_simulator/tests/test_cli_scenario.py` (new file)

Pure-Python, no Redis. ~150 LOC.

| # | Test | Asserts |
|---|---|---|
| 1 | `test_scenario_flag_loads_origin_for_known_id` | `main(["--scenario", "disaster_zone_v1"])` calls `set_egs_position(34.0, -118.5)` (via mock) |
| 2 | `test_scenario_flag_accepts_path` | path-form (e.g., `sim/scenarios/resilience_v1.yaml`) works |
| 3 | `test_scenario_flag_unknown_id_errors` | `FileNotFoundError` with the path tried in the message |
| 4 | `test_explicit_egs_overrides_scenario_with_warning` | both flags → explicit wins; stderr contains `WARN: --egs-lat/--egs-lon override` |
| 5 | `test_no_flags_exits_with_clear_error` | `main([])` returns 2; stderr contains `ERROR: no EGS configured` |

### G. Playwright e2e — 2 migrated tests are the proof

`test_e2e_playwright_dom_render.py` and `test_e2e_playwright_real_drone_findings.py` already drive the drone agent with `disaster_zone_v1`. Swapping their mesh sim args from explicit lat/lon to `--scenario` makes the migration end-to-end self-checking: if the dashboard stops rendering findings, these fail fast.

### H. Docs

1. **`TODOS.md`** — replace open entry with `### CLOSED — Derive EGS lat/lon from active scenario YAML` + resolution block citing this plan.
2. **`docs/STATUS.md`** — update Day-10 header to Day 11 / May 11; add Ibrahim Day 11 entry.
3. **`docs/08-mesh-communication.md`** — grep for mesh sim CLI examples; swap if present.
4. **`docs/13-runtime-setup.md`** — same; swap manual mesh launch example.

## Validation order

1. `uv run pytest sim/tests/test_scenario.py` — `resolve_scenario_path` covered (extracted helper)
2. `uv run pytest agents/mesh_simulator/tests/test_cli_scenario.py` — 5 new CLI tests
3. `uv run pytest agents/mesh_simulator/tests/` — no existing-test regressions
4. `uv run pytest scripts/tests/test_launch_scripts.py` — parametrized regression guard
5. `bash scripts/launch_swarm.sh --dry-run` — output shows `--scenario disaster_zone_v1`, no hardcoded coords
6. `bash scripts/run_beat5_capture.sh --dry-run` — same
7. `uv run pytest frontend/ws_bridge/tests/test_e2e_playwright_dom_render.py` — Playwright proves dashboard still renders findings through migrated mesh sim
8. `uv run pytest frontend/ws_bridge/tests/test_e2e_playwright_real_drone_findings.py` — second e2e
9. Full sweep: `uv run pytest` — stays green

## Acceptance criteria

- 4 real-scenario callers on `--scenario`, 4 synthetic-position callers untouched
- `resolve_scenario_path()` lives in `sim/scenario.py`, imported by both `list_drones.py` and mesh sim
- 5 new CLI tests pass
- Parametrized regression guard passes across all `scripts/*.sh` that invoke mesh sim
- 2 Playwright e2e green after migration
- TODOS entry closed with resolution block
- STATUS.md reflects Day 11 + cleanup
- Full sweep green

## Risks

| Risk | Mitigation |
|---|---|
| Missed a caller | Parametrized regression guard catches it on next test run |
| YAML load adds startup latency | ~10ms; not a concern |
| Conflict path (both flags) confuses operators | Loud stderr WARN |
| No-flags case breaks an obscure caller | Fail-fast surfaces it immediately; no silent regressions |
| Day 12 Beat 5 capture risk | `run_beat5_capture.sh` migration covered by both unit + Playwright tests |

## Effort

~1.5–2 hr. Code ~50 min (extract + mesh main + 4 callers), Playwright runs ~10 min, docs ~15 min, sweep ~20 min.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 4 issues, 0 critical gaps, 0 unresolved |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | n/a (no UI scope) | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

**ENG CLEARED.** 4 review issues resolved inline (1A extract resolver, 2A fail-fast on no-EGS, 3A lock stderr strings, 4A parametrized regression guard). 0 critical failure gaps. 0 unresolved decisions. Outside voice skipped (plan size + scope make it unnecessary).

**VERDICT:** ENG CLEARED — ready to implement.
