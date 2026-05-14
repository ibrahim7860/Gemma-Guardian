# 2026-05-12 — Phase G cold-run of `docs/sim-reproduction.md` on M1 16GB

## Why

`sim/ROADMAP.md` Phase G has one open item: *"have an outside tester run cold
from scratch on a fresh box and fix everything that breaks the cold run."*
Hazim's STATUS.md entry says he's blocked on this. With six days to
submission, every doc gap surfaced now is a gap an outside reviewer or
hackathon judge won't trip over later.

Ibrahim's M1 16GB laptop is the most "outside" hardware on the team:
- Different OS than Hazim's box (macOS Metal vs WSL2/CUDA).
- The drone3-reliability work (commits `33d54d9`, `7509928`) already proved
  this box has *known* deviations from the doc's defaults (httpx 120 s
  timeout, `OLLAMA_NUM_PARALLEL` not mentioned anywhere) — those deviations
  are themselves likely Phase G doc gaps to file.

So: walk the doc literally, in order, and write down every place the doc's
instructions don't match what actually happens.

## What this is NOT

- Not a perception-correctness check. Beat 5 capture and drone3 victim
  recognition belong to other plans.
- Not a fix-as-you-go session. Findings get filed back to Hazim/Thayyil as a
  diff and a punch list. Only fixes I'd ship anyway (typos, broken commands)
  go in this PR; everything else is a TODO entry for Phase G owner.
- Not a substitute for Thayyil's Days-15–16 cold run. See "Phase G status"
  below — this run produces a punch list to apply *before* his run, not
  in place of it.

## What "outside tester" means here (honest version)

I am not a true outsider — I wrote half this repo. The cold-run still has
value because:

1. **Doc literal-ness:** I will execute *exactly* what the doc says, not
   what I know works. If §4c says `bash scripts/run_resilience_scenario.sh`
   and that times out on M1 without `OLLAMA_NUM_PARALLEL=1`, that's a gap.
2. **True fresh checkout:** `git clone` into `/tmp/phase-g-coldrun/` so
   §1–§2 (prereqs, install) are genuinely exercised on a path that has
   never seen `uv sync` for this repo. Existing dev clone stays untouched.
3. **State isolation:** `GG_LOG_DIR=/tmp/phase-g-coldrun/logs` and
   `redis-cli -n 1` (DB 1, not the default 0 the dev work may be using).
   Brew-restart of Ollama reuses the polling cleanup pattern from
   `scripts/run_drone3_reliability.sh:cleanup()` to avoid the race the
   drone3 plan already documented.
4. **Fresh-eyes review:** read §1, §2, §6 as if I'd never seen them. Note
   anywhere I had to context-switch to another doc to understand a step.

This honesty about the limits of my "outside" status goes in the findings
doc loudly: **this run does NOT close Phase G.** It produces a punch list
to apply *before* Thayyil's Days-15–16 fresh-machine cold run, which is
the run that actually closes the gate. Goal here is to shrink Thayyil's
finding surface to near-zero so his run is fast and the doc ships clean.

## Per-section checks (in doc order)

Each step has: (a) the doc command exactly as written, (b) what I expect,
(c) what I check, (d) what I write down if observation diverges. The
overall execution sequence is consolidated in "Execution order" at the
bottom of this doc — don't read this section as a script.

### §1 — OS prerequisites

Just a read-through. Compare doc's `Python | 3.11+` table against `python3
--version`, `redis-cli --version`, `ollama --version`, `tmux -V`, `uv
--version`. File a gap if any version mentioned in the doc is wrong.

### §2 — Clone and install Python dependencies

True fresh checkout: `git clone <local-origin-url> /tmp/phase-g-coldrun/
gemma-guardian` (use the local repo's origin URL or the GitHub remote
directly so we exercise the doc's literal command). Then `uv sync
--all-extras` against a venv that has never seen this project. Time both
clone + sync; both are first-time-on-this-box costs an outside tester
pays.

Watch for any package resolution failures on macOS that wouldn't surface
on Linux (where Hazim works). Watch for `setup-uv`-style cache misses
that aren't documented as "expected first run."

Doc says "Activate the venv directly if you prefer not to prefix
everything with `uv run`" — try both paths, note if one breaks (e.g.
shell-specific `.venv/bin/activate` instructions are zsh-friendly on
macOS).

All subsequent steps (§3–§8) run from `/tmp/phase-g-coldrun/gemma-guardian`
unless otherwise noted, so the dev clone at `~/CS Work/Repos/Gemma-Guardian`
stays untouched.

### §3 — First-run validation: pytest

```bash
PYTHONPATH=. uv run python -m pytest sim/ agents/mesh_simulator/ scripts/tests/ -v
```

Expect: green. CI runs this and is green on `main` (commit `b1ad600`).

What I check:
- Pass/fail count matches what `sim/ROADMAP.md` claims (73 sim/mesh +
  scripts tests).
- No `xfail` / `skipped` surprises.
- Total wall-clock for the suite (doc doesn't promise a number; if it's
  >2 min, that's worth a doc note).

### §4a — Single-drone smoke (~30 s)

```bash
bash scripts/launch_swarm.sh single_drone_smoke --drones=auto --duration=30
```

Expect: tmux session `fieldagent` with `waypoint`, `frames`, `mesh`
windows; `[skip]` lines for `egs`, `drone1` (not part of `single_drone_smoke`
roles for a sim-only test). Sim runners self-terminate after 30 s.

What I check:
- Redis already running → no `.gg_started_redis` sentinel.
- Redis NOT running → launcher daemonizes one, sentinel appears, then
  `stop_demo.sh` cleans it up.
- `redis-cli pubsub channels 'drones.*'` returns `drones.drone1.state` and
  `drones.drone1.camera` while the smoke is live.
- `validation_events.jsonl` is empty (no drone agent, no validation).

### §4b — Hybrid 3-drone demo (real sim + fake EGS/findings)

```bash
bash scripts/run_hybrid_demo.sh disaster_zone_v1
```

Expect: bridge on `:9090`, fake EGS + fake findings producing data.

```bash
PYTHONPATH=. uv run python scripts/check_hybrid_demo.py
```

Expect: PASS (3 drones in `active_drones`, ≥1 finding, ack roundtrip clean).

What I check:
- Bridge log says `uvicorn` (regression for the bare-script-exit bug
  documented in §6).
- All 3 fake-producer windows exist.
- `stop_demo.sh hybrid_demo` actually tears it down (no orphan processes
  on port 9090, no stray `dev_fake_producers.py`).

### §4c — Full resilience scenario (~4 min nominal, 10 min hard cap)

```bash
bash scripts/run_resilience_scenario.sh
```

This is the section I expect to surface the most doc gaps on Apple
Silicon. The specific M1 16GB cure for the failure modes I expect to hit
is fully documented in
[`docs/plans/2026-05-12-drone3-reliability-capture.md`](2026-05-12-drone3-reliability-capture.md)
— the vision+tools pre-warm pattern, the Ollama env tuning table, and
the `DRONE_AGENT_OLLAMA_TIMEOUT_S` env override (commit `7509928`).
This plan does NOT restate those; the findings doc will cite them as
the proposed fix for each gap I file.

What I file as Phase G gaps if observed:
- §6's pre-warm `curl` is text-only — does it actually warm the
  vision+tools path 3 drones serialize on?
- §6 has no mention of Apple Silicon Metal serialization or the
  Ollama env tuning needed to survive 3-drone concurrent vision+tools.
- Agent's default 120 s timeout vs Metal-serialized ~126 s round-trip.
- Any other doc/observation divergence on this step.

**Abort criteria** (hard 10-min cap on this step; do not exceed):
1. No `validation_events.jsonl` lines written 8 min after step start.
2. Any `dronN.log` contains `httpx.ReadTimeout` or
   `httpx.ConnectError`.
3. `redis-cli pubsub channels 'drones.*'` returns empty mid-run.

Hit any of those → abort, capture logs verbatim under
`/tmp/phase-g-coldrun/abort/`, and write the wedge up as the finding.
A wedge IS a Phase G finding — don't force a "success."

### §5 — Per-layer health checks

Walk every command in §5 against a live §4b (hybrid) run. Each command
either returns expected output or doesn't.

What I check:
- `redis-cli psubscribe 'drones.drone1.state'` actually receives messages.
- `ls $GG_LOG_DIR` matches the file list in the doc (note any missing or
  extra files).
- `tmux attach -t fieldagent` works; window names match doc.
- The Flutter dashboard section (§5 "Dashboard") — I'll skip the dashboard
  itself since I already run it daily, but note any doc instructions that
  are wrong (e.g. `flutter` on PATH assumption).

### §6 — Common failures spot-check

Read every failure mode. For each one, ask: is this still a current
failure mode on `main`? If a fix has shipped but the doc still describes
the broken-then-fixed flow, that's OK (it's a "regression coverage" note).
If a new failure mode has emerged that isn't listed, file it.

Specific spot-checks I'll do:
- `agents/drone_agent/main.py ImportError` — is the script-form ImportError
  still reproducible? (Doc says yes, flagged for Kaleel.)
- Ollama cold-load timeout text-warm fix — see §4c above.
- The mesh-adjacency-full-mesh-in-disaster_zone_v1 note — verify by
  running §4b and checking `mesh.adjacency_matrix`.

### §7 — Fixture reproduction (dry run only)

```bash
uv run python -m scripts.fetch_disaster_fixtures --dry-run
```

Expect: previews 8 frame URLs + 1 base-image URL, no network writes.

If the dry-run actually fetches anything (it shouldn't per the doc) that
is a Phase G gap.

### §8 — Cross-references

Click through every cross-reference link. If any of them 404 inside the
repo (`13-runtime-setup.md`, `15-multi-drone-spawning.md`, etc.), that's a
gap.

## Output artifact

A new doc at `docs/plans/2026-05-12-phase-g-cold-run-findings.md` with the
following fields per finding so the punch list is machine-actionable, not
prose:

| Field | Notes |
|---|---|
| `section` | doc section number (e.g. §4c) |
| `doc_line` | line in `docs/sim-reproduction.md` |
| `command_run` | the exact bash invocation |
| `actual_output` | verbatim or path under `/tmp/phase-g-coldrun/evidence/` |
| `expected_per_doc` | what the doc claims |
| `gap_type` | one of: typo \| stale \| missing \| misleading \| wedge |
| `suggested_fix` | concrete patch or "see plan X" reference |
| `owner` | Hazim \| Thayyil \| me-this-PR |

Plus four section headers:

1. **Environment snapshot** — uname, Python, Redis, Ollama, uv versions;
   git SHA cold-run executed against; cloned-from-where.
2. **Section-by-section findings** — pass/fail per §1–§8 using the
   table format above.
3. **Doc-edit punch list** — items where `owner = me-this-PR` get
   bundled into this PR; rest gets handed to Hazim/Thayyil.
4. **Phase G acceptance** — explicit one-liner: *"this run does NOT
   close Phase G — Thayyil's Days-15–16 fresh-machine run does. This
   run's job is to shrink Thayyil's finding surface so the gate closes
   cleanly when his run happens."*

## Acceptance

This plan is done when:

1. Findings doc exists, every §1–§8 has a row (pass or fail).
2. Every `gap_type = wedge` finding has stderr captured verbatim and an
   abort timestamp.
3. PR with doc fixes I'd ship anyway is open (or "no fixes needed" is
   documented).
4. STATUS.md / sim/ROADMAP.md Phase G entry gets a one-line update:
   *"Punch list filed 2026-05-12; awaits Thayyil's cold run to close."*

Soft target: 60–90 min wall clock (excluding the cold `uv sync` and
`ollama pull` time, which we'll measure and report rather than budget).
Hard cap: 2 hours, after which remaining sections get marked
NOT-EXECUTED with the reason.

## Risks / explicit non-goals

- **Not changing `sim-reproduction.md` mid-flight.** Doc edits go in a
  separate commit, after the cold-run finishes, so the doc state under
  test stays fixed.
- **Not running the dashboard end-to-end** beyond §5's bridge ping —
  that's Beat 5 capture's domain, not Phase G's.
- **Not retrying §4c if it wedges.** First-run experience is what Phase G
  cares about; if the doc says "this should just work" and it doesn't, the
  finding is "the doc lies on first run." Retrying masks that.
- **Not patching the agent or sim code.** Only doc + (maybe) launcher
  scripts.

## Execution order (the literal sequence)

1. Snapshot environment in dev clone: versions of python/redis/ollama/
   tmux/uv, current `git rev-parse HEAD`, `ollama list` (models already
   pulled — note which, since the doc says `ollama pull gemma4:e2b` is a
   prereq; if my cache already has them I can't time the cold pull, file
   that limit honestly).
2. `mkdir -p /tmp/phase-g-coldrun && cd /tmp/phase-g-coldrun &&
   git clone <origin> gemma-guardian` — start the wall clock here.
   Subsequent commands run from `/tmp/phase-g-coldrun/gemma-guardian`.
3. `export GG_LOG_DIR=/tmp/phase-g-coldrun/logs && mkdir -p "$GG_LOG_DIR"`.
4. Pre-flight Ollama using the cleanup pattern from
   `scripts/run_drone3_reliability.sh:cleanup()` (poll
   `/api/version` until reachable before proceeding — avoids the brew
   restart race the drone3 plan already documented).
5. For redis isolation: use a non-default DB so we don't touch any
   dev-state redis is holding. `redis-cli -n 1 flushdb`. Any
   `--redis-url` we pass to launchers gets `?db=1` (or the launcher's
   own equivalent). If a launcher hard-codes db=0, that itself is a
   Phase G finding.
6. Execute §2 → §3 → §4a → §4b → §4c (with 10-min hard cap) → §5 →
   §6 spot-check → §7 dry-run → §8 link audit, in order.
7. Capture stderr + stdout for every divergence verbatim under
   `/tmp/phase-g-coldrun/evidence/<section>/`.
8. Write `docs/plans/2026-05-12-phase-g-cold-run-findings.md` in the
   dev clone (not the /tmp clone — the findings doc is the project
   artifact).
9. Open PR with findings doc + any one-shot doc fixes I'd ship anyway
   (typos, dead links, obviously broken commands).
10. Reply to Hazim/Thayyil in standup with the punch list and the
    explicit "this does NOT close Phase G" note.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 5 issues, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

**UNRESOLVED:** 0
**VERDICT:** ENG CLEARED — ready to execute. CEO/Design/Outside-voice not needed for this process plan.

**Findings summary (all resolved with chosen "Recommended" options):**
1. P1 — fresh clone vs install-path test → clone into `/tmp/phase-g-coldrun/`
2. P1 — destructive resets blast radius → `GG_LOG_DIR` isolation + `redis-cli -n 1` + reuse drone3 `cleanup()`
3. P2 — DRY with drone3-reliability plan → reference, don't restate
4. P2 — `§4c` no abort criterion → 10-min cap + 3 explicit abort signals
5. P2 — Phase G acceptance unclear → findings doc says loudly "does NOT close Phase G; produces punch list for Thayyil"

**Lake score:** 5/5 recommendations chose complete option ✓
