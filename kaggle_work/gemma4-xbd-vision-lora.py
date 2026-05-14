"""Kaggle kernel: Gemma 4 E2B Vision LoRA fine-tune on xBD.

Runs as a Kaggle batch script (kernel_type=script). Hardware target: P100 16 GB.
Internet ON (pip install Unsloth + push final model to Kaggle private Models).
Dataset attached: tunguz/xview2-challenge-dataset-train-and-test at /kaggle/input/.

Flow:
  Cell 1: env + smoke-test toggle + /kaggle/input layout dump
  Cell 2: preprocess xBD post-disaster building crops via kaggle_work/preprocess.py
          (class-balanced sampling, same WKT cropper as ml/data_prep/crop_patches.py)
  Cell 3: load Gemma 4 E2B vision + Unsloth LoRA (load_in_4bit=True, vision ON)
  Cell 4: train (SFTTrainer; bf16; gradient checkpointing)
  Cell 5: eval — JSON-envelope parse_status reporting, per-class F1, binary acc.
          (HF Transformers inference path; GGUF avoided per Unsloth issue #2290)
  Cell 6: merge adapter + push to Kaggle private Model with qasim_inference.py bundled

DECISIONS LOCKED via /plan-eng-review (2026-05-14):
  A1: Output schema matches ml/data_prep/format_for_gemma.py JSON envelope.
  A2: load_in_4bit=True (matches ml/training/finetune_lora.py:58).
  A3: Removed proxy 3-run trigger; real victim test runs on Qasim's box.
  A4: Real exit-code check on model push, distinguishes "exists" vs fatal.
  A5: predict() records parse_status; no silent coercion.
  A6: Cell 1 dumps /kaggle/input tree for early diagnosis.
  C3: TARGET_SIZE = 224 (matches crop_patches.py).
  P2: Class-balanced sampling caps output well under /kaggle/working's 19GB.
"""

# %% [markdown]
# ## Cell 1 — environment + input tree dump

# %%
import os
import sys
import json
import shutil
from pathlib import Path

# Make sibling modules (prompts.py, preprocess.py) importable.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# SMOKE_TEST: first push validates the full pipeline on a tiny slice. Flip to
# False for the real ~6-hr run.
SMOKE_TEST = True

INPUT = Path("/kaggle/input/xview2-challenge-dataset-train-and-test")
WORK = Path("/kaggle/working")
WORK.mkdir(parents=True, exist_ok=True)

print(f"SMOKE_TEST = {SMOKE_TEST}")
print(f"INPUT.exists() = {INPUT.exists()}")
if INPUT.exists():
    # A6: dump enough of the tree to diagnose layout drift in seconds.
    print("\n/kaggle/input/ tree (depth 3):")
    for p in sorted(INPUT.rglob("*"))[:80]:
        rel = p.relative_to(INPUT)
        if len(rel.parts) <= 3:
            print(f"  {rel}")

os.system("pip install -q --upgrade pip")
os.system("pip install -q unsloth")
os.system("pip install -q datasets pillow shapely tqdm scikit-learn")

# %% [markdown]
# ## Cell 2 — preprocess via vendored ml/data_prep functions

# %%
from tqdm import tqdm

from preprocess import (
    CLASS_LABELS,
    TARGET_SIZE,
    class_balance,
    collect_post_disaster_pairs,
    crop_buildings,
    find_xbd_root,
    split_by_disaster,
    write_chat_jsonl,
)

xbd_root = find_xbd_root(INPUT)
print(f"xBD root: {xbd_root}")

crops_dir = WORK / "crops"
crops_dir.mkdir(parents=True, exist_ok=True)

tiles_per_split_cap = 50 if SMOKE_TEST else None
per_class_cap = 200 if SMOKE_TEST else 5000

# Crop all tiles across train/test/tier3/hold splits present.
all_rows: list[dict] = []
for split_name in ("train", "test", "tier3", "hold"):
    split_dir = xbd_root / split_name
    if not split_dir.exists():
        continue
    pairs = collect_post_disaster_pairs(split_dir)
    if tiles_per_split_cap:
        pairs = pairs[:tiles_per_split_cap]
    out_split_dir = crops_dir / split_name
    out_split_dir.mkdir(exist_ok=True)
    for img_p, lbl_p in tqdm(pairs, desc=f"crop {split_name}"):
        all_rows.extend(crop_buildings(img_p, lbl_p, out_split_dir))

print(f"\nTotal cropped buildings: {len(all_rows)}")
from collections import Counter
raw_dist = Counter(r["label"] for r in all_rows)
print(f"Raw class distribution: {dict(raw_dist)}")

# P2: class-balanced sampling — caps each class so no-damage doesn't drown
# the loss signal and so /kaggle/working stays under its 19GB ceiling.
balanced = class_balance(all_rows, max_per_class=per_class_cap)
balanced_dist = Counter(r["label"] for r in balanced)
print(f"Balanced class distribution (cap={per_class_cap}): {dict(balanced_dist)}")

# Split by disaster for honest generalization measurement.
splits = split_by_disaster(balanced)
for s, items in splits.items():
    print(f"  {s}: {len(items)} ({dict(Counter(r['label'] for r in items))})")

train_jsonl = WORK / "train.jsonl"
val_jsonl = WORK / "val.jsonl"
test_jsonl = WORK / "test.jsonl"
n_train = write_chat_jsonl(splits["train"], train_jsonl)
n_val = write_chat_jsonl(splits["val"], val_jsonl)
n_test = write_chat_jsonl(splits["test"], test_jsonl)
print(f"Wrote train={n_train}, val={n_val}, test={n_test} rows")

# %% [markdown]
# ## Cell 3 — load Gemma 4 E2B vision + LoRA
#
# load_in_4bit=True matches ml/training/finetune_lora.py:58 (the working config).
# finetune_vision_layers=True per Unsloth vision-fine-tune docs.

# %%
from unsloth import FastVisionModel

MODEL_ID = "unsloth/gemma-4-E2B-it"

model, tokenizer = FastVisionModel.from_pretrained(
    MODEL_ID,
    load_in_4bit=True,
    use_gradient_checkpointing="unsloth",
)

model = FastVisionModel.get_peft_model(
    model,
    finetune_vision_layers=True,
    finetune_language_layers=True,
    finetune_attention_modules=True,
    finetune_mlp_modules=True,
    r=16,
    lora_alpha=16,
    lora_dropout=0,
    bias="none",
    random_state=3407,
    use_rslora=False,
    loftq_config=None,
)
model.print_trainable_parameters()

# %% [markdown]
# ## Cell 4 — train

# %%
from datasets import load_dataset
from trl import SFTTrainer, SFTConfig
from unsloth.trainer import UnslothVisionDataCollator

train_ds = load_dataset("json", data_files=str(train_jsonl), split="train")
print(f"Train rows loaded: {len(train_ds)}")

FastVisionModel.for_training(model)

max_steps = 30 if SMOKE_TEST else 500
save_steps = 10 if SMOKE_TEST else 100

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    data_collator=UnslothVisionDataCollator(model, tokenizer),
    train_dataset=train_ds,
    args=SFTConfig(
        per_device_train_batch_size=1,
        gradient_accumulation_steps=4,
        warmup_steps=5,
        max_steps=max_steps,
        learning_rate=2e-4,
        bf16=True,
        logging_steps=5,
        save_steps=save_steps,
        optim="adamw_8bit",
        weight_decay=0.01,
        lr_scheduler_type="linear",
        seed=3407,
        output_dir=str(WORK / "checkpoints"),
        report_to="none",
        remove_unused_columns=False,
        dataset_text_field="",
        dataset_kwargs={"skip_prepare_dataset": True},
        max_seq_length=2048,
    ),
)

stats = trainer.train()
print(stats)

# %% [markdown]
# ## Cell 5 — eval via HF Transformers; track parse_status, no silent coercion.

# %%
import torch
from sklearn.metrics import classification_report, confusion_matrix

from prompts import PROMPT, parse_model_output

FastVisionModel.for_inference(model)


def predict_raw(image_path: str) -> str:
    messages = [
        {"role": "user", "content": [
            {"type": "image", "image": image_path},
            {"type": "text", "text": PROMPT},
        ]},
    ]
    inputs = tokenizer.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
    ).to("cuda")
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=64, do_sample=False)
    return tokenizer.batch_decode(
        out[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True
    )[0]


# Use the proper held-out test split; fall back to val if test is empty.
eval_rows = splits["test"] if splits["test"] else splits["val"]
eval_cap = 50 if SMOKE_TEST else 800
eval_rows = eval_rows[:eval_cap]
print(f"Evaluating on {len(eval_rows)} rows")

y_true: list[str] = []
y_pred: list[str] = []
parse_counts = {"ok": 0, "off_schema": 0, "empty": 0, "bad_class": 0}
raw_samples: list[dict] = []

for row in tqdm(eval_rows, desc="eval"):
    raw = predict_raw(row["path"])
    parsed = parse_model_output(raw)
    parse_counts[parsed["parse_status"]] += 1
    if len(raw_samples) < 10:
        raw_samples.append({"label": row["label"], **parsed})
    # For metrics, only count successful parses against ground truth.
    if parsed["parse_status"] == "ok":
        y_true.append(row["label"])
        y_pred.append(parsed["damage_class"])

if y_true:
    report = classification_report(
        y_true, y_pred, labels=CLASS_LABELS, output_dict=True, zero_division=0,
    )
    cm = confusion_matrix(y_true, y_pred, labels=CLASS_LABELS).tolist()
    binary_true = ["damaged" if l != "no-damage" else "no-damage" for l in y_true]
    binary_pred = ["damaged" if l != "no-damage" else "no-damage" for l in y_pred]
    binary_acc = sum(t == p for t, p in zip(binary_true, binary_pred)) / len(binary_true)
else:
    report, cm, binary_acc = {}, [], None

parse_rate_ok = parse_counts["ok"] / max(1, len(eval_rows))

eval_summary = {
    "smoke_test": SMOKE_TEST,
    "n_eval": len(eval_rows),
    "parse_counts": parse_counts,
    "parse_rate_ok": parse_rate_ok,
    "per_class_report": report,
    "confusion_matrix": cm,
    "confusion_matrix_labels": CLASS_LABELS,
    "binary_damaged_accuracy": binary_acc,
    "raw_samples": raw_samples,
}
eval_path = WORK / "eval_summary.json"
eval_path.write_text(json.dumps(eval_summary, indent=2))
print(json.dumps({k: v for k, v in eval_summary.items() if k != "raw_samples"}, indent=2))

# %% [markdown]
# ## Cell 6 — merge adapter + push to Kaggle private Model
#
# Saves merged 16-bit HF model. Bundles prompts.py and qasim_inference.py so
# the published Model version is self-contained for Qasim's CUDA box.

# %%
import subprocess

merged_dir = WORK / "merged_model"
model.save_pretrained_merged(str(merged_dir), tokenizer, save_method="merged_16bit")
print(f"Merged model saved to {merged_dir}")

# Bundle the inference contract files into the model dir so the Kaggle Model
# version is self-contained for Qasim's CUDA box.
shutil.copy(Path(__file__).parent / "prompts.py", merged_dir / "prompts.py")
shutil.copy(eval_path, merged_dir / "eval_summary.json")

qasim_loader = '''"""qasim_inference.py — run the merged Gemma 4 E2B vision LoRA on a CUDA box.

Output is the same JSON envelope used during training (see prompts.py).

Usage:
    pip install transformers accelerate pillow
    python qasim_inference.py path/to/image.jpg
"""
import sys
import json
from pathlib import Path
import torch
from transformers import AutoModelForImageTextToText, AutoProcessor
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prompts import PROMPT, parse_model_output

MODEL_DIR = Path(__file__).parent
processor = AutoProcessor.from_pretrained(MODEL_DIR)
model = AutoModelForImageTextToText.from_pretrained(
    MODEL_DIR, torch_dtype=torch.bfloat16, device_map="cuda"
)

img = Image.open(sys.argv[1]).convert("RGB")
messages = [
    {"role": "user", "content": [
        {"type": "image", "image": img},
        {"type": "text", "text": PROMPT},
    ]},
]
inputs = processor.apply_chat_template(
    messages, add_generation_prompt=True, tokenize=True,
    return_dict=True, return_tensors="pt",
).to("cuda")
with torch.no_grad():
    out = model.generate(**inputs, max_new_tokens=64, do_sample=False)
raw = processor.batch_decode(
    out[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True
)[0]
print(json.dumps(parse_model_output(raw), indent=2))
'''
(merged_dir / "qasim_inference.py").write_text(qasim_loader)

# Per-instance model metadata.
MODEL_SLUG = "ibrahimahmed7860/gemma4-e2b-xbd-vision-lora"
FRAMEWORK = "transformers"
VARIATION = "lora-merged-bf16"
n_eval_safe = max(1, len(eval_rows))
binary_acc_str = f"{binary_acc:.3f}" if binary_acc is not None else "n/a"
VERSION_NOTES = (
    f"smoke={SMOKE_TEST} | parse_ok={parse_rate_ok:.2f} | "
    f"binary_acc={binary_acc_str} | n_eval={n_eval_safe}"
)

instance_meta = {
    "ownerSlug": "ibrahimahmed7860",
    "modelSlug": "gemma4-e2b-xbd-vision-lora",
    "instanceSlug": VARIATION,
    "framework": FRAMEWORK,
    "overview": "Gemma 4 E2B + Unsloth vision LoRA, merged 16-bit. Load via qasim_inference.py.",
    "usage": "See qasim_inference.py bundled in this version.",
    "licenseName": "Apache 2.0",
    "fineTunable": True,
    "trainingData": ["tunguz/xview2-challenge-dataset-train-and-test"],
}
(merged_dir / "model-instance-metadata.json").write_text(
    json.dumps(instance_meta, indent=2)
)


def run_kaggle(cmd: list[str]) -> tuple[int, str, str]:
    """Run a kaggle CLI command, return (rc, stdout, stderr)."""
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


# A4: real exit-code handling. "already exists" is OK; anything else is fatal.
model_init_dir = WORK / "model_init"
model_init_dir.mkdir(exist_ok=True)
(model_init_dir / "model-metadata.json").write_text(json.dumps({
    "ownerSlug": "ibrahimahmed7860",
    "title": "Gemma 4 E2B Vision LoRA — xBD damage",
    "slug": "gemma4-e2b-xbd-vision-lora",
    "subtitle": "Gemma 4 E2B fine-tuned on xBD via Unsloth LoRA",
    "isPrivate": True,
    "licenseName": "Apache 2.0",
}, indent=2))

rc, out, err = run_kaggle(["kaggle", "models", "create", "-p", str(model_init_dir)])
if rc != 0:
    if "already exists" in (out + err).lower():
        print("Model entry already exists (OK), will add new version.")
    else:
        print(f"Model create failed (rc={rc}):\nSTDOUT: {out}\nSTDERR: {err}")
        print("Falling back to tarball.")
        tar_path = WORK / "artifacts.tar.gz"
        os.system(f"tar -czf {tar_path} -C {merged_dir.parent} {merged_dir.name}")
        print(f"Tarball: {tar_path}")
        raise SystemExit(0)  # Don't fail the kernel — operator pulls tarball.
else:
    print("Model entry created.")

push_args = [
    "kaggle", "models", "instances", "versions", "create",
    f"{MODEL_SLUG}/{FRAMEWORK}/{VARIATION}",
    "-p", str(merged_dir),
    "-n", VERSION_NOTES,
]
rc, out, err = run_kaggle(push_args)
if rc == 0:
    print(f"Model version pushed: {MODEL_SLUG}/{FRAMEWORK}/{VARIATION}")
else:
    print(f"Model version push failed (rc={rc}):\nSTDOUT: {out}\nSTDERR: {err}")
    print("Falling back to tarball.")
    tar_path = WORK / "artifacts.tar.gz"
    os.system(f"tar -czf {tar_path} -C {merged_dir.parent} {merged_dir.name}")
    print(f"Tarball: {tar_path}")
