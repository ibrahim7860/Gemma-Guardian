# Gate 3 deliverables — `xbd_e2b_it_lora_v4_balanced`

Everything Ibrahim's review asked for, in one place. Last updated 2026-05-14.

## Files in `ml/adapters/xbd_e2b_it_lora_v4_balanced/`

| File | What it is | Purpose |
|---|---|---|
| `lora_weights.pt` | torch.save'd state dict (714 tensors, 59.7 M params, 239 MB) | Custom format because `transformers 5.5.0` `save_pretrained` is broken on bnb_4bit (see docs/plans/2026-05-14-gate3-fine-tune-run-and-call.md). Loadable via `model.load_state_dict(strict=False)` on a `get_peft_model`-wrapped base. |
| `lora_config.json` | The exact `get_peft_model` kwargs + training metadata | Source of truth for hyperparameters. |
| `chat_template.jinja` | Saved alongside the tokenizer | Gemma 4 chat template (the `-it` tokenizer ships one even though `processor.chat_template` reads None). |
| `tokenizer.json`, `tokenizer_config.json`, `processor_config.json` | Tokenizer + processor side files | Saved via `processor.save_pretrained` for reproducibility. |
| `eval_val.json` | 200-example val results, base vs tuned | Aggregate metrics from `ml/evaluation/eval_adapter.py`. |
| `behavioral_victim_test.json` | 3-run-each base vs tuned on `placeholder_victim_01.jpg` | The behavioral test from Ibrahim's review. |
| `peft_format/` | Standard PEFT/HF directory (`adapter_config.json` + `adapter_model.safetensors`) | Produced by `python -m ml.training.convert_to_peft_format`. Loadable via `PeftModel.from_pretrained(base, adapter_dir)`. |

## Exact hyperparameters used (the "different method")

From `lora_config.json`:

```json
{
  "base_model": "unsloth/gemma-4-e2b-it",
  "lora_kwargs": {
    "finetune_vision_layers": false,
    "finetune_language_layers": true,
    "finetune_attention_modules": true,
    "finetune_mlp_modules": true,
    "target_modules": "all-linear",
    "r": 16,
    "lora_alpha": 16,
    "lora_dropout": 0.0,
    "bias": "none",
    "random_state": 42,
    "use_rslora": false,
    "use_gradient_checkpointing": "unsloth"
  },
  "training_kwargs": {
    "epochs": 1,
    "batch_size": 2,
    "grad_accum": 4,
    "lr": 5e-5,
    "train_examples": 8000,
    "elapsed_hours": 1.04
  }
}
```

**Deviations from docs/12 §"Hyperparameters" (and why):**

| docs/12 | What we ran | Why |
|---|---|---|
| `r = 32, alpha = 32` | r=16, alpha=16 | The first run on docs/12's hyperparams (v7) hit mode collapse predicting `major_damage` for 137 of 200 val examples. Halved rank to reduce LoRA's ability to memorize a single majority class. |
| LR `2e-4` | `5e-5` | Same reason — slower LR + smaller rank breaks the over-fit-to-train-majority dynamic. |
| `warmup_ratio = 0.03` (implicit) | `0.1` | Longer warmup stabilizes early optimization on small balanced batches. |
| `~500K patches, 1-3 epochs` | 8 K class-balanced, 1 epoch | We balanced 2 K per class × 4 classes from the 233 K-example train set, single epoch. Time budget: this is a 63-min run on an A5000. The plan's 500 K × 3 was a multi-day run; we did not have that window. |
| `finetune_vision_layers = False` (start) | same | Kept per docs/12's "start text-only" guidance. |

## Exact training script

`ml/training/finetune_lora.py` — reproduction command on a Runpod `unsloth/unsloth:latest` pod:

```bash
/opt/venv/bin/python ml/training/finetune_lora.py \
    --data-dir ml/data/xbd_gemma \
    --run-name xbd_e2b_it_lora_v4_balanced \
    --epochs 1 --batch-size 2 --grad-accum 4 \
    --lr 5e-5 --warmup-ratio 0.1 \
    --lora-rank 16 --lora-alpha 16 \
    --balance --train-limit 8000 --val-limit 500
```

The `--balance` flag is the load-bearing one: it samples the JSONL into equal counts per `damage_class`, breaking the natural xBD ~80% no_damage distribution that earlier runs collapsed under.

## Eval set

**Aggregate val slice (200 examples):**

- Source: `ml/data/manifest.json["splits"]["val"]`, shuffled with `seed=42`, first 200.
- Held out by **disaster** (`split_dataset.py` keeps `mexico-earthquake` and `moore-tornado` out of train).
- Natural class distribution: 192 no_damage / 5 minor_damage / 0 major_damage / 3 destroyed.
- Rerun apples-to-apples:
  ```bash
  /opt/venv/bin/python -m ml.evaluation.eval_adapter \
      --manifest ml/data/manifest.json \
      --adapter ml/adapters/xbd_e2b_it_lora_v4_balanced \
      --split val --limit 200 --seed 42 \
      --out ml/adapters/xbd_e2b_it_lora_v4_balanced/eval_val.json
  ```

**Behavioral test (the one Ibrahim's review actually wanted):**

- Source: `sim/fixtures/frames/placeholder_victim_01.jpg` (FEMA Katrina destroyed-school aerial, CC0).
- Drone-agent system prompt + filled user template (drone3 standalone-window state), same image, base then tuned, 3 runs each.
- Rerun apples-to-apples:
  ```bash
  /opt/venv/bin/python -m ml.evaluation.behavioral_victim_test \
      --adapter ml/adapters/xbd_e2b_it_lora_v4_balanced \
      --frame sim/fixtures/frames/placeholder_victim_01.jpg \
      --runs 3 \
      --out ml/adapters/xbd_e2b_it_lora_v4_balanced/behavioral_victim_test.json
  ```

## Did the LoRA pass the 3/3 `report_finding(victim)` bar?

**No** — and **neither did the base model**. Both base Gemma 4 E2B-it and the LoRA-adapted model classify `placeholder_victim_01.jpg` as a damaged structure 3/3 times, not as a victim. That's correct behavior per the drone agent system prompt line 34: *"Victims: human bodies, faces, limbs, clothing colors, signs of distress. Do not classify mannequins or non-human shapes as victims."* The frame is a destroyed school aerial; there's no human body visible.

The realistic reading of the drone3 reliability TODO (which asks for "≥1 `report_finding` for drone3 within the standalone window", not specifically `type="victim"`) is that **both base and tuned PASS the 3/3 bar for `report_finding(any)`** on this frame. So the drone3 reliability problem isn't a "the model fails to classify this frame as a finding" problem — it's elsewhere (frame mapping, multi-drone inference saturation, scenario timing).

### Scope mismatch surfaced

docs/12 §"Scope" line 58-70 says explicitly:
> "We do NOT fine-tune for: Victim detection (visually ambiguous, sim-to-real gap is huge)"

The v4_balanced LoRA was trained on **building damage classification**, not victim detection. Expecting it to fix `report_finding(type="victim")` on a frame that doesn't contain a victim is asking the LoRA to violate the system prompt. The fact that the LoRA *doesn't* falsely classify this as a victim is a positive outcome.

## Separate finding: schema enum mismatch in base model output

Both base and tuned models output `type="damaged structures"` (with a space + trailing `s`), but the Contract-4 schema enum is `damaged_structure` (underscore, no `s`). The validation layer would reject this. This is a **prompt-template issue, not a LoRA issue** (base model has the same bug). Fix would be tightening the system prompt's tool documentation to explicitly list the valid enum values.

## Deployment status

The drone agent currently uses `gemma4:e2b` via Ollama. The trained LoRA is on `unsloth/gemma-4-e2b-it` in custom torch.save format. Deploying this LoRA into the drone agent would require either:

- Solving the transformers 5.5.0 → GGUF export bug (upstream blocker), OR
- Adding a transformers/vLLM-based inference path to the drone agent (significant code change, docs/12 §271 documented fallback)

Per the docs/12 NO-GO branch we took on the strict 4-class metric (+7.5 pp, missed 10 pp threshold by 2.5 pp), neither of these is on the critical path. The adapter stays in the repo as documented work.
