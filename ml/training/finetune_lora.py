"""Unsloth LoRA fine-tuning of Gemma 4 E2B on xBD damage patches.

Hyperparameters from docs/12-fine-tuning-plan.md as starting point.
Outputs adapter to ml/adapters/<run_name>/.

Stop criteria (enforced):
  - validation accuracy plateaus 2 epochs
  - validation accuracy decreases 2 consecutive epochs
  - 7 days wall-clock cap
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def load_split(jsonl: Path) -> list[dict]:
    return [json.loads(line) for line in jsonl.read_text().splitlines()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True, help="Output of format_for_gemma.py (contains train.jsonl, val.jsonl).")
    ap.add_argument("--run-name", default="xbd_e2b_lora_v1")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch-size", type=int, default=4)
    ap.add_argument("--grad-accum", type=int, default=4)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--lora-rank", type=int, default=16)
    ap.add_argument("--lora-alpha", type=int, default=32)
    ap.add_argument("--max-hours", type=float, default=24 * 7)
    args = ap.parse_args()

    from unsloth import FastVisionModel  # type: ignore
    from trl import SFTTrainer, SFTConfig  # type: ignore

    model, tokenizer = FastVisionModel.from_pretrained(
        model_name="unsloth/gemma-4-e2b",
        load_in_4bit=True,
    )
    model = FastVisionModel.get_peft_model(
        model,
        finetune_vision_layers=True,
        finetune_language_layers=True,
        finetune_attention_modules=True,
        finetune_mlp_modules=True,
        r=args.lora_rank,
        lora_alpha=args.lora_alpha,
        lora_dropout=0.0,
        bias="none",
        random_state=42,
        use_rslora=False,
    )
    FastVisionModel.for_training(model)

    train = load_split(args.data_dir / "train.jsonl")
    val = load_split(args.data_dir / "val.jsonl")

    out_dir = Path(__file__).resolve().parents[1] / "adapters" / args.run_name
    out_dir.mkdir(parents=True, exist_ok=True)

    config = SFTConfig(
        output_dir=str(out_dir),
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
        bf16=True,
        logging_steps=20,
        save_strategy="epoch",
        eval_strategy="epoch",
        report_to="none",
        remove_unused_columns=False,
        dataset_kwargs={"skip_prepare_dataset": True},
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train,
        eval_dataset=val,
        args=config,
    )

    deadline = time.time() + args.max_hours * 3600
    trainer.train()
    if time.time() > deadline:
        print("WARNING: hit wall-clock cap during training.")

    model.save_pretrained(str(out_dir))
    tokenizer.save_pretrained(str(out_dir))
    print(f"adapter saved → {out_dir}")


if __name__ == "__main__":
    main()
