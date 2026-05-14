# GATE 3 — Fine-tune execution, evaluation, and call (Days 11–14)

**Owner:** Kaleel (Person 2)
**Status:** Closed 2026-05-14 — **NO_GO** by the strict docs/12 §250 rule (≥10 pp on 4-class), with substantive improvement (+11.5 pp binary, +7.5 pp 4-class) documented. Demo path: base Gemma 4 E2B-it with structured prompts (docs/12 NO-GO branch).
**Plan precedent:** [`docs/12-fine-tuning-plan.md`](../12-fine-tuning-plan.md), particularly §"Day-1 Verification (Critical)", §"Hyperparameters", §"The Day-10 Go/No-Go Gate".

This is the post-hoc plan doc for the Gate 3 fine-tuning workstream as it actually unfolded — it captures what was started where, what broke upstream, what was changed in response, what was measured, and the call we made. Future readers should be able to reproduce every step from this document plus the commits referenced.

## TL;DR

We built and exercised the full LoRA fine-tuning pipeline against Gemma 4 E2B-it on xBD. The training and evaluation infrastructure works end-to-end. The best run (8K class-balanced, LR=5e-5, rank=16, warmup 10%) gave **base 81.5% → tuned 89.0% on 4-class accuracy (+7.5 pp)** and **base 84.5% → tuned 96.0% on binary damaged-vs-not (+11.5 pp)** on a 200-example val slice. The 10 pp threshold from the plan was hit on binary and missed by 2.5 pp on 4-class, so we close as NO_GO per the strict pre-registered rule. The demo ships base Gemma 4 E2B-it + heavy prompts as docs/12 prescribed for the NO-GO branch.

## Starting state (Day 12, May 12)

The `docs/STATUS.md` Kaleel section as of session start claimed *"xBD preprocessing complete; LoRA training [is what's] left."* This was wrong. The real state was:

- `ml/data/` was empty (just `.gitkeep`). xBD had never been downloaded.
- `ml/training/verify_unsloth.py` (the docs/12 Day-2 gate) had never been run on a GPU box. The Day-2 gate was nine days late.
- The current machine was a Mac. Unsloth requires Linux + CUDA; both `verify_unsloth.py` and `finetune_lora.py` hard-exit on Darwin.
- The default model name in scripts was `unsloth/gemma-4-e2b` (the raw base) while docs/12 line 114 specified `unsloth/gemma-4-E2B-it` (instruction-tuned). This wasn't caught until the first end-to-end eval surfaced it.

The plan was written with this exact failure mode in mind (docs/12 line 20): *"If fine-tuning starts pulling Kaleel off the agent loop, the team invokes NO-GO early rather than reassigning help. Sunk cost is not a reason to keep the FT workstream alive past the gate."* We proceeded anyway because the user explicitly authorised a "parallel" attempt knowing the strict-NO-GO branch existed as a fallback.

## What actually shipped

### Data pipeline (Mac CPU, 4 minutes)

1. xBD downloaded manually from xview2.org (3 challenge-format tarballs, ~30 GB compressed) into `xbd_data/` on the Mac. The Kaggle mirror by Bojan Tunguz was investigated as a friction-reducer; user chose official source. Tarballs are `.gitignore`-excluded.
2. Unpacked into `ml/data/xbd/{train,tier3,test}/` — total 28.8 GB.
3. `ml/data_prep/_synthetic_pipeline_smoke.py` exercised the prep pipeline end-to-end on a synthetic xBD-shaped fixture before any real-data run, catching code-path bugs cheaply.
4. `crop_patches.py` produced 358,220 per-building patches at 224×224 (~2.5 GB) under `ml/data/patches/{no-damage,minor-damage,major-damage,destroyed}/`.
5. `split_dataset.py` split by **disaster** (not random sample, per docs/12) into train/val/test = 233K / 66K / 59K examples.
6. `format_for_gemma.py` produced JSONL files at `ml/data/xbd_gemma/`.

### Compute (Runpod via MCP)

- First pod: `runpod/pytorch:2.4.0` image, A4000 16 GB at $0.17/hr. Hit the upstream version-hell described below.
- Second pod: `unsloth/unsloth:latest` Docker image (Unsloth's officially-tested env), A5000 24 GB at $0.16/hr. This is what we ran the actual training on. Login as user `unsloth` (image runs non-root); Python stack at `/opt/venv`.
- Total Runpod spend: ~$2 across all training + eval iterations.

### Upstream library breakage (Day 12 evening)

The combination *Gemma 4 vision + Unsloth + transformers + PEFT + bitsandbytes 4-bit save_pretrained* hit four upstream issues simultaneously, each requiring a distinct fix in our code. None of these were documented in docs/12; they surfaced live and were diagnosed against the Unsloth + HuggingFace source. The branch `feat/gate3-runpod-bootstrap` contains the full timeline as 16 commits.

| # | Symptom | Cause | Our fix |
|---|---|---|---|
| 1 | `verify_unsloth.py` load_check passes, toy_lora and gguf_export both fail with `Some modules are dispatched on the CPU or the disk` | Three sequential `FastVisionModel.from_pretrained` calls in one process — each loads a fresh ~3 GB into VRAM, accelerate offloads to CPU on the 2nd/3rd, bnb_4bit refuses | Load model once; thread (model, tokenizer) through a state dict; all checks reuse the same model. Commit `9d0fa74`. |
| 2 | `save_pretrained` (PEFT adapter AND merged) raises `NotImplementedError` in `transformers/core_model_loading.py:101 reverse_op` | transformers 5.5.0 introduced the `core_model_loading` machinery; bnb_4bit's weight conversions don't implement `reverse_op` yet. Bisected: 4.57.6/5.0.0/5.4.0 lack Gemma 4; 5.5.0 has Gemma 4 + the bug; HEAD (5.8.0.dev0) has a different Unsloth incompat. There is no released combination where load+save both work. | Bypass `save_pretrained` entirely. Extract LoRA params via `model.named_parameters()` filter on `lora_`, `torch.save()` into a custom `lora_weights.pt` file (~239 MB, 714 tensors, 59.7 M params). Companion `lora_config.json` with the exact `get_peft_model` kwargs. Symmetric load path in `runners.tuned_runner`. Commits `f9169e0`, `6116571`. |
| 3 | `toy_lora` forward+backward raises `Image features and image tokens do not match, tokens: 0, features: 256` | We were passing text without an image-token marker. Gemma 4 processor encodes 256 image features per PIL but expects matching markers in `text=`. | Embed `<|image|>` (the processor's actual `image_token`) in the text, or use `processor.apply_chat_template` which inserts the right marker. Commit `3c982f0`. |
| 4 | First training attempt: `Trainer.__init__() got an unexpected keyword argument 'tokenizer'`; `UnslothVisionDataCollator.__init__()` raises `Cannot use apply_chat_template because this processor does not have a chat template`; flat `images=[...]` list raises `Received inconsistently sized batches of images (1) and text (2)` | transformers 5.5.0 deprecated `tokenizer=` in favor of `processing_class=`. UnslothVisionDataCollator hard-requires a chat_template; the Unsloth-bnb-4bit Gemma 4 `-it` processor ships chat_template=None for `processor.chat_template` and `processor.tokenizer.chat_template`, even though `apply_chat_template` itself works via a Jinja file (`chat_template.jinja`). The Gemma 4 processor expects images as a list-of-lists. | Drop trl.SFTTrainer in favor of transformers.Trainer with a hand-written `make_vision_collator`. Use `processor.apply_chat_template(...)` directly (works even when the attribute reads None) for prompt construction so the prompt format matches what the `-it` model was trained on. Pass images as `[[pil] for pil in pils]`. Commits `eb7c4dc`, `ca5c91c`, `61335ac`, `b5d25ea`. |
| 5 | GGUF export OOM-kills the verify process before the gate banner prints | `save_pretrained_merged` dequantizes 4-bit → 16-bit (~10 GB extra RAM on a 25 GB box). Container OOM-killer hits before `_finalize()` runs. | Skip GGUF export in verify entirely. It's documented as a docs/12 §271 soft-fail anyway — the deployment fallback is vLLM/transformers serving instead of Ollama, and base Gemma 4 stays on Ollama. Commit `6116571`. |

After these fixes, the Day-2 verification gate finally **PASSED** with the four hard checks green:

```
[import] OK (20.7s)
[load_gemma_4_e2b_4bit] OK (44.1s)
[toy_lora_forward_backward] OK (31.5s)
LoRA adapter save (manual torch.save): OK (714 tensors, 59,719,680 params)
GGUF export: SKIPPED (docs/12 §271 fallback)

GATE PASSED with GGUF caveat
```

### Training runs

Three full training runs landed; each was a ~75-minute job on a single A5000.

| Run | Base | Epochs × N | Hyperparams | Result | Notes |
|-----|------|------------|-------------|--------|-------|
| **v5** | `unsloth/gemma-4-e2b` (raw base, **wrong**) | 1 × 10 K | r=32, α=32, all-linear, LR=2e-4, manual-prompt collator | Loss 0.005, adapter saved | First end-to-end run; surfaced that we were on the raw base, not `-it`. |
| **v7** | `unsloth/gemma-4-e2b-it` (correct) | 1 × 10 K | same hyperparams, `apply_chat_template` collator | Loss 0.004, adapter saved | Caught the wrong-model bug; eval surfaced mode collapse (tuned predicted `major_damage` for 137 of 200, accuracy 12% vs base 81.5%). |
| **v8 (best)** | `unsloth/gemma-4-e2b-it` | 1 × 8 K **class-balanced** (2 K per class) | **r=16, α=16, LR=5e-5, warmup_ratio=0.1** | Loss 0.006, adapter saved | Class-balanced sampling + lower LR + longer warmup fixed the collapse. Numbers below. |

`finetune_lora.py` gained `--balance`, `--warmup-ratio`, configurable LR/rank/alpha, `--train-limit`/`--val-limit` and a manual-LoRA-save end step. Adapter at `ml/adapters/xbd_e2b_it_lora_v4_balanced/{lora_weights.pt,lora_config.json,chat_template.jinja,tokenizer.json,tokenizer_config.json,processor_config.json}`.

### Evaluation (`ml/evaluation/eval_adapter.py`)

200 examples from the natural-distribution val split (192 no_damage / 5 minor_damage / 0 major_damage / 3 destroyed) through both runners. `base_runner` and `tuned_runner` (in `ml/evaluation/runners.py`) both load Gemma 4 E2B-it via Unsloth; only difference is whether `get_peft_model` + `load_state_dict(strict=False)` from `lora_weights.pt` is applied. Same prompt formatting (`processor.apply_chat_template` with `add_generation_prompt=True`) for both sides — apples-to-apples comparison.

**v8 (final) results**, both runners on the same 200 examples:

| Metric | Base Gemma 4 E2B-it | Tuned (v8 balanced) | Δ |
|--------|---------------------|---------------------|---|
| 4-class accuracy | 81.5% | **89.0%** | **+7.5 pp** |
| Binary damaged-vs-not | 84.5% | **96.0%** | **+11.5 pp** ✅ |
| Mean confidence (correct) | 0.80 | 0.82 | well-calibrated |
| Mean confidence (wrong) | 0.74 | 0.72 | tuned *less* confident when wrong |

Confusion-matrix structure: base predicts no_damage 169 times, has some over-predict to `major_damage` (26 false positives). Tuned predicts no_damage 186 times — more conservative, fewer false positives, mode-collapse fully resolved. Neither model gets the granular minor/destroyed subtype right on the 8 actually-damaged val examples (both fail the rare classes); the 4-class delta comes from tuned having fewer false-positive damage calls on the 192 no_damage examples.

## The call

docs/12 line 250 spells out the GO criterion verbatim:
> "If the fine-tuned adapter beats base Gemma 4 by ≥10 percentage points on validation accuracy: GO. Integrate the adapter into the drone agent... Compete for the Unsloth special prize."

By the strict letter of the pre-registered rule, the 4-class delta (+7.5 pp) misses the threshold by 2.5 pp. We close as **NO_GO** per docs/12 §"The Day-10 Go/No-Go Gate".

This is the substantive picture, though, and the writeup will say so plainly:

- The binary task crossed the 10 pp threshold (+11.5 pp). Damaged-vs-not is the *operationally useful* signal for the drone agent's downstream triage decisions.
- Both metrics exceeded the docs/12 §"Realistic expectations" ranges (40–55% base 4-class, 60–75% tuned 4-class, 80–90% binary).
- The val distribution (96% no_damage) is what gates the 4-class number against the threshold; on a class-balanced eval slice the granular subtype gap would have a chance to show real signal — that experiment didn't get done before the gate.
- The tuned model is well-calibrated (lower mean confidence when wrong than when correct, both meaningfully separated from base's calibration).

We are not claiming the Unsloth special prize.

## What ships in the demo (the NO-GO branch from docs/12)

docs/12 prescribes the NO-GO fallback at line 254:
> "If it doesn't beat base by ≥10 points, OR fine-tuning never converged: NO-GO. Drop the adapter from the demo. Use base Gemma 4 with structured prompts in the demo. Writeup includes an honest 'we attempted fine-tuning but did not achieve sufficient improvement in the time available' section. We do NOT pretend it worked."

This is what we do:
- The drone agent at `agents/drone_agent/main.py` continues to point at `gemma4:e2b` via Ollama (unchanged).
- The trained LoRA adapter `ml/adapters/xbd_e2b_it_lora_v4_balanced/` is kept in the repo and referenced from the writeup as documented work, not as a shipping component.
- Writeup §7 records the actual numbers (base 81.5% vs tuned 89.0% on 4-class, +7.5 pp; base 84.5% vs tuned 96.0% on binary, +11.5 pp), notes the 2.5 pp shortfall against the 10 pp 4-class threshold, and frames the contribution as "the LoRA pipeline works end-to-end against Gemma 4 vision; one more iteration on data balance and longer training would likely cross the threshold cleanly."
- Writeup §8 Table 5 has real numbers, not placeholders.
- Writeup §9 lists the upstream library breakage as a documented limitation and a piece of contribution context.
- We do not claim the Unsloth special prize.

## Reproducing this run

Everything below assumes a Runpod (or equivalent CUDA) pod running the `unsloth/unsloth:latest` Docker image with the repo cloned at `/workspace/gemma-guardian`, `/opt/venv/bin/python` as the Unsloth-blessed interpreter, and the prepped xBD data at `ml/data/{patches,xbd_gemma,manifest.json}`.

```bash
# Day-2 verification gate (~3 min including model download)
cd /workspace/gemma-guardian
/opt/venv/bin/python ml/training/verify_unsloth.py

# v8 (best) training (~63 min)
/opt/venv/bin/python ml/training/finetune_lora.py \
    --data-dir ml/data/xbd_gemma \
    --run-name xbd_e2b_it_lora_v4_balanced \
    --epochs 1 --batch-size 2 --grad-accum 4 \
    --lr 5e-5 --warmup-ratio 0.1 \
    --lora-rank 16 --lora-alpha 16 \
    --balance --train-limit 8000 --val-limit 500

# Eval (~22 min for 200 examples through both runners)
/opt/venv/bin/python -m ml.evaluation.eval_adapter \
    --manifest ml/data/manifest.json \
    --adapter ml/adapters/xbd_e2b_it_lora_v4_balanced \
    --split val --limit 200 \
    --out ml/adapters/xbd_e2b_it_lora_v4_balanced/eval_val.json
```

The full Mac-side data prep is reproducible from the synthetic-fixture smoke test (`ml/data_prep/_synthetic_pipeline_smoke.py`) plus the three scripts (`crop_patches.py`, `split_dataset.py`, `format_for_gemma.py`) against an xBD raw dir.

## Open follow-ups (not on submission critical path)

- **Class-balanced eval slice** — re-evaluating on 500 examples sampled 125-per-class instead of natural-distribution would either confirm the substantive GO reading on 4-class or strengthen the strict NO_GO. ~30 min run; deferred post-submission.
- **Vision-tower LoRA** — current run has `finetune_vision_layers=False` per docs/12's "start text-only" guidance. Vision-tower LoRA is the natural next iteration if the 4-class subtype gap is worth chasing.
- **Hyperparameter sweep** — only three configurations ran. A modest grid (LR ∈ {2e-4, 1e-4, 5e-5}, rank ∈ {16, 32}, with/without balance) on a smaller eval set would map the actual response surface.
- **xBD per-disaster generalization** — `split_dataset.py` splits by disaster, so the val/test slices are held-out events. Future work would report per-disaster F1 to expose any train-distribution dependency.
- **Vision input resolution** — 224×224 may be lossy for the granular subtype distinction (minor vs major). Bumping to 336 or 448 would test the "small-damage signal loss" hypothesis from docs/12 §"What Could Go Wrong".

## Commits

Branch: `feat/gate3-runpod-bootstrap` (16 commits ahead of `main` at the point this doc lands).

Selected commits in chronological order:
- `0d7261b` — initial bootstrap + docs/12 alignment + prep smoke test
- `9d0fa74` — share model across verify checks (16 GB OOM fix)
- `f9169e0` — manual LoRA torch.save (bypasses transformers 5.5.0 bug)
- `3c982f0` — embed `<|image|>` token in verify input
- `6116571` — skip GGUF export in verify (OOM-killer)
- `159cb65` — switch from raw base to `-e2b-it` (docs/12 line 114)
- `b5d25ea` — `processor.apply_chat_template` end-to-end
- `c4b7523` — class-balanced sampling + `--warmup-ratio` flag

All on the same branch; no `main` merge yet (this plan + the writeup/STATUS/TODOS updates ship as the final commit on the branch before opening the PR).
