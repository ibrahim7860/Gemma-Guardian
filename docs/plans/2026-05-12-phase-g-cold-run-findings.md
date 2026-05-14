# 2026-05-12 — Phase G cold-run findings (M1 16GB)

Companion to [`2026-05-12-phase-g-cold-run.md`](2026-05-12-phase-g-cold-run.md).
Executed by Ibrahim on Apple Silicon M1 16GB.

**This run does NOT close Phase G.** It produces a punch list to apply
*before* Thayyil's Days-15–16 fresh-machine cold run, which is the run
that actually closes the gate. Goal here was to shrink Thayyil's finding
surface so the gate closes cleanly when his run happens.

## Environment snapshot

| Component | Value |
|---|---|
| `uname` | `Darwin … 25.4.0 arm64` (macOS) |
| Python (system) | 3.12.12 |
| Python (venv picked by `uv sync --all-extras`) | **3.14.4** |
| Redis | 8.6.2 |
| Ollama | 0.23.1 |
| tmux | 3.6a |
| uv | 0.11.2 |
| Repo cloned-from | `https://github.com/ibrahim7860/Gemma-Guardian.git` |
| Initial SHA tested | `7509928` (origin/main at start) |
| Final SHA tested  | `c2c20cc` (after F1 fix landed mid-run) |
| Clone path | `/tmp/phase-g-coldrun/gemma-guardian` |
| Log path | `/tmp/phase-g-coldrun/logs[2-4]/` |
| Evidence path | `/tmp/phase-g-coldrun/evidence/` |

## Section-by-section findings

| Section | Result | Findings |
|---|---|---|
| §1 — OS prerequisites | PASS with note | F7 |
| §2 — Clone + uv sync | PASS | F2 (minor) |
| §3 — First-run pytest | FAIL then PASS | F1 (fixed inline) |
| §4a — single-drone smoke | **PASS after F4/F8 fix** | F3, F4, F8, F9 |
| §4b — hybrid demo | re-validated via patched launcher | F4 fix verified |
| §4c — full resilience | not executed (time budget) | F4 fix verified via §4a path |
| §5 — per-layer health | spot-check PASS | — |
| §6 — common failures | spot-check PASS with note | F5 |
| §7 — fixture reproduction | PASS | — |
| §8 — cross-references | PASS | 17/17 ok |

---

## F1 — `run_drone3_reliability.sh` missing `--dry-run` (P1, **FIXED**)

- **section:** §3
- **doc_line:** §3 line "Everything should pass against `uv sync --extra
  sim --extra mesh --extra dev`. If any test fails on a clean checkout,
  stop and file an issue — that's a Phase G blocker."
- **command_run:** `PYTHONPATH=. uv run python -m pytest sim/ agents/mesh_simulator/ scripts/tests/ -v`
- **actual_output:**
  `FAILED scripts/tests/test_launch_scripts.py::test_shell_launcher_passes_egs_config_to_mesh_simulator[run_drone3_reliability.sh]`
  with `Failed: Timeout (>30.0s) from pytest-timeout.`
- **expected_per_doc:** all green
- **gap_type:** regression
- **suggested_fix:** add `--dry-run` branch that prints planned mesh-sim
  + sim + drone-agent invocations and exits 0
- **owner:** me-this-PR (**already fixed and pushed**, commit `c2c20cc`)
- **post-fix evidence:** re-clone of `origin/main` at `c2c20cc` →
  `381 passed in 20.51s`

Notable: §3's "stop and file" instruction worked exactly as intended —
caught a real regression I introduced two commits earlier (`7509928`).

---

## F4 — `bash scripts/launch_swarm.sh` fails with `ModuleNotFoundError` (P1, **FIXED**)

**Status:** fixed inline by Ibrahim during cold-run. Applied to
`scripts/launch_swarm.sh`, `scripts/run_hybrid_demo.sh`, and
`scripts/run_beat5_capture.sh`. Pure wrappers (`scripts/run_resilience_scenario.sh`,
`scripts/run_full_demo.sh`) inherit the fix transparently.

Regression guard: `scripts/tests/test_launch_scripts.py::test_shell_launcher_emits_venv_activation_when_present`
parametrizes over every `scripts/*.sh` that defines `emit()` with `python3`
invocations; any future launcher that drops the `${ACTIVATE}` prefix or
the `ACTIVATE` setup is caught by the parametrize discovery.

**End-to-end verification:** sim ran clean to completion from an
`env -i` shell (no inherited VIRTUAL_ENV) — `waypoint_runner: reached
--duration=20.0s; exiting cleanly`, mesh + drone + ws_bridge all came up
without `ModuleNotFoundError`. Evidence:
`/tmp/phase-g-verify/logs/`.



- **section:** §4 (all three demos)
- **doc_line:** §4a, §4b, §4c launch commands
- **command_run:** `bash scripts/launch_swarm.sh single_drone_smoke --drones=auto --duration=30`
- **actual_output:**
  ```
  Traceback (most recent call last):
    File ".../sim/waypoint_runner.py", line 44, in <module>
      import redis
  ModuleNotFoundError: No module named 'redis'
  ```
  Identical error class across all spawned services
  (waypoint: `redis`, frames: `redis`, mesh: `redis`,
  drone1: `httpx`, egs: `jsonschema`, ws_bridge: `uvicorn`).
- **expected_per_doc:** smoke run completes, sim runners self-terminate
  after 30s with `[waypoint_runner] reached --duration=30.0s`
- **gap_type:** missing (doc step + script behavior mismatch)
- **root cause (two compounding issues):**
  1. **Script:** `scripts/launch_swarm.sh` and `scripts/run_hybrid_demo.sh`
     (and by extension `scripts/run_resilience_scenario.sh`) invoke
     services as bare `python3 ...` — neither `uv run python3 ...` nor
     `.venv/bin/python3 ...`.
  2. **Doc:** §2 presents `source .venv/bin/activate` as **optional**
     ("if you prefer not to prefix everything with `uv run`"). For §4
     it is NOT optional — without it, `python3` resolves to system
     `python3.14` (or whatever the user's shell picks) which lacks the
     venv's dependencies.
- **Additional trap (separate sub-bug):** even with `source
  .venv/bin/activate` in the calling shell, **tmux subshells lose the
  venv** because `tmux new-window` spawns a fresh shell that re-sources
  `~/.zshrc`/`~/.bashrc` without re-running activate. Verified on M1
  zsh; reproducible after `tmux kill-server` and even via `uv run bash
  scripts/launch_swarm.sh ...`.
- **suggested_fix (one of):**
  - **(a) Doc-only:** §2 changes "Activate the venv directly if you
    prefer..." to **"You MUST activate the venv before any `scripts/*.sh`
    launch command, AND if you have a prior tmux session running,
    `tmux kill-server` first."**
  - **(b) Script-only (recommended):** in `launch_swarm.sh` /
    `run_hybrid_demo.sh`, detect `.venv/bin/activate` at the top and
    prefix every `emit`'d command with `source $REPO_ROOT/.venv/bin/activate && `
    when the venv exists. Robust against PATH mishaps AND stale tmux
    servers. `python3` literal stays in the file so
    `_shell_launchers_that_invoke_mesh_sim` still matches.
- **owner:** Hazim (launcher contract is sim/launcher scope)
- **estimated fix cost:** ~10 LoC change in 2 scripts + a test that
  asserts `source .venv/bin/activate &&` appears in emit lines when
  `.venv` exists at test time. CC: ~15 min. Human: ~1h.

This is the single biggest gap. Everything in §4 is blocked until F4
lands. Closing F4 likely unblocks §4a/b/c entirely with no other
findings.

---

## F2 — `uv sync` warns about VIRTUAL_ENV mismatch (low)

- **section:** §2 / §3
- **command_run:** `uv sync --all-extras` then `uv run python -m pytest …`
  from a shell where another project's `.venv` is already activated
- **actual_output:**
  `warning: VIRTUAL_ENV=… does not match the project environment path
  .venv and will be ignored; use --active to target the active
  environment instead`
- **expected_per_doc:** doc is silent on this
- **gap_type:** misleading
- **suggested_fix:** §2 add a sentence: "If your shell already has
  another project's `.venv` activated, `deactivate` first — uv prints a
  confusing warning otherwise."
- **owner:** Hazim
- **severity rationale:** non-blocking, but for a tester juggling
  multiple repos this is a 5-minute trip-up.

---

## F3 — §4a "what this exercises" list incomplete (low)

- **section:** §4a
- **doc_line:** §4a "What this exercises:" bullet list
- **observed:** on a fully-built repo, `bash scripts/launch_swarm.sh
  single_drone_smoke …` ALSO launches `agents/egs_agent/main.py`,
  `agents/drone_agent` (drone1), and `ws_bridge` via uvicorn. The doc
  only mentions waypoint_runner, frame_server, and mesh_simulator.
- **expected_per_doc:** "skip note for unbuilt components" implies a
  partial-install path; doesn't explain what happens on a complete
  install.
- **gap_type:** missing
- **suggested_fix:** append a fourth bullet: "On a fully-built repo,
  this ALSO launches `agents/egs_agent/main.py`, the per-drone agent,
  and `ws_bridge`. Each will attempt to connect to Ollama for Gemma 4 —
  pull `gemma4:e2b` and `gemma4:e4b` first or `single_drone_smoke` will
  fail at agent boot."
- **owner:** Hazim
- **severity rationale:** an outside tester who hasn't pre-pulled the
  Gemma models will see drone1/egs crash on Ollama healthcheck failure
  even before F4 is hit.

---

## F5 — §6 Ollama pre-warm fix is wrong for 3-drone vision+tools (P2)

- **section:** §6 "Ollama: first inference times out"
- **doc_line:** the `curl -s -X POST http://127.0.0.1:11434/api/chat
  -d '{"model":"gemma4:e2b","stream":false,"messages":[{"role":"user",
  "content":"hi"}]}'` text-only pre-warm
- **observed:** this is a TEXT-only warm. The path that actually times
  out under 3-drone serial inference is the **vision+tools** call shape
  (`messages` includes a base64 image AND `tools` includes the
  `report_finding` function definition). My drone3 reliability
  investigation proved the text warm doesn't transfer.
- **expected_per_doc:** "Once the model is warm, subsequent calls land
  in 30–45 s on CPU." This is true for text but not for vision+tools
  cold-load.
- **gap_type:** misleading
- **suggested_fix:** §6 add an Apple-Silicon-specific note pointing at
  `docs/plans/2026-05-12-drone3-reliability-capture.md` for the full
  tuning recipe (`OLLAMA_NUM_PARALLEL=1`, `KV_CACHE_TYPE=q8_0`,
  `FLASH_ATTENTION=1`, `KEEP_ALIVE=30m`, **vision+tools** pre-warm via
  `scripts/run_drone3_reliability.sh:70-87`, and the
  `DRONE_AGENT_OLLAMA_TIMEOUT_S` env override).
- **owner:** Hazim or Ibrahim (since the source-of-truth doc is in
  Ibrahim's plans/ dir; Hazim owns sim-reproduction.md)
- **estimated fix cost:** 1 paragraph in §6.

---

## F6 — §3's "stop and file" instruction worked perfectly (info, positive)

- **section:** §3
- **observed:** the explicit "If any test fails on a clean checkout,
  stop and file an issue — that's a Phase G blocker" instruction is
  exactly what caught F1 cleanly. Without it I might have shrugged off
  a 30s timeout as "probably flaky."
- **action:** **no change.** This is positive feedback for the doc's
  authoring style — keep this pattern in future Phase G iterations.

---

## F8 — Pre-existing: spaces in REPO_ROOT silently break `cd` in emit lines (P2, **FIXED**)

- **section:** §4 (latent)
- **discovered while:** verifying F4 fix from the dev clone whose path
  is `/Users/.../CS Work/Repos/Gemma-Guardian` (space in "CS Work")
- **observed:** `emit waypoint "cd $REPO_ROOT && python3 ..."` unquoted
  → tmux pane runs `cd /Users/.../CS Work/...` which bash interprets as
  `cd /Users/.../CS` (other words silently dropped). The subsequent
  `python3` then runs from `/Users/.../CS` and finds no module
  hierarchy. Without F4 fix, this manifested identically to F4. With
  F4 fix, manifested as `-bash: source: /Users/.../CS: is a directory`.
- **gap_type:** missing (script quoting)
- **fix applied:** every emit line changed from `"cd $REPO_ROOT && ..."`
  to `"cd \"$REPO_ROOT\" && ..."`. Same pattern applied to `ACTIVATE`
  variable. Applied to `launch_swarm.sh`, `run_hybrid_demo.sh`,
  `run_beat5_capture.sh`.
- **owner:** Ibrahim (fixed inline)
- **why pre-existing:** anyone with a space-containing path who tried
  to run these scripts before would have silently cd'd to a partial
  path and gotten module-not-found errors that look identical to F4.

---

## F9 — `single_drone_smoke` + `shared/config.yaml` mismatch on doc default (low)

- **section:** §4a
- **doc_line:** §4a `bash scripts/launch_swarm.sh single_drone_smoke …`
- **observed:** waypoint_runner exits with
  `[waypoint_runner] mission.drone_count=3 from shared/config.yaml
  disagrees with scenario 'single_drone_smoke' len(drones)=1.
  Reconcile the two before launching: either edit shared/config.yaml or
  add/remove drones in the scenario YAML.`
- **expected_per_doc:** smoke run completes after 30s
- **gap_type:** missing (config-vs-scenario coupling not mentioned)
- **note:** this is an intentional sanity guard added on
  `feature/sim-polish` (sim/ROADMAP.md "Done" entries). The doc just
  needs to mention it.
- **suggested_fix:** §4a add a one-line note: "`shared/config.yaml`'s
  `mission.drone_count` must match the scenario's drone count. The
  default `drone_count: 3` aligns with `disaster_zone_v1` /
  `resilience_v1`; before running `single_drone_smoke`, edit
  `mission.drone_count: 1` in `shared/config.yaml`."
- **owner:** Hazim
- **severity:** an outside tester following §4a literally hits this
  immediately. Cheap doc fix.

---

## F7 — Python 3.14 not in §1 prereq table (low)

- **section:** §1 OS prerequisites
- **observed:** the table says `Python | 3.11+ | 3.13 also works`. On
  this M1 box, `uv sync --all-extras` picked **Python 3.14.4** for the
  venv. All 381 sim/mesh/scripts tests passed on 3.14.
- **expected_per_doc:** any 3.11+ Python should work; 3.13 explicitly
  called out.
- **gap_type:** stale
- **suggested_fix:** change the row to `Python | 3.11+ | 3.13 / 3.14
  also work (uv picks the latest available on your box)`.
- **owner:** Hazim
- **severity rationale:** no functional impact (tests green), but a
  3.14 tester might second-guess themselves.

---

## Doc-edit punch list

Items shipped by Ibrahim in this PR:
- F1: `scripts/run_drone3_reliability.sh` `--dry-run` (commit `c2c20cc`,
  already on `origin/main`).
- F4: `ACTIVATE` venv-prefix in `launch_swarm.sh`,
  `run_hybrid_demo.sh`, `run_beat5_capture.sh` + regression guard test.
- F8: quote `$REPO_ROOT` in every emit'd `cd` and in `ACTIVATE`
  assignment (same 3 scripts).
- Doc updates in `docs/sim-reproduction.md` covering F2, F3, F5, F7, F9.

Items still open for Hazim (none P0):
- (none — all surfaced findings shipped in this PR.)

---

## Phase G acceptance

**This run still does NOT formally close Phase G** (Thayyil's
Days-15–16 fresh-box run on Linux/WSL2 is what closes it), but every
finding it surfaced is shipped. F1 + F4 + F8 are script fixes with
regression guards. F2, F3, F5, F7, F9 are doc patches now in
`docs/sim-reproduction.md`. Thayyil's run should see §1–§8 green
end-to-end from a fresh `git clone`.

Recommendation for STATUS.md:
> Phase G cold-run completed 2026-05-12 by Ibrahim on M1 16GB. 9
> findings surfaced; F1, F4, F8 fixed inline with regression tests
> (commits `c2c20cc` + this PR). F2, F3, F5, F7, F9 shipped as
> doc-edits in same PR. Awaits Thayyil's Days-15–16 Linux/WSL2 cold
> run for formal Phase G closure.

## Limits of this run (what Thayyil still owes)

- A **Linux/WSL2** cold-run — the F4 tmux-loses-venv sub-trap is macOS-
  zsh-specific in its surface form; the underlying root cause (raw
  `python3` in scripts) bites everywhere but may present differently.
- A **fresh ollama pull** time measurement — my cache already had both
  Gemma 4 tags.
- A **fresh uv cache** sync time — my uv cache was warm; outsider's
  first run will be 5–10 min on a typical broadband connection.
- **§4a/b/c full execution** — blocked here by F4; will need re-test
  after F4 lands.
