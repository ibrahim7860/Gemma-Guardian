# `ml/` — Fine-Tuning Subtree

This directory holds the **training-time** code for FieldAgent's vision LoRA
work. Runtime integration (how the running drone agent loads the adapter,
the `--c2a-adapter-path` CLI flag, the in-process PEFT route) is documented
in the top-level [`README.md`](../README.md) under "C2A victim-detection
adapter" — this README does **not** duplicate that content; it documents
the subtree itself so a fresh reader can navigate without grepping.

## Active path: C2A victim detection (shipped)

The canonical record of the shipped LoRA is in
[`../docs/12-fine-tuning-plan.md`](../docs/12-fine-tuning-plan.md)
("What We Shipped") and [`../WRITEUP.md`](../WRITEUP.md) §6. Quick pointers:

- **Training scaffold:** `kaggle_work_c2a/` at the repo root (not under
  `ml/`) — Kaggle notebook + data-prep scripts tailored to the Kaggle T4
  free-tier environment.
- **Trained adapter (local):** `kaggle_out_c2a/adapter/` at the repo root.
  Contains `adapter_model.safetensors`, `adapter_config.json`, and the
  `eval_summary.json` that backs every number cited in the writeup.
- **Trained adapter (public):** Kaggle Model
  [`ibrahimahmed7860/gemma4-e2b-victim-vision-lora-c2a`](https://www.kaggle.com/models/ibrahimahmed7860/gemma4-e2b-victim-vision-lora-c2a)
  under `Transformers/lora-c2a-bf16/3` (PUBLIC, ~120 MB).
- **Training notebook (public):**
  [`gemma-4-e2b-victim-vision-lora-c2a-disaster`](https://www.kaggle.com/code/ibrahimahmed7860/gemma-4-e2b-victim-vision-lora-c2a-disaster).
- **Runtime loader:** `agents/drone_agent/c2a_inference.py`. See the
  top-level [`README.md`](../README.md) for how the demo wires this in.

## Historical / insurance path: xBD building damage

The original Day 1 plan was xBD-based building-damage classification. That
work survives in the repo for archaeology and post-submission extension but
is **not loaded by the running demo**.

- **Training scaffold:** `kaggle_work/` at the repo root.
- **Data-prep code:** the scripts under `ml/data_prep/` (see below) are
  xBD-shaped. The C2A pipeline does its own data prep inside its Kaggle
  notebook and does not reuse these scripts.
- **Why kept:** belt-and-suspenders insurance during the 2026-05-14 pivot;
  documented in [`../docs/12-fine-tuning-plan.md`](../docs/12-fine-tuning-plan.md)
  under "Historical xBD Plan".

## Subdirectory map

| Path | Purpose | Status |
|---|---|---|
| `ml/adapters/` | Intentionally empty in-repo. Adapters live in `kaggle_out_c2a/adapter/` (local) or are pulled from the Kaggle Model (public). Contains only `.gitkeep`. | Empty by design |
| `ml/data/` | Local data scratch directory. Not committed; populated by the xBD data-prep scripts. | Scratch |
| `ml/data_prep/` | xBD-shaped data-prep utilities. Used by the historical xBD path; the C2A path runs its own prep inside the Kaggle notebook. | Historical (xBD path) |
| `ml/training/` | Training entry points. `finetune_lora.py` is the xBD-side trainer; `verify_unsloth.py` is the environment smoke test. The C2A trainer lives in the published Kaggle notebook, not in-repo. | Historical (xBD path) |
| `ml/evaluation/` | Eval harness for the trained adapter and for the wow-moment trigger experiments. `eval_adapter.py` (xBD-side), `eval_wow_moment_trigger.py` (used to measure base-E4B trigger rate, cited in WRITEUP §6.5 / draft §7.6), `runners.py`, and `tests/`. | Active |

### `ml/data_prep/` contents

| Script | Purpose |
|---|---|
| `download_xbd.py` | Pulls the xBD dataset to `ml/data/xbd_raw/`. |
| `crop_patches.py` | Crops per-building 224×224 patches from xBD post-event imagery. |
| `split_dataset.py` | Disaster-grouped train/val/test split (no random shuffling across disasters). |
| `format_for_gemma.py` | Renders cropped patches + Joint Damage Scale labels into the Gemma 4 chat format. |

### `ml/training/` contents

| Script | Purpose |
|---|---|
| `verify_unsloth.py` | Environment smoke test — confirms Unsloth + CUDA + Gemma 4 base load on a fresh machine. Safe to run before any actual training. |
| `finetune_lora.py` | xBD-side LoRA trainer (rank 32, all-linear, bf16). Not the C2A path. |

### `ml/evaluation/` contents

| Script | Purpose |
|---|---|
| `eval_adapter.py` | xBD-side eval harness; emits per-class F1 and accuracy on the held-out split. |
| `eval_wow_moment_trigger.py` | Measures base Gemma 4 E4B's `ASSIGNMENT_TOTAL_MISMATCH` trigger rate on the wow-moment replan scenario. Source of the "0 / 7" disclosure in `WRITEUP.md` §6.5 and `docs/22-writeup-draft.md` §7.6. |
| `runners.py` | Shared eval helpers. |
| `tests/` | Unit tests for the eval harness. |

## Output locations (where things land)

- xBD raw data: `ml/data/xbd_raw/` (not committed)
- xBD prepared patches: `ml/data/xbd_prepared/` (not committed)
- xBD adapter (if trained): would land in `ml/adapters/xbd-lora/` (not present at submission)
- C2A adapter: `kaggle_out_c2a/adapter/` at repo root (committed; weights tracked via Git LFS / Kaggle Model)
- Eval reports: `kaggle_out_c2a/adapter/eval_summary.json`

## Numbers at a glance (C2A v11, n=400)

| Metric | Value |
|---|---|
| Binary accuracy | 77.25% |
| Victim F1 | 0.78 (precision 0.79, recall 0.77) |
| Parse-rate (`ok`) | 100% |
| C2A per-source accuracy | 97.2% |
| AIDER per-source accuracy | 77.5% |
| SARD per-source accuracy (held out) | 55% |

Source of truth: `kaggle_out_c2a/adapter/eval_summary.json`. Any doc that
disagrees with this file is wrong; this file wins.

## Hackathon special-prize eligibility (honest)

- **Unsloth — yes.** The training pipeline uses Unsloth `FastVisionModel`
  end-to-end (DoRA, `target_modules="all-linear"`,
  `finetune_vision_layers=True`). Single-GPU sub-hour fine-tune on Kaggle
  T4 free-tier is real, reproducible from the public notebook.
- **Ollama — partial.** Base Gemma 4 E2B / E4B are served via Ollama in
  the running demo. The adapter itself is **not** served through Ollama —
  the GGUF vision-tower export path is broken upstream
  ([Unsloth #2290](https://github.com/unslothai/unsloth/issues/2290)). The
  adapter rides a PEFT/HF Transformers in-process path
  (`agents/drone_agent/c2a_inference.py`). We do not claim
  adapter-via-Ollama.

## Pointers

- Canonical fine-tuning record: [`../docs/12-fine-tuning-plan.md`](../docs/12-fine-tuning-plan.md)
- Writeup (1500-word): [`../WRITEUP.md`](../WRITEUP.md) §6 + §6.5
- Writeup (long-form draft): [`../docs/22-writeup-draft.md`](../docs/22-writeup-draft.md) §7
- Runtime integration: [`../README.md`](../README.md) "C2A victim-detection adapter"
- Runtime loader code: [`../agents/drone_agent/c2a_inference.py`](../agents/drone_agent/c2a_inference.py)
