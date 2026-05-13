"""Unsloth LoRA fine-tuning of Gemma 4 E2B on xBD damage patches.

Hyperparameters from docs/12-fine-tuning-plan.md as starting point.
Outputs adapter to ml/adapters/<run_name>/ as lora_weights.pt + lora_config.json.

The standard `trainer.save_pretrained()` path hits a known transformers 5.5.0 ×
Unsloth × Gemma 4 4-bit incompatibility (NotImplementedError in
core_model_loading.revert_weight_conversion). We sidestep this by:
  - save_strategy="no" (no checkpoint writes during training)
  - manual LoRA extraction via model.named_parameters() at end of training
  - torch.save({param_name: tensor}) into lora_weights.pt
  - companion lora_config.json with the exact get_peft_model kwargs so the
    adapter can be re-applied to a fresh base-model load

COMPUTE PATH (docs/12 §Compute Path): Run on WSL2+NVIDIA or a rented cloud GPU
(Lambda Labs / Paperspace / Runpod). Will not run on macOS. Workflow:
  1. Preprocess xBD locally (Mac/Windows): download_xbd → crop_patches →
     split_dataset → format_for_gemma. Output goes to ml/data/xbd_gemma/.
  2. rsync ml/data/xbd_gemma/ + ml/data/patches/ to the GPU box.
  3. Run this script on the GPU box.
  4. scp ml/adapters/<run_name>/ back to the demo box.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path


if platform.system() == "Darwin":
    print("This script cannot run on macOS — Unsloth requires Linux + NVIDIA CUDA.")
    print("See docs/12-fine-tuning-plan.md §Compute Path for WSL2 / cloud GPU setup.")
    sys.exit(2)


def load_split(jsonl: Path, limit: int | None = None) -> list[dict]:
    examples = [json.loads(line) for line in jsonl.read_text().splitlines()]
    if limit is not None:
        examples = examples[:limit]
    return examples


def make_vision_collator(processor):
    """Convert {messages: [...]} JSONL examples to a Gemma 4 vision training batch.

    Each example has one user turn with an image + text and one assistant turn
    with a JSON string. We:
      - resolve and PIL-load the image (paths are relative to the repo root)
      - prepend the processor's image token to the user prompt
      - call processor(text=, images=) to get input_ids + pixel_values
      - mask labels=-100 for the user portion so loss is only on assistant tokens
    """
    from PIL import Image
    import torch
    REPO_ROOT = Path(__file__).resolve().parents[2]
    image_token = getattr(processor, "image_token", None) or "<start_of_image>"

    def collate(examples: list[dict]) -> dict:
        texts: list[str] = []
        images: list[Image.Image] = []
        assistant_strs: list[str] = []

        for ex in examples:
            user_msg = ex["messages"][0]
            assistant_msg = ex["messages"][1]

            user_text = ""
            img_path = None
            for part in user_msg["content"]:
                if part["type"] == "image":
                    img_path = part["image"]
                elif part["type"] == "text":
                    user_text = part["text"]
            assert img_path is not None, f"missing image in example: {ex}"

            full = (REPO_ROOT / img_path) if not Path(img_path).is_absolute() else Path(img_path)
            images.append(Image.open(full).convert("RGB"))
            texts.append(f"{image_token}\n{user_text}\n{assistant_msg['content']}")
            assistant_strs.append(assistant_msg["content"])

        batch = processor(text=texts, images=images, return_tensors="pt", padding=True)
        labels = batch["input_ids"].clone()
        # Mask everything that isn't the assistant continuation. Heuristic: find
        # the assistant string's length in tokens from the END of each row and
        # mask the rest to -100. This avoids depending on a chat template.
        for i, assistant in enumerate(assistant_strs):
            tail_ids = processor.tokenizer(assistant, add_special_tokens=False)["input_ids"]
            tail_len = len(tail_ids)
            if tail_len <= 0:
                labels[i, :] = -100
                continue
            seq_len = labels.shape[1]
            mask_until = max(0, seq_len - tail_len)
            labels[i, :mask_until] = -100
        # Also mask pad tokens
        pad_id = processor.tokenizer.pad_token_id
        if pad_id is not None:
            labels[batch["input_ids"] == pad_id] = -100
        batch["labels"] = labels
        return batch

    return collate


def save_lora_manual(model, tokenizer, out_dir: Path, config: dict) -> None:
    """Bypass transformers 5.5.0 save_pretrained bug — torch.save the LoRA params."""
    import torch
    out_dir.mkdir(parents=True, exist_ok=True)
    lora_state = {
        name: param.detach().cpu()
        for name, param in model.named_parameters()
        if "lora_" in name.lower()
    }
    if not lora_state:
        raise RuntimeError(
            "No LoRA params found via named_parameters() filter — "
            "get_peft_model may not have wrapped the model correctly."
        )
    torch.save(lora_state, out_dir / "lora_weights.pt")
    (out_dir / "lora_config.json").write_text(json.dumps(config, indent=2))
    try:
        tokenizer.save_pretrained(str(out_dir))
    except Exception as e:
        print(f"  WARN: tokenizer.save_pretrained failed ({e}); skipping (LoRA weights OK)")
    n_params = sum(p.numel() for p in lora_state.values())
    print(f"  manual LoRA save: {len(lora_state)} tensors, {n_params:,} params → {out_dir}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True, help="Output of format_for_gemma.py (contains train.jsonl, val.jsonl).")
    ap.add_argument("--run-name", default="xbd_e2b_lora_v1")
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--batch-size", type=int, default=2)
    ap.add_argument("--grad-accum", type=int, default=4)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--lora-rank", type=int, default=32, help="docs/12: r=32 default for vision LoRA.")
    ap.add_argument("--lora-alpha", type=int, default=32)
    ap.add_argument("--target-modules", default="all-linear", help='docs/12: Unsloth current default for vision.')
    ap.add_argument("--finetune-vision-layers", action="store_true", help="docs/12: start with this OFF.")
    ap.add_argument("--train-limit", type=int, default=None, help="Cap train examples (for quick runs).")
    ap.add_argument("--val-limit", type=int, default=None, help="Cap val examples.")
    ap.add_argument("--max-hours", type=float, default=24 * 7)
    args = ap.parse_args()

    from unsloth import FastVisionModel  # type: ignore
    from trl import SFTTrainer, SFTConfig  # type: ignore

    model, tokenizer = FastVisionModel.from_pretrained(
        model_name="unsloth/gemma-4-e2b",
        load_in_4bit=True,
    )
    lora_config = dict(
        finetune_vision_layers=args.finetune_vision_layers,
        finetune_language_layers=True,
        finetune_attention_modules=True,
        finetune_mlp_modules=True,
        target_modules=args.target_modules,
        r=args.lora_rank,
        lora_alpha=args.lora_alpha,
        lora_dropout=0.0,
        bias="none",
        random_state=42,
        use_rslora=False,
        use_gradient_checkpointing="unsloth",
    )
    model = FastVisionModel.get_peft_model(model, **lora_config)
    FastVisionModel.for_training(model)

    train = load_split(args.data_dir / "train.jsonl", limit=args.train_limit)
    val = load_split(args.data_dir / "val.jsonl", limit=args.val_limit)
    print(f"train={len(train)} val={len(val)}")

    out_dir = Path(__file__).resolve().parents[1] / "adapters" / args.run_name
    out_dir.mkdir(parents=True, exist_ok=True)

    config = SFTConfig(
        output_dir=str(out_dir),
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
        bf16=True,
        optim="adamw_8bit",
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        logging_steps=10,
        save_strategy="no",   # bypass transformers 5.5.0 save_pretrained bug
        eval_strategy="no",   # skip eval to keep this run cheap; eval externally
        report_to="none",
        remove_unused_columns=False,
        dataset_kwargs={"skip_prepare_dataset": True},
    )

    collator = make_vision_collator(tokenizer)

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train,
        eval_dataset=val,
        args=config,
        data_collator=collator,
    )

    t0 = time.time()
    trainer.train()
    elapsed_h = (time.time() - t0) / 3600
    print(f"training wall-clock: {elapsed_h:.2f}h")

    save_lora_manual(
        model, tokenizer, out_dir,
        config={
            "base_model": "unsloth/gemma-4-e2b",
            "lora_kwargs": lora_config,
            "training_kwargs": {
                "epochs": args.epochs,
                "batch_size": args.batch_size,
                "grad_accum": args.grad_accum,
                "lr": args.lr,
                "train_examples": len(train),
                "elapsed_hours": round(elapsed_h, 2),
            },
        },
    )
    print(f"adapter saved → {out_dir}")


if __name__ == "__main__":
    main()
