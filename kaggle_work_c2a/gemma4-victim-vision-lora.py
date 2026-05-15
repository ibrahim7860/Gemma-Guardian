"""Kaggle kernel: Gemma 4 E2B Vision LoRA for VICTIM DETECTION on C2A dataset.

PIVOT RATIONALE (vs kaggle_work/ xBD path):
  The GATE 3 acceptance test is `report_finding(type='victim')` 3/3 on the
  wow-moment frame (placeholder_victim_01.jpg). xBD trains building-damage
  classification, which is a related but indirect task. C2A is purpose-built
  for human detection in disaster aerial imagery — direct fit for our task.

  C2A: 10,215 high-res UAV images, 360K+ annotated human instances across
  4 disaster scenarios (Fire/Smoke, Flood, Collapsed Building, Traffic).
  YOLO-style label format (one .txt per image, one line per human bbox).

Output schema (matches FieldAgent's report_finding contract):
  {"finding_type": "victim" | "none",
   "confidence": <float 0-1>,
   "visual_evidence": "<short description>"}

SELF-CONTAINED. Kaggle CLI's kernels push uploads only the code_file, so
all helpers are inline below.

DECISIONS LOCKED via parallel xBD work (v1-v18 in kaggle_work/):
  - load_in_4bit=True (matches finetune_lora.py:58)
  - finetune_vision_layers=True (vision tower must adapt)
  - T4 fp16 (not bf16; Turing doesn't support bf16)
  - Inference: PIL Image + tokenizer(image, text) — NOT path-in-content
  - Stronger prompt forcing JSON output, "Do not refuse, do not hedge"
  - LoRA-only save (~200MB) instead of merged_16bit (~10GB)
  - Stratified random split (not disaster-held-out)
"""

# %% [markdown]
# ## Cell 1 — env + input tree dump

# %%
import os
import sys
import json
import re
import random
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

# SMOKE_TEST=True validates the pipeline on a tiny slice in ~15 min.
# Flip to False for the real ~3.5-4 hr training run.
# v4: smoke v3 validated AIDER+C2A balanced eval (binary_acc 0.72, precision 1.0).
# Full run to push recall up via 500 train steps on 5000+5000 balanced examples.
SMOKE_TEST = True  # v8: validate DoRA + new hyperparams on smoke before full run

INPUT_ROOT = Path("/kaggle/input")
# Cross-user datasets mount under /kaggle/input/datasets/<owner>/<slug>/
C2A_ROOT = INPUT_ROOT / "datasets" / "rgbnihal" / "c2a-dataset"
AIDER_ROOT = INPUT_ROOT / "datasets" / "samik2005" / "aider-dataset"
SARD_ROOT = INPUT_ROOT / "datasets" / "nikolasgegenava" / "sard-search-and-rescue"
# Fallbacks for differing Kaggle mount conventions
if not C2A_ROOT.exists() and (INPUT_ROOT / "c2a-dataset").exists():
    C2A_ROOT = INPUT_ROOT / "c2a-dataset"
if not AIDER_ROOT.exists() and (INPUT_ROOT / "aider-dataset").exists():
    AIDER_ROOT = INPUT_ROOT / "aider-dataset"
if not SARD_ROOT.exists() and (INPUT_ROOT / "sard-search-and-rescue").exists():
    SARD_ROOT = INPUT_ROOT / "sard-search-and-rescue"
INPUT_EXPECTED = C2A_ROOT  # legacy name kept for downstream references
WORK = Path("/kaggle/working")
WORK.mkdir(parents=True, exist_ok=True)

print(f"SMOKE_TEST = {SMOKE_TEST}")
print(f"C2A_ROOT:   {C2A_ROOT} (exists={C2A_ROOT.exists()})")
print(f"AIDER_ROOT: {AIDER_ROOT} (exists={AIDER_ROOT.exists()})")
print(f"SARD_ROOT:  {SARD_ROOT} (exists={SARD_ROOT.exists()})")

print("\nGPU info:")
os.system("nvidia-smi --query-gpu=name,compute_cap,driver_version,memory.total --format=csv 2>/dev/null || echo 'nvidia-smi unavailable'")

if INPUT_ROOT.exists():
    print("\n/kaggle/input/ top-level entries:")
    for p in sorted(INPUT_ROOT.iterdir()):
        print(f"  {p.name} (dir={p.is_dir()})")
    print("\nC2A dataset tree (depth 4, first 40 entries):")
    if INPUT_EXPECTED.exists():
        n = 0
        for p in sorted(INPUT_EXPECTED.rglob("*")):
            rel = p.relative_to(INPUT_EXPECTED)
            if len(rel.parts) <= 4:
                print(f"  {rel}")
                n += 1
                if n >= 40:
                    print("  ... (truncated)")
                    break
else:
    raise RuntimeError("No /kaggle/input — kernel cannot proceed.")

print("\nConnectivity check:")
os.system("curl -sS --max-time 10 https://pypi.org/simple/ -o /dev/null -w 'pypi HTTP %{http_code}\\n' 2>&1")

os.system("pip install -q --upgrade pip")
os.system("pip install -q unsloth bitsandbytes")
os.system("pip install -q datasets pillow tqdm scikit-learn")

# %% [markdown]
# ## Cell 1b — VENDORED constants + I/O contract

# %%
# Output schema for victim detection. Mirrors FieldAgent's report_finding
# function-call contract (type: victim is the GATE 3 acceptance bar).
FINDING_TYPES = ["victim", "none"]

PROMPT = (
    "You are analyzing an aerial image from a disaster-response drone. "
    "Determine if a human victim is visible. "
    "Respond with ONLY a JSON object in this exact format: "
    '{"finding_type": <one of: victim, none>, '
    '"confidence": <float between 0 and 1>, '
    '"visual_evidence": <brief description of what you see>}. '
    "Do not include any other text. Do not refuse. Do not hedge."
)

EVIDENCE_VICTIM = "Human figure visible in the disaster scene."
EVIDENCE_NONE = "No human victims visible in this scene."


def to_chat_example(image_path: str, label: str) -> dict:
    """Convert (image, label) into Unsloth/Gemma 4 vision chat-format row."""
    if label not in FINDING_TYPES:
        raise ValueError(f"Unknown finding type: {label!r}")
    evidence = EVIDENCE_VICTIM if label == "victim" else EVIDENCE_NONE
    return {
        "messages": [
            {"role": "user", "content": [
                {"type": "image", "image": image_path},
                {"type": "text", "text": PROMPT},
            ]},
            {"role": "assistant", "content": [{"type": "text", "text": json.dumps({
                "finding_type": label,
                "confidence": 0.9,
                "visual_evidence": evidence,
            })}]},
        ]
    }


_JSON_BLOCK = re.compile(r"\{.*?\}", re.DOTALL)


def _extract_json(text: str) -> Optional[dict]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = _JSON_BLOCK.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def parse_model_output(raw: str) -> dict:
    if raw is None or not raw.strip():
        return {"parse_status": "empty", "finding_type": None, "raw": raw}
    obj = _extract_json(raw.strip())
    if obj is None:
        return {"parse_status": "off_schema", "finding_type": None, "raw": raw}
    ft = obj.get("finding_type")
    if ft not in FINDING_TYPES:
        return {"parse_status": "bad_class", "finding_type": None, "raw": raw}
    return {
        "parse_status": "ok",
        "finding_type": ft,
        "confidence": obj.get("confidence"),
        "visual_evidence": obj.get("visual_evidence"),
        "raw": raw,
    }


# %% [markdown]
# ## Cell 2 — preprocess C2A into (image, victim/none) pairs

# %%
from tqdm import tqdm
from PIL import Image

# C2A actual structure (verified via v1 kernel log):
#   C2A_Dataset/new_dataset3/
#     train/images/   train/labels/   train_annotations.json
#     val/images/     val/labels/     val_annotations.json
#     test/images/    test/labels/    test_annotations.json
#     All labels with Pose information/labels/  (pose-enriched dup of all labels)
#     Coco_annotation_pose/  (COCO-format annotations with pose info)
def find_c2a_splits(root: Path) -> dict[str, dict[str, Path]]:
    """Return {split_name: {'images': Path, 'labels': Path}} for train/val/test."""
    candidates_root = [root]
    for p in root.rglob("C2A_Dataset"):
        if p.is_dir():
            candidates_root.append(p)
            break
    for r in candidates_root:
        for sub in ["new_dataset3", "."]:
            base = r / sub if sub != "." else r
            if not base.exists():
                continue
            out = {}
            for split in ("train", "val", "test"):
                imgs = base / split / "images"
                lbls = base / split / "labels"
                if imgs.exists() and lbls.exists():
                    out[split] = {"images": imgs, "labels": lbls}
            if out:
                return out
    raise RuntimeError(f"Could not find C2A train/val/test splits under {root}")


c2a_splits_dirs = find_c2a_splits(C2A_ROOT)
print(f"C2A splits found: {list(c2a_splits_dirs.keys())}")
for split, paths in c2a_splits_dirs.items():
    n_imgs = sum(1 for _ in paths["images"].rglob("*.jpg"))
    n_lbls = sum(1 for _ in paths["labels"].glob("*.txt"))
    print(f"  {split}: {n_imgs} images, {n_lbls} labels")


def find_aider_images(root: Path) -> list[Path]:
    """AIDER layout: AIDER_full/<class>/<image>.jpg. Pure backgrounds, no humans."""
    if not root.exists():
        return []
    candidates = [root]
    for p in root.rglob("AIDER_full"):
        if p.is_dir():
            candidates.append(p)
            break
    for base in candidates:
        imgs = list(base.rglob("*.jpg")) + list(base.rglob("*.JPG"))
        if imgs:
            return imgs
    return []


aider_imgs_all = find_aider_images(AIDER_ROOT)
print(f"AIDER images: {len(aider_imgs_all)}")
if aider_imgs_all:
    # Quick class distribution
    from collections import Counter as _C
    print(f"AIDER class distribution: {dict(_C(p.parent.name for p in aider_imgs_all))}")


def parse_label_file(p: Path) -> list[tuple[int, float, float, float, float]]:
    """YOLO-format label: <class> <cx> <cy> <w> <h> per line (normalized 0-1).

    C2A YOLO label class IDs in the simple labels/ dir are typically just 0=person
    (single-class). The pose-aware classification (Upright, Sitting, Lying, Bent,
    Kneeling) lives in the COCO annotations files. For our binary task we don't
    need the pose subclass — any human present → "victim".
    """
    out = []
    try:
        for line in p.read_text().splitlines():
            parts = line.strip().split()
            if len(parts) < 5:
                continue
            cls = int(parts[0])
            cx, cy, w, h = (float(x) for x in parts[1:5])
            out.append((cls, cx, cy, w, h))
    except (OSError, ValueError):
        pass
    return out


def find_image_for_label(lbl_path: Path, images_dir: Path) -> Optional[Path]:
    """Find the image file matching a label file's stem."""
    stem = lbl_path.stem
    for ext in (".jpg", ".jpeg", ".png"):
        cand = images_dir / f"{stem}{ext}"
        if cand.exists():
            return cand
    # Fallback: rglob (images may be in subdirs).
    for ext in (".jpg", ".jpeg", ".png"):
        for c in images_dir.rglob(f"{stem}{ext}"):
            return c
    return None


# Binary labeling rule:
#   - C2A image (has human annotations) → "victim"
#   - AIDER image (pure background, no humans) → "none"
# v3 mix: C2A is the victim source, AIDER is the none source. This is the
# correct binary discrimination setup — C2A v2 had zero "none" data.

# C2A comes pre-split. Use C2A's splits for victim rows.
c2a_caps = {"train": 1500, "val": 250, "test": 250} if SMOKE_TEST else \
           {"train": None, "val": 800, "test": 400}

c2a_rows_by_split: dict[str, list[dict]] = {"train": [], "val": [], "test": []}
for split_name, paths in c2a_splits_dirs.items():
    label_files = sorted(paths["labels"].glob("*.txt"))
    cap = c2a_caps.get(split_name)
    if cap:
        label_files = label_files[:cap]
    print(f"\nC2A {split_name}: {len(label_files)} label files (cap={cap})")
    for lbl_path in tqdm(label_files, desc=f"c2a {split_name}"):
        img_path = find_image_for_label(lbl_path, paths["images"])
        if img_path is None:
            continue
        annots = parse_label_file(lbl_path)
        if not annots:
            continue
        c2a_rows_by_split[split_name].append({
            "path": str(img_path),
            "label": "victim",
            "source": "c2a",  # tracked for per-source eval breakdown
            "scenario": next((s for s in ("collapsed_building", "fire", "flood", "traffic_accident") if lbl_path.stem.startswith(s)), "unknown"),
            "n_humans": len(annots),
        })

# SARD: REAL drone footage with annotated people. Add as a second VICTIM source
# to break the C2A-synthesis-artifact shortcut. If our model is learning real
# victim features (H1), training+evaluating with C2A AND SARD victim examples
# should produce similar metrics. If it's learning C2A synthesis artifacts (H2),
# SARD examples will be classified wrong.
def find_sard_splits(root: Path) -> dict[str, dict[str, Path]]:
    """Roboflow-style: search-and-rescue/{train,val,test}/{images,labels}/"""
    if not root.exists():
        return {}
    candidates = [root]
    for p in root.rglob("search-and-rescue"):
        if p.is_dir():
            candidates.append(p)
            break
    for r in candidates:
        out = {}
        for split in ("train", "val", "test"):
            imgs = r / split / "images"
            lbls = r / split / "labels"
            if imgs.exists() and lbls.exists():
                out[split] = {"images": imgs, "labels": lbls}
        if out:
            return out
    return {}

sard_splits_dirs = find_sard_splits(SARD_ROOT)
print(f"\nSARD splits found: {list(sard_splits_dirs.keys())}")
sard_rows_by_split: dict[str, list[dict]] = {"train": [], "val": [], "test": []}
sard_caps = {"train": 500, "val": 100, "test": 100} if SMOKE_TEST else \
            {"train": None, "val": 400, "test": 400}
for split_name, paths in sard_splits_dirs.items():
    label_files = sorted(paths["labels"].glob("*.txt"))
    cap = sard_caps.get(split_name)
    if cap:
        label_files = label_files[:cap]
    print(f"SARD {split_name}: {len(label_files)} label files (cap={cap})")
    for lbl_path in tqdm(label_files, desc=f"sard {split_name}"):
        img_path = find_image_for_label(lbl_path, paths["images"])
        if img_path is None:
            continue
        annots = parse_label_file(lbl_path)
        if not annots:
            continue
        sard_rows_by_split[split_name].append({
            "path": str(img_path),
            "label": "victim",
            "source": "sard",
            "scenario": "sar_drone",
            "n_humans": len(annots),
        })

# AIDER comes as one flat pool — split it 80/10/10 for train/val/test.
rng = random.Random(3407)
aider_imgs = list(aider_imgs_all)
rng.shuffle(aider_imgs)
n_aider = len(aider_imgs)
n_val = max(50, int(n_aider * 0.10))
n_test = max(50, int(n_aider * 0.10))
aider_split = {
    "train": aider_imgs[n_val + n_test:],
    "val":   aider_imgs[:n_val],
    "test":  aider_imgs[n_val:n_val + n_test],
}
aider_rows_by_split: dict[str, list[dict]] = {}
for split_name, imgs in aider_split.items():
    if SMOKE_TEST:
        cap = {"train": 1500, "val": 250, "test": 250}[split_name]
        imgs = imgs[:cap]
    aider_rows_by_split[split_name] = [{
        "path": str(p),
        "label": "none",
        "source": "aider",
        "scenario": p.parent.name,
        "n_humans": 0,
    } for p in imgs]
    print(f"AIDER {split_name}: {len(aider_rows_by_split[split_name])} images")

# Merge + balance per split.
# v7: REVERTED SARD inclusion. v6 (C2A+AIDER+SARD) collapsed to always-victim
# (binary_acc 0.508) — model couldn't reconcile diverse victim sources and
# defaulted to victim prediction. v4 (C2A+AIDER only) was 96.5% balanced.
# Keep SARD parsing logic for future experiments but exclude from training.
# SARD eval rows used as held-out test for honest H1 vs H2 measurement.
USE_SARD_IN_TRAIN = False  # set True to re-include SARD in victim pool
splits: dict[str, list[dict]] = {}
for s in ("train", "val", "test"):
    victim_rows = c2a_rows_by_split[s] + (sard_rows_by_split[s] if USE_SARD_IN_TRAIN else [])
    # Hold SARD eval rows for the per-source breakdown even when not training on them.
    if s in ("val", "test") and not USE_SARD_IN_TRAIN:
        victim_rows = victim_rows + sard_rows_by_split[s]
    none_rows = aider_rows_by_split[s]
    rng.shuffle(victim_rows)
    rng.shuffle(none_rows)
    n = min(len(victim_rows), len(none_rows))
    if n == 0:
        print(f"  WARNING: {s} has victim={len(victim_rows)}, none={len(none_rows)}")
        splits[s] = victim_rows + none_rows
    else:
        splits[s] = victim_rows[:n] + none_rows[:n]
    rng.shuffle(splits[s])

for s in splits:
    by_src = Counter(r["source"] for r in splits[s])
    by_lbl = Counter(r["label"] for r in splits[s])
    print(f"  {s}: {len(splits[s])} | labels={dict(by_lbl)} | sources={dict(by_src)}")


def write_chat_jsonl(rows, out_path: Path) -> int:
    n = 0
    with out_path.open("w") as f:
        for r in rows:
            f.write(json.dumps(to_chat_example(r["path"], r["label"])) + "\n")
            n += 1
    return n


train_jsonl = WORK / "train.jsonl"
val_jsonl = WORK / "val.jsonl"
test_jsonl = WORK / "test.jsonl"
n_train = write_chat_jsonl(splits["train"], train_jsonl)
n_val = write_chat_jsonl(splits["val"], val_jsonl)
n_test = write_chat_jsonl(splits["test"], test_jsonl)
print(f"Wrote train={n_train}, val={n_val}, test={n_test} rows")

# %% [markdown]
# ## Cell 3 — load Gemma 4 E2B vision + LoRA

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
    # v8: research-backed improvements for generalization
    #   r=16 with alpha=2*r is the Unsloth heuristic (was 16/16)
    #   use_dora=True: Weight-Decomposed LoRA — closes half the gap to full
    #     fine-tuning on vision tasks per DoRA paper (LLaVA, VL-BART). Fused
    #     in Unsloth 2026.04+, runs at same speed as plain LoRA.
    #   lora_dropout=0.05: small regularization to prevent shortcut memorization
    #     (v7 train_loss converged to 0.0004 — deep overfit territory).
    r=16,
    lora_alpha=32,
    lora_dropout=0.05,
    bias="none",
    random_state=3407,
    use_dora=True,
)
model.print_trainable_parameters()

# %% [markdown]
# ## Cell 4 — train

# %%
from datasets import Dataset
from trl import SFTTrainer, SFTConfig
from unsloth.trainer import UnslothVisionDataCollator


def _normalize_chat(record):
    for msg in record.get("messages", []):
        if isinstance(msg.get("content"), str):
            msg["content"] = [{"type": "text", "text": msg["content"]}]
    return record


with open(train_jsonl) as f:
    train_records = [_normalize_chat(json.loads(line)) for line in f if line.strip()]
train_ds = Dataset.from_list(train_records)
print(f"Train rows: {len(train_ds)}")

FastVisionModel.for_training(model)
# v8: max_steps reduced 500 → 300. Train loss hit 0.0004 by step ~130 in v6/v7,
# indicating deep overfit. Stopping earlier preserves more general features.
max_steps = 30 if SMOKE_TEST else 300
save_steps = 10 if SMOKE_TEST else 75

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
        # v8: lowered LR per DoRA's "use slightly lower learning rate than LoRA"
        # recommendation. Was 2e-4.
        learning_rate=1e-4,
        fp16=True, bf16=False,  # T4 doesn't support bf16
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
# ## Cell 5 — eval (HF Transformers path, with images passed correctly)

# %%
import torch
from sklearn.metrics import classification_report, confusion_matrix

FastVisionModel.for_inference(model)
print(f"PEFT adapters: {list(model.peft_config.keys()) if hasattr(model, 'peft_config') else 'NONE'}")


def predict_raw(image_path: str) -> str:
    image = Image.open(image_path).convert("RGB")
    messages = [{"role": "user", "content": [
        {"type": "image"},
        {"type": "text", "text": PROMPT},
    ]}]
    input_text = tokenizer.apply_chat_template(messages, add_generation_prompt=True)
    inputs = tokenizer(
        image, input_text, add_special_tokens=False, return_tensors="pt",
    ).to("cuda")
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=128, do_sample=False)
    return tokenizer.batch_decode(
        out[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True,
    )[0]


eval_rows = splits["test"] if splits["test"] else splits["val"]
eval_cap = 50 if SMOKE_TEST else 400
eval_rows = eval_rows[:eval_cap]
print(f"Evaluating on {len(eval_rows)} rows")

y_true, y_pred, y_source = [], [], []
parse_counts = {"ok": 0, "off_schema": 0, "empty": 0, "bad_class": 0}
raw_samples: list[dict] = []

for row in tqdm(eval_rows, desc="eval"):
    raw = predict_raw(row["path"])
    parsed = parse_model_output(raw)
    parse_counts[parsed["parse_status"]] += 1
    if len(raw_samples) < 12:
        raw_samples.append({"label": row["label"], "source": row.get("source", "?"), **parsed})
    if parsed["parse_status"] == "ok":
        y_true.append(row["label"])
        y_pred.append(parsed["finding_type"])
        y_source.append(row.get("source", "?"))

if y_true:
    report = classification_report(
        y_true, y_pred, labels=FINDING_TYPES, output_dict=True, zero_division=0,
    )
    cm = confusion_matrix(y_true, y_pred, labels=FINDING_TYPES).tolist()
    binary_acc = sum(t == p for t, p in zip(y_true, y_pred)) / len(y_true)
    victim_recall = report["victim"].get("recall", 0.0)
    victim_precision = report["victim"].get("precision", 0.0)
    # Per-source accuracy — H1 vs H2 vs H3 test.
    # H1 (real victim detection): C2A and SARD should be similar accuracy.
    # H2 (C2A synthesis artifact): C2A accuracy >> SARD accuracy.
    # H3 (disaster scene proxy): both C2A and SARD high (both have disaster context).
    per_source = {}
    # Sorted iteration keeps log output deterministic across runs.
    for src in sorted(set(y_source)):
        idxs = [i for i, s in enumerate(y_source) if s == src]
        if not idxs:
            continue
        src_correct = sum(y_true[i] == y_pred[i] for i in idxs)
        per_source[src] = {
            "n": len(idxs),
            "accuracy": src_correct / len(idxs),
            "labels": dict(Counter(y_true[i] for i in idxs)),
        }
else:
    report, cm, binary_acc, victim_recall, victim_precision, per_source = {}, [], None, None, None, {}

parse_rate_ok = parse_counts["ok"] / max(1, len(eval_rows))
eval_summary = {
    "smoke_test": SMOKE_TEST,
    "dataset": "c2a+aider+sard",
    "n_eval": len(eval_rows),
    "parse_counts": parse_counts,
    "parse_rate_ok": parse_rate_ok,
    "binary_acc": binary_acc,
    "victim_recall": victim_recall,
    "victim_precision": victim_precision,
    "per_source_accuracy": per_source,
    "per_class_report": report,
    "confusion_matrix": cm,
    "confusion_matrix_labels": FINDING_TYPES,
    "raw_samples": raw_samples,
}
eval_path = WORK / "eval_summary.json"
eval_path.write_text(json.dumps(eval_summary, indent=2))
print(json.dumps({k: v for k, v in eval_summary.items() if k != "raw_samples"}, indent=2))

# %% [markdown]
# ## Cell 6 — merge + push to Kaggle private Model

# %%
print(f"Pre-cleanup disk:")
os.system("df -h /kaggle/working")
for sub in ("checkpoints", "model_init"):
    p = WORK / sub
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)
print(f"Post-cleanup disk:")
os.system("df -h /kaggle/working")

merged_dir = WORK / "adapter"
merged_dir.mkdir(parents=True, exist_ok=True)
model.save_pretrained(str(merged_dir))     # LoRA adapter only (~200MB)
tokenizer.save_pretrained(str(merged_dir))
(merged_dir / "BASE_MODEL.txt").write_text(MODEL_ID + "\n")
shutil.copy(eval_path, merged_dir / "eval_summary.json")

# Bundle I/O contract.
(merged_dir / "prompts.py").write_text(f'''"""I/O contract for the C2A victim-detection adapter."""
import json, re
FINDING_TYPES = {FINDING_TYPES!r}
PROMPT = {PROMPT!r}
_JSON_BLOCK = re.compile(r"\\{{.*?\\}}", re.DOTALL)
def _extract_json(text):
    try: return json.loads(text)
    except json.JSONDecodeError: pass
    m = _JSON_BLOCK.search(text)
    if not m: return None
    try: return json.loads(m.group(0))
    except json.JSONDecodeError: return None
def parse_model_output(raw):
    if raw is None or not raw.strip():
        return {{"parse_status": "empty", "finding_type": None, "raw": raw}}
    obj = _extract_json(raw.strip())
    if obj is None:
        return {{"parse_status": "off_schema", "finding_type": None, "raw": raw}}
    ft = obj.get("finding_type")
    if ft not in FINDING_TYPES:
        return {{"parse_status": "bad_class", "finding_type": None, "raw": raw}}
    return {{"parse_status": "ok", "finding_type": ft, "confidence": obj.get("confidence"), "visual_evidence": obj.get("visual_evidence"), "raw": raw}}
''')

# Qasim loader for the actual GATE 3 test on placeholder_victim_01.jpg.
qasim_loader = '''"""qasim_inference.py — Gemma 4 E2B + C2A victim LoRA adapter on a CUDA box.

Usage:
    pip install transformers accelerate peft pillow torch
    python qasim_inference.py path/to/aerial_image.jpg
"""
import sys, json
from pathlib import Path
import torch
from transformers import AutoModelForImageTextToText, AutoProcessor
from peft import PeftModel
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
from prompts import PROMPT, parse_model_output
MODEL_DIR = Path(__file__).parent
BASE = (MODEL_DIR / "BASE_MODEL.txt").read_text().strip()
processor = AutoProcessor.from_pretrained(BASE)
base_model = AutoModelForImageTextToText.from_pretrained(BASE, torch_dtype=torch.float16, device_map="cuda")
model = PeftModel.from_pretrained(base_model, MODEL_DIR)
model.eval()
img = Image.open(sys.argv[1]).convert("RGB")
messages = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": PROMPT}]}]
input_text = processor.apply_chat_template(messages, add_generation_prompt=True)
inputs = processor(text=input_text, images=img, add_special_tokens=False, return_tensors="pt").to("cuda")
with torch.no_grad():
    out = model.generate(**inputs, max_new_tokens=128, do_sample=False)
raw = processor.batch_decode(out[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True)[0]
print(json.dumps(parse_model_output(raw), indent=2))
'''
(merged_dir / "qasim_inference.py").write_text(qasim_loader)

MODEL_SLUG = "ibrahimahmed7860/gemma4-e2b-victim-vision-lora-c2a"
FRAMEWORK = "transformers"
VARIATION = "lora-c2a-bf16"
binary_str = f"{binary_acc:.3f}" if binary_acc is not None else "n/a"
recall_str = f"{victim_recall:.3f}" if victim_recall is not None else "n/a"
VERSION_NOTES = (
    f"smoke={SMOKE_TEST} | parse_ok={parse_rate_ok:.2f} | "
    f"binary_acc={binary_str} | victim_recall={recall_str} | n_eval={len(eval_rows)}"
)

(merged_dir / "model-instance-metadata.json").write_text(json.dumps({
    "ownerSlug": "ibrahimahmed7860",
    "modelSlug": "gemma4-e2b-victim-vision-lora-c2a",
    "instanceSlug": VARIATION,
    "framework": FRAMEWORK,
    "overview": "Gemma 4 E2B + Unsloth vision LoRA for victim detection on C2A disaster aerial imagery.",
    "usage": "See qasim_inference.py bundled in this version.",
    "licenseName": "Apache 2.0",
    "fineTunable": True,
    "trainingData": ["rgbnihal/c2a-dataset"],
}, indent=2))


def run_kaggle(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


model_init_dir = WORK / "model_init"
model_init_dir.mkdir(exist_ok=True)
(model_init_dir / "model-metadata.json").write_text(json.dumps({
    "ownerSlug": "ibrahimahmed7860",
    "title": "Gemma 4 E2B Victim Vision LoRA C2A",
    "slug": "gemma4-e2b-victim-vision-lora-c2a",
    "subtitle": "Victim detection LoRA for Gemma 4 E2B trained on C2A",
    "description": (
        "Vision LoRA adapter for Gemma 4 E2B trained on the C2A disaster "
        "human-detection dataset (rgbnihal/c2a-dataset). Output schema is the "
        "FieldAgent report_finding contract (finding_type: victim | none, "
        "confidence, visual_evidence). Produced for the Gemma 4 Good Hackathon "
        "(May 2026) GATE 3 acceptance test. Load via bundled qasim_inference.py."
    ),
    "isPrivate": True,
    "licenseName": "Apache 2.0",
    "keywords": ["gemma", "vision", "lora", "c2a", "victim-detection", "search-rescue"],
}, indent=2))

rc, out, err = run_kaggle(["kaggle", "models", "create", "-p", str(model_init_dir)])
if rc != 0 and "already exists" not in (out + err).lower():
    print(f"Model create failed:\n{out}\n{err}")
    tar_path = WORK / "artifacts.tar.gz"
    os.system(f"tar -czf {tar_path} -C {merged_dir.parent} {merged_dir.name}")
    raise SystemExit(0)
print("Model entry ready.")

rc, out, err = run_kaggle([
    "kaggle", "models", "instances", "versions", "create",
    f"{MODEL_SLUG}/{FRAMEWORK}/{VARIATION}",
    "-p", str(merged_dir),
    "-n", VERSION_NOTES,
])
if rc == 0:
    print(f"Model version pushed: {MODEL_SLUG}/{FRAMEWORK}/{VARIATION}")
else:
    print(f"Model version push failed (rc={rc}):\n{out}\n{err}")
    tar_path = WORK / "artifacts.tar.gz"
    os.system(f"tar -czf {tar_path} -C {merged_dir.parent} {merged_dir.name}")
