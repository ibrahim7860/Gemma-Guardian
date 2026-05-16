# C7 + C8 Cleanup — Reassigned Kaleel → Ibrahim — 2026-05-15

**Drafted:** Fri 2026-05-15 PM
**Submission deadline:** Mon 2026-05-18 23:59 UTC
**Owner:** Ibrahim (reassigned from Kaleel — status unknown, deadline pressure)
**Time budget:** ~2 hr total. Fits inside Fri evening + Sat AM buffer.
**Code-freeze impact:** C7 is the only code change (~5 LOC). Must land before Sat noon CDT freeze. C8 is all docs — can slide to Sun.

---

## Why reassign

C7 + C8 were Kaleel's lane in the original Fri split (`docs/plans/2026-05-15-remaining-work-to-submission.md` Track C, items C7/C8). Status remained unknown by Fri PM — not visible in any recent commit. With Mon 23:59 UTC deadline three days out, Ibrahim absorbs the work rather than wait on a sync that may not happen.

---

## C7 — `command_translator.py:70` timeout hoist (code, ~30 min)

### Current state

`agents/egs_agent/command_translator.py:70`:
```python
async with httpx.AsyncClient() as client:
    resp = await client.post(endpoint, json=payload, timeout=180.0)
```

Inline literal `180.0`. The sibling pattern in `replanning.py` already hoisted its `180.0` → `EGS_HTTPX_PER_ATTEMPT_TIMEOUT_S = 30.0` per Hazim's GH #32 fix (commit `d86a7d9`).

### Critical constraint — DO NOT drop to 30s

`TODOS.md` L47 warning: operator-command translation may legitimately take >30s on a slow box. The hoist is **DRY only**, not a behavior change. Keep the value at `180.0`.

### Design decision

Two options surfaced in TODOS L46:

| Option | Pro | Con |
|---|---|---|
| (a) Import `EGS_HTTPX_PER_ATTEMPT_TIMEOUT_S` from `replanning.py` | Single source of truth | Couples the two timeouts — if one changes the other follows by accident. Also forces a behavior change (180 → 30) which TODOS explicitly warns against. **Rejected.** |
| (b) Define parallel `COMMAND_TRANSLATOR_HTTPX_PER_ATTEMPT_TIMEOUT_S = 180.0` in `command_translator.py` | Preserves current behavior, no coupling, clearly named for its path | Two constants for similar concepts — minor drift risk |

**Choice: (b).** Constant lives in `command_translator.py` module scope. Future invariant tests can grep for the constant name across both modules.

### Implementation

1. Add module constant near top of `command_translator.py` after imports:
   ```python
   # Per-attempt timeout for Gemma 4 E4B operator-command translation calls.
   # Operator command translation runs E4B end-to-end (system prompt + state
   # summary + retries) and can legitimately need >30s on slow boxes — see
   # TODOS.md "command_translator.py:70". Mirrored from the same value that
   # used to live inline at the post() call.
   #
   # Sibling constant: agents/egs_agent/replanning.py:EGS_HTTPX_PER_ATTEMPT_TIMEOUT_S = 30.0
   # is intentionally tighter — replan attempts run inside an outer wait_for guard
   # (GH #32 fix, Hazim commit d86a7d9), while this operator-translation path has
   # no outer guard and may need the longer budget.
   COMMAND_TRANSLATOR_HTTPX_PER_ATTEMPT_TIMEOUT_S = 180.0
   ```

2. Update line 70 to use the constant:
   ```python
   resp = await client.post(endpoint, json=payload, timeout=COMMAND_TRANSLATOR_HTTPX_PER_ATTEMPT_TIMEOUT_S)
   ```

3. No call-site changes anywhere else.

### Testing

#### Unit test (new file: `agents/egs_agent/tests/test_command_translator_timeout.py`)

```python
"""Invariant test: command_translator does not regress to inline timeout literal.

Mirrors the spirit of the GH #32 fix on replanning.py — once we hoist a
timeout to a module constant, regression-test that future edits don't
sneak the literal back into the call site.
"""
import re
from pathlib import Path
import inspect

from agents.egs_agent import command_translator


def test_timeout_constant_is_180s():
    """Behavior preservation — the operator-command timeout must remain 180s."""
    assert command_translator.COMMAND_TRANSLATOR_HTTPX_PER_ATTEMPT_TIMEOUT_S == 180.0


def test_no_inline_timeout_literal_in_post_call():
    """DRY enforcement — `timeout=` keyword must reference the module constant,
    not an inline float literal. Catches accidental re-introduction.

    LIMIT: this regex catches the obvious inline-literal form
    (`client.post(..., timeout=180.0)`). It does NOT catch local-var indirection
    (`t = 180.0; client.post(..., timeout=t)`) or **kwargs unpacking
    (`kwargs = {"timeout": 180.0}; client.post(..., **kwargs)`). For a hackathon
    timebox this is the pragmatic level; an AST-based check would catch the
    rest but isn't worth the cost.
    """
    src = inspect.getsource(command_translator)
    # Find the client.post(... timeout=X ...) call inside translate_operator_command
    # and assert X is the constant name, not a number literal.
    pattern = re.compile(r"client\.post\([^)]*timeout=([A-Z_]+|[\d.]+)", re.DOTALL)
    matches = pattern.findall(src)
    assert matches, "expected to find a client.post(..., timeout=...) call"
    for m in matches:
        assert not re.match(r"^[\d.]+$", m), (
            f"client.post timeout uses inline literal {m!r}; "
            f"must reference COMMAND_TRANSLATOR_HTTPX_PER_ATTEMPT_TIMEOUT_S"
        )


def test_timeout_constant_passed_to_httpx_call(monkeypatch):
    """Integration smoke — when translate_operator_command runs, the httpx
    client gets the constant value as the timeout kwarg.
    """
    import httpx
    captured = {}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, timeout=None):
            captured["timeout"] = timeout
            # Force the loop to bail out cleanly via a fake error response.
            raise httpx.HTTPError("fake")

    monkeypatch.setattr(command_translator.httpx, "AsyncClient", lambda: FakeClient())

    # Minimal stubs for the rest of the call chain.
    class _Stub:
        max_retries = 0

        def validate_operator_command(self, *a, **k):
            class R:
                valid = False
                failure_reason = None
                detail = "stub"
            return R()

    # Run; we expect it to fail-out the retry loop and return unknown_command.
    import asyncio
    asyncio.run(
        command_translator.translate_operator_command(
            operator_text="test",
            language="en",
            egs_state={"drones_summary": {}},
            validation_node=_Stub(),
        )
    )
    assert captured.get("timeout") == 180.0
```

#### Regression sweep

```bash
uv run pytest agents/egs_agent/tests/ -x -q
```

Must stay green. Specifically check `test_command_translator*` if it exists already.

### Done criteria

- [ ] `COMMAND_TRANSLATOR_HTTPX_PER_ATTEMPT_TIMEOUT_S` defined at module top with sibling-reference comment
- [ ] Line 70 uses the constant
- [ ] 3 new unit tests pass in `agents/egs_agent/tests/test_command_translator_timeout.py`
- [ ] Specific regression coverage green:
  - `agents/egs_agent/tests/test_command_translator*.py` (any existing file matching the glob)
  - `agents/egs_agent/tests/test_replanning*.py`
  - Full `uv run pytest agents/egs_agent/tests/ -x -q` clean
- [ ] No behavior change (timeout still 180.0)
- [ ] Commit message references TODOS.md L43-49 + Hazim's GH #32 (`d86a7d9`) precedent

---

## C8 G5 — Rewrite `docs/22-writeup-draft.md` §7 (docs, ~30 min)

### Current state

`docs/22-writeup-draft.md` lines 388-414 — old xBD-based fine-tuning narrative. Single ~25-line section. No §7.B / conditional banner exists (already cleaned in a prior pass).

### Target

Replace lines 388-414 with the C2A victim-detection narrative matching `WRITEUP.md` §6 + §6.5. The long-form draft has room — aim for 60-90 lines, more expansive than the 1500-word WRITEUP.md cap allows.

### Content outline

1. **Lead** — why C2A, why victim detection. The GATE 3 acceptance bar is `report_finding(type='victim')` 3/3 on the wow-moment frame. Base Gemma 4 E2B reliably emits 2/3; fine-tuning unlocks the third hit. xBD remains as belt-and-suspenders in `kaggle_work/` but is not the primary path.
2. **Dataset** — C2A (rgbnihal/c2a-dataset) for the victim class (10,215 UAV images, ~360k human instances across four disaster scenarios). AIDER (samik2005/aider-dataset) for the none class. SARD (nikolasgegenava/sard-search-and-rescue) held out for cross-source domain transfer. Schema collapsed to binary `{finding_type: "victim" | "none", confidence, visual_evidence}`.
3. **Method** — Unsloth `FastVisionModel` on `unsloth/gemma-4-E2B-it`. DoRA (`use_dora=True`), rank 16, alpha 32, dropout 0.05, `target_modules="all-linear"`, `finetune_vision_layers=True`, lr 2e-4 cosine, fp16 (T4 doesn't support bf16). Single Kaggle T4 free GPU, ~49 min for the v11 full run.
4. **Results (n=400 held-out)** — match WRITEUP.md §6: binary 77.25%, victim F1 0.78 (precision 0.79, recall 0.77), parse_rate 1.0, per-source C2A 97.2% / AIDER 77.5% / SARD 55%. State the SARD number honestly bounds the in-domain claim. The +13pp lift over v9 (42% → 55% SARD) came from fixing a label-collapse bug in v10 (varied scenario-keyed evidence templates).
5. **Inference integration** — Route (b) PEFT/HF chosen (route (a) Ollama Modelfile dead per Unsloth #2290 vision regression). In-process loader at `agents/drone_agent/c2a_inference.py`. Two non-trivial Unsloth↔PEFT compat shims required: `Gemma4ClippableLinear` unwrap (232 layers walked, inner `nn.Linear` rebound) and DoRA magnitude-vector key rename (`…lora_magnitude_vector.default` → `.default.weight`). 50 lines of shim code; transparent at load time. Document this honestly because future trainings reusing Unsloth+DoRA will hit the same wall.
6. **Wow-moment disclosure** — mirror `WRITEUP.md` §6.5 verbatim or by reference. State the 0/7 trigger rate, the p95=143s latency, the `--inject-overcount-once` jump-cut decision.
7. **Published artifacts** — Kaggle Model `lora-c2a-bf16/3` PUBLIC, training notebook PUBLIC.
8. **What didn't ship** — xBD building-damage adapter kept as scaffold in `kaggle_work/` but not loaded. Multi-finding-type (fire/smoke/blocked_route) deferred to post-submission per `TODOS.md` "Multi-finding-type LoRA adapter".

### Testing

- Markdown lint (informal — visually read in IDE preview)
- Link check: every `[text](url)` and every `[text](relative/path)` resolves
  ```bash
  # Quick sanity grep for broken relative paths:
  grep -oE '\[.*\]\((\.\./|[^h)][^)]*)\)' docs/22-writeup-draft.md
  ```
- Cross-doc consistency: numbers in §7 must match `WRITEUP.md` §6 + `kaggle_out_c2a/adapter/eval_summary.json`
- Read-aloud pass

### Done criteria

- [ ] `## 7. Fine-Tuning` rewritten (lines ~388 onward)
- [ ] All references to `xBD` outside this section's "what didn't ship" subsection are intentional (history-preserving, e.g., earlier section archaeology)
- [ ] Numbers match WRITEUP.md §6 exactly: 77.25 / 0.78 / 97.2 / 77.5 / 55
- [ ] Kaggle Model + Notebook URLs work in incognito
- [ ] No dead anchors to §7.B or NO-GO variants

---

## C8 J2 — Write `ml/README.md` (docs, ~20 min)

### Content boundary (per /plan-eng-review 2D)

To prevent duplication with the top-level `README.md` "C2A victim-detection adapter" section:

- **Top-level `README.md` owns:** runtime integration. How the demo loads the adapter, the `--c2a-adapter-path` CLI flag, the in-process route via `agents/drone_agent/c2a_inference.py`, where weights live for the running system.
- **`ml/README.md` owns:** the `ml/` subtree structure itself. What each subdir is for (`ml/data_prep/`, `ml/evaluation/`, `ml/training/`, `ml/adapters/`), which scripts run when, where outputs land, what's intentionally empty in-repo (e.g., `ml/adapters/` is empty because adapters live in `kaggle_out_c2a/adapter/` or are pulled from Kaggle).

If you need to mention the runtime integration in `ml/README.md`, link to the top-level README section rather than duplicating it.

### Current state

`ml/README.md` does not exist. The `ml/` tree contains:
- `ml/adapters/` — empty, `.gitkeep` only
- `ml/data_prep/` — xBD prep scripts (`crop_patches.py`, `download_xbd.py`, `format_for_gemma.py`, `split_dataset.py`)
- `ml/evaluation/` — `eval_adapter.py`, `eval_wow_moment_trigger.py`, `runners.py`, `tests/`
- `ml/training/` — (skeleton only)

### Target

New `ml/README.md` (~80-120 lines) that:
1. Names the active fine-tuning path: C2A victim detection, scaffold at `kaggle_work_c2a/`, output at `kaggle_out_c2a/adapter/`.
2. Names the historical/insurance path: xBD building damage, scaffold at `kaggle_work/`, not loaded by the demo.
3. Points to the published Kaggle Model: `ibrahimahmed7860/gemma4-e2b-victim-vision-lora-c2a` `Transformers/lora-c2a-bf16/3`.
4. Points to the inference integration: `agents/drone_agent/c2a_inference.py` + `--c2a-adapter-path` CLI flag.
5. Briefly describes each `ml/` subdir's purpose so a fresh reader doesn't have to grep.
6. States that `ml/adapters/` is intentionally empty in-repo (adapters live in `kaggle_out_c2a/adapter/` or are pulled from Kaggle).
7. Honest disclosure on Unsloth special-prize eligibility: yes (training pipeline uses Unsloth `FastVisionModel`); but adapter-via-Ollama claim is dead per #2290, so no Ollama special-prize claim.

### Testing

- Link check (same grep as G5)
- `cd ml && cat README.md` reads cleanly cold
- No promises of files that don't exist (e.g., don't reference `ml/adapters/lora-c2a-bf16.safetensors` if it's not there)

### Done criteria

- [ ] `ml/README.md` exists
- [ ] All referenced files actually exist OR are clearly marked as "pulled from Kaggle Model"
- [ ] Kaggle Model + Notebook links resolve
- [ ] Mentioned in top-level `README.md` § "C2A victim-detection adapter" (already updated by subagent — verify the link survives)

---

## C8 J6 — Beef up `docs/12-fine-tuning-plan.md` 2026-05-14 addendum (docs, ~30 min)

### Current state

`docs/12-fine-tuning-plan.md` lines 1-14 — 12-line addendum at top, body lines 16-328 still all-xBD. C2A is mentioned as "pivot footnote" but the substantive plan is xBD.

### Target

Promote the addendum from footnote → canonical. Restructure top of file so a fresh reader sees C2A first, xBD second.

### Proposed structure

1. **Top of file (replace current lines 1-14):**
   - New top section: `## What We Shipped (C2A victim-detection LoRA, 2026-05-15)`
   - ~50-line "canonical path" summary: dataset, hyperparameters, results, published artifacts, inference integration, compat shims, lessons learned
   - Then a clear divider: `## Historical xBD Plan (kept for archaeology)` introducing the rest

2. **Body (existing lines 16-328):**
   - Keep as-is but wrap with a banner at line 16-ish: `> The plan below is the **original xBD building-damage path** drafted 2026-04-29. We ran it as belt-and-suspenders insurance — adapter scaffold lives at \`kaggle_work/\`. The hackathon's primary GATE 3 path moved to C2A 2026-05-14; see "What We Shipped" above for the canonical record.`

3. **At the bottom, add:**
   - `## What Didn't Ship + Future Work` mirroring the C8 G5 final subsection

### Content for the new top section (draft)

```
## What We Shipped (C2A victim-detection LoRA, 2026-05-15)

### Final dataset choice
- **Train (victim):** C2A (`rgbnihal/c2a-dataset`) — 10,215 UAV images, ~360k human
  instances across four disaster scenarios.
- **Train (none):** AIDER (`samik2005/aider-dataset`) — disaster-context images
  with no human subjects.
- **Held-out cross-source:** SARD (`nikolasgegenava/sard-search-and-rescue`) — for
  honest domain-transfer evaluation. n=100 SARD samples included in the n=400
  held-out eval split.
- **Schema:** binary, `{finding_type: "victim" | "none", confidence, visual_evidence}`,
  collapsing C2A's bounding-box annotations to image-level for our `report_finding`
  contract.

### Final hyperparameters (v11, published)
- Base: `unsloth/gemma-4-E2B-it`
- LoRA: DoRA enabled (`use_dora=True`), rank 16, alpha 32, dropout 0.05,
  `target_modules="all-linear"`, `finetune_vision_layers=True`
- Optimizer: lr 2e-4 cosine, fp16 (Kaggle T4 doesn't support bf16)
- Training: 300 steps, ~49 min on a single Kaggle T4 free instance

### Final results (n=400 held-out, `kaggle_out_c2a/adapter/eval_summary.json`)
| Metric | Value |
|---|---|
| Binary accuracy | 77.25% |
| Victim F1 | 0.78 (precision 0.79, recall 0.77) |
| Parse-rate (ok) | 100% |
| C2A per-source accuracy | 97.2% |
| AIDER per-source accuracy | 77.5% |
| SARD per-source accuracy (held out) | 55% |

The +13pp SARD lift over v9 (42% → 55%) came from fixing a label-collapse bug
in v10 — fixed-string `visual_evidence` labels were producing a trivial
shortcut (loss → 0.0004 in 25 steps). v10's fix used scenario-keyed varied
evidence templates and varied confidence values.

### Published artifacts
- Kaggle Model: [`gemma4-e2b-victim-vision-lora-c2a`](https://www.kaggle.com/models/ibrahimahmed7860/gemma4-e2b-victim-vision-lora-c2a)
  `Transformers/lora-c2a-bf16/3` — PUBLIC.
- Kaggle Notebook: [`gemma-4-e2b-victim-vision-lora-c2a-disaster`](https://www.kaggle.com/code/ibrahimahmed7860/gemma-4-e2b-victim-vision-lora-c2a-disaster)
  — PUBLIC, with C2A + AIDER + SARD dataset citations rendered in the Inputs panel.

### Inference integration
- Route (a) Ollama Modelfile is dead per [Unsloth #2290](https://github.com/unslothai/unsloth/issues/2290)
  — vision-tower export regresses; no GGUF path for Gemma 4 vision LoRA today.
- Route (b) PEFT/HF Transformers shipped in `agents/drone_agent/c2a_inference.py`.
  Wired into `DroneAgent.step()` as fast-path before the Ollama reasoning call.
- Two non-trivial Unsloth↔PEFT compat shims required:
  - `Gemma4ClippableLinear` unwrap: vanilla PEFT can't inject LoRA into Unsloth's
    custom wrapper class. We walk the base model post-load and `setattr` the
    inner `nn.Linear` on every 232 wrapped layers.
  - DoRA magnitude-vector key rename: Unsloth saves DoRA tensors as
    `…lora_magnitude_vector.default` (no `.weight` suffix); vanilla
    `PeftModel.from_pretrained` expects `.default.weight`. We load the
    safetensors file, rename in memory, save to a temp dir, then load via PEFT.
- CLI flag `--c2a-adapter-path` defaults to `$C2A_ADAPTER_PATH` env var or
  `kaggle_work_c2a/adapter/`. Adapter-load failure → graceful fallback to
  Ollama-only mode (demo never crashes).

### Lessons learned
- Unsloth + DoRA is the right training-time choice for hackathon timeboxes
  (T4 fit in ~49 min, +13pp SARD over plain LoRA). The save/load contract
  with vanilla PEFT is a known fragility; budget time for the inference-side
  shims when planning future trainings.
- Label-collapse bug pattern: when training-time labels are fixed strings,
  loss can converge to a trivial shortcut. Vary evidence/confidence per
  example.
- SARD is the right honest domain-transfer benchmark — it's not in C2A's
  training distribution and exposes overfit risk cleanly.
```

### Testing

- Same link-check grep
- Cross-doc consistency with `WRITEUP.md` §6, `docs/22-writeup-draft.md` §7, `ml/README.md`, `kaggle_out_c2a/adapter/eval_summary.json`
- Read-aloud pass

### Done criteria

- [ ] New "What We Shipped" top section is the canonical record
- [ ] Historical xBD plan clearly labeled as such
- [ ] Numbers match all sibling docs (single source of truth: `eval_summary.json`)
- [ ] All links resolve
- [ ] No remaining "TBD" / "pivot in progress" language

---

## Order of operations (Fri PM → Sat AM)

| Order | Item | Why | Time |
|---|---|---|---|
| 1 | C7 (code change + tests) | Code-freeze pressure; everything else is docs and slides | 30 min |
| 2 | C8 J6 fine-tuning plan addendum | Becomes the canonical source for the other docs to reference | 30 min |
| 3 | C8 G5 §7 rewrite in 22-writeup-draft | Pulls from J6 canonical | 30 min |
| 4 | C8 J2 `ml/README.md` | Links into J6 + G5 — best last | 20 min |
| 5 | Cross-doc consistency sweep | One final pass after all are written | 15 min |

Total ~2 hr 5 min. Fits inside Fri evening; Sat AM remains for dress rehearsal + drone3 reliability + freeze prep.

---

## Cross-cutting test plan

After all four items land:

```bash
# 1. Test suite green
uv run pytest agents/egs_agent/tests/ agents/drone_agent/tests/ -x -q

# 2. No broken relative links in any of the four files we touched
for f in agents/egs_agent/command_translator.py \
         docs/22-writeup-draft.md \
         ml/README.md \
         docs/12-fine-tuning-plan.md; do
  echo "--- $f ---"
  grep -oE '\[.*\]\(([^h)][^)]*)\)' "$f" 2>/dev/null || true
done

# 3. Numbers consistency — every doc cites the same v11 stats
grep -nH "77.25\|0\.78\|97\.2\|77\.5\|SARD 55" \
  WRITEUP.md docs/22-writeup-draft.md docs/12-fine-tuning-plan.md ml/README.md

# 4. No stray "xBD" mentions in the canonical-path sections of doc updates
#    (only allowed in clearly-historical subsections)
```

---

## Done definition

All four items meet their per-item done-criteria AND:
- [ ] Single commit on `main` titled `feat: C7 timeout hoist + C8 docs cleanup (canonical C2A path)`
- [ ] `docs/plans/2026-05-15-remaining-work-to-submission.md` Track C reflects C7 + C8 as `[x]` with commit SHA
- [ ] `TODOS.md` L43-49 entry struck through with closure note
- [ ] No regression in any `pytest agents/` lane

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 6 issues raised, 5 applied (2A naming parity, 2B regex limit doc, 2C boil-the-lake J6, 2D J2 boundary, 3A test-name enumeration). 0 critical gaps. 1A constants module skipped (not worth it). 1B/3B optional, deferred. |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

**UNRESOLVED:** 0
**VERDICT:** ENG CLEARED — ready to implement.
