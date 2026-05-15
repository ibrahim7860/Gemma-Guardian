"""Kaggle kernel: Gemma 4 E2B Vision LoRA fine-tune on xBD.

SELF-CONTAINED. Kaggle CLI's `kaggle kernels push -p folder` uploads ONLY the
code_file (despite docs implying otherwise), so prompts.py and preprocess.py
contents are vendored inline here. Source of truth for those modules lives in
kaggle_work/{prompts,preprocess}.py for local tests; this file duplicates them.
Re-sync manually if either module changes.

Runs as a Kaggle batch script (kernel_type=script). Hardware target: P100 16 GB.
Internet ON (pip install Unsloth + push final model to Kaggle private Models).
Dataset attached: tunguz/xview2-challenge-dataset-train-and-test at /kaggle/input/.

DECISIONS LOCKED via /plan-eng-review (2026-05-14):
  A1: Output schema matches ml/data_prep/format_for_gemma.py JSON envelope.
  A2: load_in_4bit=True (matches ml/training/finetune_lora.py:58).
  A3: Removed proxy 3-run trigger; real victim test runs on Qasim's box.
  A4: Real exit-code check on model push, distinguishes "exists" vs fatal.
  A5: predict() records parse_status; no silent coercion.
  A6: Cell 1 unconditionally dumps /kaggle/input/ tree.
  C3: TARGET_SIZE = 224 (matches crop_patches.py).
  P2: Class-balanced sampling caps output well under /kaggle/working's 19GB.
"""

# %% [markdown]
# ## Cell 1 — env + UNCONDITIONAL /kaggle/input tree dump

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
from typing import Iterable, Optional

# SMOKE_TEST: tiny slice for pipeline validation. Flip to False for the real run.
# v12 (smoke) confirmed predict_raw now passes images to the model: outputs went
# from "I need an image" → "the image is blurry". v13 (SMOKE_TEST=False): full
# 500-step training + 800-sample eval with working inference path.
SMOKE_TEST = False  # v19: v18 smoke confirmed stratified split works; full run for real per-class metrics

INPUT_ROOT = Path("/kaggle/input")
# Kaggle mounts cross-user datasets at /kaggle/input/datasets/<owner>/<slug>/
# (NOT the typical /kaggle/input/<slug>/ — empirically confirmed via v2 tree dump).
INPUT_EXPECTED = INPUT_ROOT / "datasets" / "tunguz" / "xview2-challenge-dataset-train-and-test"
# Fallback: if dataset is mounted at the simple path on some Kaggle envs.
INPUT_FALLBACK = INPUT_ROOT / "xview2-challenge-dataset-train-and-test"
if not INPUT_EXPECTED.exists() and INPUT_FALLBACK.exists():
    INPUT_EXPECTED = INPUT_FALLBACK
WORK = Path("/kaggle/working")
WORK.mkdir(parents=True, exist_ok=True)

print(f"SMOKE_TEST = {SMOKE_TEST}")
print(f"INPUT_ROOT.exists() = {INPUT_ROOT.exists()}")
print(f"INPUT_EXPECTED.exists() = {INPUT_EXPECTED.exists()}")

# Surface GPU info. Kaggle's pre-baked PyTorch dropped sm_60 (Tesla P100)
# kernels, so we need T4 (sm_75) or newer. See Unsloth issue #3182.
print("\nGPU info:")
os.system("nvidia-smi --query-gpu=name,compute_cap,driver_version,memory.total --format=csv 2>/dev/null || echo 'nvidia-smi unavailable'")

# A6: ALWAYS dump /kaggle/input tree so we can diagnose dataset-attach failures.
if INPUT_ROOT.exists():
    print("\n/kaggle/input/ top-level entries:")
    for p in sorted(INPUT_ROOT.iterdir()):
        print(f"  {p.name} (dir={p.is_dir()})")
    print("\n/kaggle/input/ tree (depth 3, first 80 entries):")
    n = 0
    for p in sorted(INPUT_ROOT.rglob("*")):
        rel = p.relative_to(INPUT_ROOT)
        if len(rel.parts) <= 3:
            print(f"  {rel}")
            n += 1
            if n >= 80:
                print("  ... (truncated)")
                break
else:
    print("ERROR: /kaggle/input does not exist. Dataset not attached.")
    raise RuntimeError("No /kaggle/input — kernel cannot proceed.")

# Connectivity check before pip install.
print("\nConnectivity check:")
rc = os.system("curl -sS --max-time 10 https://pypi.org/simple/ -o /dev/null -w 'pypi HTTP %{http_code}\\n' 2>&1")
print(f"curl exit code: {rc}")

os.system("pip install -q --upgrade pip")
# bitsandbytes is needed for load_in_4bit=True.
os.system("pip install -q unsloth bitsandbytes")
os.system("pip install -q datasets pillow shapely tqdm scikit-learn")

# %% [markdown]
# ## Cell 1b — VENDORED constants + functions (from kaggle_work/{prompts,preprocess}.py)

# %%
# ----- prompts.py contents -----
CLASS_LABELS = ["no-damage", "minor-damage", "major-damage", "destroyed"]
CLASS_TO_LABEL = {
    "no-damage": "no_damage",
    "minor-damage": "minor_damage",
    "major-damage": "major_damage",
    "destroyed": "destroyed",
}
LABEL_TO_CLASS = {v: k for k, v in CLASS_TO_LABEL.items()}

# v16: prompt was too soft. Original "Classify the damage" let Gemma's instruction-
# tuned hedging instinct take over (model refused to classify "blurry" satellite
# crops). Stronger directive: explicit JSON schema, no hedge, no refusal.
PROMPT = (
    "Classify the building damage in this aerial image. "
    "Respond with ONLY a JSON object in this exact format: "
    '{"damage_class": <one of: no_damage, minor_damage, major_damage, destroyed>, '
    '"confidence": <float between 0 and 1>, '
    '"visual_evidence": <brief description>}. '
    "Do not include any other text. Do not refuse. Do not hedge."
)

EVIDENCE_BY_CLASS = {
    "no-damage": "Building intact, walls and roof appear undamaged.",
    "minor-damage": "Visible cracks or broken windows, structure largely intact.",
    "major-damage": "Partial collapse, missing roof sections, structural deformation.",
    "destroyed": "Structure reduced to rubble, no recognizable form.",
}


def to_chat_example(image_path: str, label: str) -> dict:
    if label not in CLASS_TO_LABEL:
        raise ValueError(f"Unknown damage class: {label!r}")
    return {
        "messages": [
            {"role": "user", "content": [
                {"type": "image", "image": image_path},
                {"type": "text", "text": PROMPT},
            ]},
            {"role": "assistant", "content": json.dumps({
                "damage_class": CLASS_TO_LABEL[label],
                "confidence": 0.9,
                "visual_evidence": EVIDENCE_BY_CLASS[label],
            })},
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
        return {"parse_status": "empty", "damage_class": None, "raw": raw}
    obj = _extract_json(raw.strip())
    if obj is None:
        return {"parse_status": "off_schema", "damage_class": None, "raw": raw}
    dc = obj.get("damage_class")
    if dc not in LABEL_TO_CLASS:
        return {"parse_status": "bad_class", "damage_class": None, "raw": raw}
    return {
        "parse_status": "ok",
        "damage_class": LABEL_TO_CLASS[dc],
        "confidence": obj.get("confidence"),
        "visual_evidence": obj.get("visual_evidence"),
        "raw": raw,
    }


# ----- preprocess.py contents -----
TARGET_SIZE = 224
PADDING = 1.2

DEFAULT_TRAIN_DISASTERS = [
    "hurricane-florence", "hurricane-harvey", "hurricane-matthew",
    "midwest-flooding", "palu-tsunami", "santa-rosa-wildfire",
    "socal-fire", "guatemala-volcano",
]
DEFAULT_VAL_DISASTERS = ["mexico-earthquake", "moore-tornado"]
DEFAULT_TEST_DISASTERS = ["joplin-tornado", "lower-puna-volcano", "nepal-flooding"]


def find_xbd_root(base: Path) -> Path:
    if not base.exists():
        raise FileNotFoundError(f"Base path does not exist: {base}")
    candidates = [base]
    for child in sorted(p for p in base.iterdir() if p.is_dir()):
        candidates.append(child)
    for c in candidates:
        if (c / "train" / "images").exists():
            return c
        if (c / "images").exists() and (c / "labels").exists():
            return c.parent if c.name in ("train", "test", "tier3", "hold") else c
    raise RuntimeError(
        f"Could not find xBD layout under {base}. "
        f"Top-level entries: {sorted(p.name for p in base.iterdir())}"
    )


def collect_post_disaster_pairs(split_root: Path) -> list[tuple[Path, Path]]:
    imgs_dir = split_root / "images"
    lbls_dir = split_root / "labels"
    if not imgs_dir.exists() or not lbls_dir.exists():
        return []
    pairs = []
    for img in sorted(imgs_dir.glob("*_post_disaster.png")):
        lbl = lbls_dir / (img.stem + ".json")
        if lbl.exists():
            pairs.append((img, lbl))
    return pairs


def _wkt_bbox(wkt):
    if not wkt:
        return None
    try:
        from shapely.wkt import loads as wkt_loads
        poly = wkt_loads(wkt)
    except Exception:
        return None
    minx, miny, maxx, maxy = poly.bounds
    return (minx, miny, maxx, maxy)


def _pad_bbox(bbox, img_shape, pad_factor):
    h, w = img_shape
    x1, y1, x2, y2 = bbox
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    bw, bh = (x2 - x1) * pad_factor, (y2 - y1) * pad_factor
    x1p = max(0, int(cx - bw / 2))
    x2p = min(w, int(cx + bw / 2))
    y1p = max(0, int(cy - bh / 2))
    y2p = min(h, int(cy + bh / 2))
    return x1p, y1p, x2p, y2p


def crop_buildings(img_path: Path, lbl_path: Path, out_dir: Path,
                   target_size: int = TARGET_SIZE, padding: float = PADDING) -> list[dict]:
    from PIL import Image
    rows: list[dict] = []
    try:
        img = Image.open(img_path).convert("RGB")
    except Exception:
        return rows
    W, H = img.size
    try:
        meta = json.loads(lbl_path.read_text())
    except (json.JSONDecodeError, OSError):
        return rows
    disaster = meta.get("metadata", {}).get("disaster") or lbl_path.stem.split("_", 1)[0]
    features = meta.get("features", {}).get("xy", [])
    for feat in features:
        props = feat.get("properties", {})
        damage = props.get("subtype")
        if damage not in CLASS_LABELS:
            continue
        bbox = _wkt_bbox(feat.get("wkt"))
        if bbox is None:
            continue
        x1, y1, x2, y2 = _pad_bbox(bbox, (H, W), padding)
        if x2 - x1 < 8 or y2 - y1 < 8:
            continue
        try:
            crop = img.crop((x1, y1, x2, y2)).resize((target_size, target_size), Image.LANCZOS)
        except Exception:
            continue
        class_dir = out_dir / damage
        class_dir.mkdir(parents=True, exist_ok=True)
        uid = props.get("uid") or f"{len(rows)}"
        out_path = class_dir / f"{disaster}_{lbl_path.stem}_{uid}.jpg"
        crop.save(out_path, quality=88)
        rows.append({
            "path": str(out_path),
            "label": damage,
            "disaster": disaster,
            "building_uid": uid,
        })
    return rows


def split_by_disaster(rows, train_disasters=DEFAULT_TRAIN_DISASTERS,
                     val_disasters=DEFAULT_VAL_DISASTERS,
                     test_disasters=DEFAULT_TEST_DISASTERS):
    out = {"train": [], "val": [], "test": []}
    for r in rows:
        d = r["disaster"]
        if d in test_disasters:
            out["test"].append(r)
        elif d in val_disasters:
            out["val"].append(r)
        else:
            out["train"].append(r)
    return out


def class_balance(rows, max_per_class: int, seed: int = 3407):
    rng = random.Random(seed)
    by_class = defaultdict(list)
    for r in rows:
        by_class[r["label"]].append(r)
    capped = []
    for cls, items in by_class.items():
        rng.shuffle(items)
        capped.extend(items[:max_per_class])
    rng.shuffle(capped)
    return capped


def write_chat_jsonl(rows, out_path: Path) -> int:
    n = 0
    with out_path.open("w") as f:
        for r in rows:
            f.write(json.dumps(to_chat_example(r["path"], r["label"])) + "\n")
            n += 1
    return n


# %% [markdown]
# ## Cell 2 — preprocess xBD

# %%
from tqdm import tqdm

xbd_root = find_xbd_root(INPUT_EXPECTED)
print(f"xBD root: {xbd_root}")

crops_dir = WORK / "crops"
crops_dir.mkdir(parents=True, exist_ok=True)

tiles_per_split_cap = 50 if SMOKE_TEST else None
per_class_cap = 200 if SMOKE_TEST else 5000

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
raw_dist = Counter(r["label"] for r in all_rows)
print(f"Raw class distribution: {dict(raw_dist)}")

balanced = class_balance(all_rows, max_per_class=per_class_cap)
balanced_dist = Counter(r["label"] for r in balanced)
print(f"Balanced class distribution (cap={per_class_cap}): {dict(balanced_dist)}")

# v18: stratified random split instead of disaster-held-out. v17 eval was
# 97% no-damage because val disasters (mexico-earthquake + moore-tornado)
# happen to have overwhelmingly no-damage buildings, making the eval
# meaningless (naive always-no-damage would score 97%). Stratify per-class.
EVAL_PER_CLASS = 50 if SMOKE_TEST else 200
TEST_PER_CLASS = 50 if SMOKE_TEST else 200

_rng = random.Random(3407)
_by_class: dict[str, list[dict]] = defaultdict(list)
for r in balanced:
    _by_class[r["label"]].append(r)
splits = {"train": [], "val": [], "test": []}
for cls, items in _by_class.items():
    _rng.shuffle(items)
    val_slice = items[:EVAL_PER_CLASS]
    test_slice = items[EVAL_PER_CLASS:EVAL_PER_CLASS + TEST_PER_CLASS]
    train_slice = items[EVAL_PER_CLASS + TEST_PER_CLASS:]
    splits["val"].extend(val_slice)
    splits["test"].extend(test_slice)
    splits["train"].extend(train_slice)
_rng.shuffle(splits["train"])
_rng.shuffle(splits["val"])
_rng.shuffle(splits["test"])
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
from datasets import Dataset
from trl import SFTTrainer, SFTConfig
from unsloth.trainer import UnslothVisionDataCollator

# load_dataset("json", ...) chokes on our nested-message JSONL (pandas/pyarrow
# error: "Trailing data"). Build the Dataset from a list of dicts directly.
# Also normalize: assistant content arrives as a JSON string from format_for_gemma,
# but PyArrow can't unify a column where some rows are str and others are list
# ("cannot mix list and non-list, non-null values"). Wrap string content into
# a [{"type": "text", "text": ...}] list so the schema is uniform.
def _normalize_chat(record):
    for msg in record.get("messages", []):
        if isinstance(msg.get("content"), str):
            msg["content"] = [{"type": "text", "text": msg["content"]}]
    return record

with open(train_jsonl) as f:
    train_records = [_normalize_chat(json.loads(line)) for line in f if line.strip()]
train_ds = Dataset.from_list(train_records)
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
        # T4 (sm_75 Turing) does not support bf16 — only Ampere+ does. Use fp16.
        # For full Stage-2 run on an A100/L4/H100 box, flip to bf16.
        fp16=True,
        bf16=False,
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

# v14 attempted train_on_responses_only but it crashed: that helper is text-only.
# Vision SFT uses UnslothVisionDataCollator which has its own batching. Leaving
# the trainer as configured and adding diagnostics post-train to figure out why
# the LoRA isn't producing JSON output at inference time.
stats = trainer.train()
print(stats)

# DIAGNOSTIC (v15): immediately after training, run ONE inference sample using
# the exact same code path that eval will use, and dump everything we need to
# diagnose Diagnosis C (template mismatch), D (LoRA not applied), E (other).
import torch  # needed for the diagnostic; re-imported in Cell 5 (idempotent).
print("\n=== POST-TRAIN INFERENCE DIAGNOSTIC ===")
FastVisionModel.for_inference(model)

# (D) PEFT adapter check
if hasattr(model, "peft_config"):
    print(f"PEFT adapters loaded: {list(model.peft_config.keys())}")
    for name, cfg in model.peft_config.items():
        print(f"  {name}: r={getattr(cfg, 'r', '?')} target_modules={getattr(cfg, 'target_modules', '?')!s:.80s}")
else:
    print("WARNING: model has no peft_config — LoRA may be detached")

# Show what the model was TRAINED on for the first row.
first_row = train_records[0]
print(f"\nFirst training row messages:")
print(json.dumps(first_row["messages"], indent=2)[:800])

# Show what apply_chat_template renders for an EVAL prompt (no assistant turn).
from PIL import Image as _DiagImage
diag_img_path = first_row["messages"][0]["content"][0].get("image")
if diag_img_path and Path(diag_img_path).exists():
    diag_img = _DiagImage.open(diag_img_path).convert("RGB")
    eval_messages = [
        {"role": "user", "content": [
            {"type": "image"},
            {"type": "text", "text": PROMPT},
        ]},
    ]
    eval_text = tokenizer.apply_chat_template(eval_messages, add_generation_prompt=True)
    print(f"\nEval-template rendered text (first 500 chars):")
    print(repr(eval_text[:500]))

    # And what the training-template would have rendered (with assistant turn).
    train_messages_for_template = first_row["messages"]
    train_text = tokenizer.apply_chat_template(train_messages_for_template, add_generation_prompt=False)
    print(f"\nTraining-template rendered text (first 800 chars):")
    print(repr(train_text[:800]))

    # Run TWO inferences: one with LoRA enabled (trained), one with LoRA disabled (baseline).
    # If both produce prose → LoRA learned nothing, problem is training masking.
    # If LoRA-enabled produces JSON-ish, LoRA-disabled produces prose → LoRA works, full run will help.
    diag_inputs = tokenizer(
        diag_img, eval_text, add_special_tokens=False, return_tensors="pt",
    ).to("cuda")

    # ENABLED (trained adapter)
    with torch.no_grad():
        diag_out = model.generate(**diag_inputs, max_new_tokens=128, do_sample=False)
    diag_raw_trained = tokenizer.batch_decode(
        diag_out[:, diag_inputs["input_ids"].shape[1]:], skip_special_tokens=True,
    )[0]
    print(f"\n[ADAPTER ENABLED] output:")
    print(repr(diag_raw_trained[:500]))

    # DISABLED (baseline Gemma 4 E2B)
    try:
        model.disable_adapters()
        with torch.no_grad():
            base_out = model.generate(**diag_inputs, max_new_tokens=128, do_sample=False)
        base_raw = tokenizer.batch_decode(
            base_out[:, diag_inputs["input_ids"].shape[1]:], skip_special_tokens=True,
        )[0]
        print(f"\n[ADAPTER DISABLED — baseline Gemma] output:")
        print(repr(base_raw[:500]))
    except Exception as e:
        print(f"Could not disable adapters: {e}")
    finally:
        try:
            model.enable_adapters()
        except Exception:
            pass
print("=== END DIAGNOSTIC ===\n")

# %% [markdown]
# ## Cell 5 — eval

# %%
import torch
from sklearn.metrics import classification_report, confusion_matrix

FastVisionModel.for_inference(model)

# Rule-out diagnosis: verify the LoRA adapter is actually attached at eval time.
# If peft_config is empty here, FastVisionModel.for_inference detached it.
if hasattr(model, "peft_config"):
    print(f"PEFT adapters at eval: {list(model.peft_config.keys())}")
else:
    print("WARNING: model has no peft_config attribute — LoRA may be detached")

from PIL import Image as _PILImage


def predict_raw(image_path: str) -> str:
    """Unsloth's recommended vision-inference pattern.

    CRITICAL: tokenizer.apply_chat_template does NOT auto-load images from path
    strings. We must open the image as a PIL object and pass it through the
    tokenizer/processor as a separate argument. Training works around this via
    UnslothVisionDataCollator (which loads images from path strings at batch
    time); inference has no such collator, so we have to do it ourselves.

    v11 produced an unevaluable adapter (parse_rate_ok=0) because predict_raw
    passed only a path string — the model received the user prompt but no image
    features and replied "Please provide the image you are referring to."
    """
    image = _PILImage.open(image_path).convert("RGB")
    messages = [
        {"role": "user", "content": [
            {"type": "image"},
            {"type": "text", "text": PROMPT},
        ]},
    ]
    input_text = tokenizer.apply_chat_template(messages, add_generation_prompt=True)
    inputs = tokenizer(
        image,
        input_text,
        add_special_tokens=False,
        return_tensors="pt",
    ).to("cuda")
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=128, do_sample=False)
    return tokenizer.batch_decode(
        out[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True
    )[0]


# Fallback chain: test → val → tail of train. Smoke runs with a 50-tile cap
# often have empty val/test because the first 50 tiles all belong to
# training-disasters per split_by_disaster's held-out policy.
if splits["test"]:
    eval_rows = splits["test"]
    eval_source = "test"
elif splits["val"]:
    eval_rows = splits["val"]
    eval_source = "val"
else:
    # Take last 20% of train as a stand-in eval for the smoke run.
    holdout = max(1, len(splits["train"]) // 5)
    eval_rows = splits["train"][-holdout:]
    eval_source = "train_tail (smoke fallback — overlaps with training set)"

eval_cap = 50 if SMOKE_TEST else 800
eval_rows = eval_rows[:eval_cap]
print(f"Evaluating on {len(eval_rows)} rows from {eval_source}")

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
# ## Cell 6 — merge + push to Kaggle private Model

# %%
# Free disk BEFORE saving the merged 10GB model. /kaggle/working is capped at
# ~19GB; checkpoints (LoRA snapshots) + crops + Unsloth's temp shards push us
# over without this cleanup. v8 demonstrated the OSError(28) failure mode.
def _du_h(path: Path) -> str:
    try:
        out = subprocess.run(["du", "-sh", str(path)], capture_output=True, text=True)
        return out.stdout.strip()
    except Exception:
        return "?"

print(f"Pre-cleanup disk:")
os.system("df -h /kaggle/working")
for sub in ("checkpoints", "crops", "model_init"):
    p = WORK / sub
    if p.exists():
        print(f"  removing {p} ({_du_h(p)})")
        shutil.rmtree(p, ignore_errors=True)
print(f"Post-cleanup disk:")
os.system("df -h /kaggle/working")

# Save LoRA-only (~200MB) instead of merged_16bit (~10GB). /kaggle/working is
# capped at 19GB and v8/v9 demonstrated the 10GB merged save runs out even
# after cleaning checkpoints + crops. The LoRA adapter is the actual transferable
# artifact; Qasim loads base + adapter at runtime via PEFT.
merged_dir = WORK / "merged_model"  # name kept for downstream references
merged_dir.mkdir(parents=True, exist_ok=True)
model.save_pretrained(str(merged_dir))     # LoRA adapter weights + adapter_config.json
tokenizer.save_pretrained(str(merged_dir)) # tokenizer for chat template
# Marker file so qasim_inference knows this is an adapter, not a merged model.
(merged_dir / "BASE_MODEL.txt").write_text(MODEL_ID + "\n")
print(f"LoRA adapter saved to {merged_dir}")
os.system(f"du -sh {merged_dir} 2>/dev/null")

shutil.copy(eval_path, merged_dir / "eval_summary.json")

# Bundle prompts (the I/O contract) as a tiny file for Qasim's inference script.
(merged_dir / "prompts.py").write_text(f'''"""I/O contract for the merged model. Mirrors training-time schema."""
import json, re
CLASS_LABELS = {CLASS_LABELS!r}
CLASS_TO_LABEL = {CLASS_TO_LABEL!r}
LABEL_TO_CLASS = {{v: k for k, v in CLASS_TO_LABEL.items()}}
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
        return {{"parse_status": "empty", "damage_class": None, "raw": raw}}
    obj = _extract_json(raw.strip())
    if obj is None:
        return {{"parse_status": "off_schema", "damage_class": None, "raw": raw}}
    dc = obj.get("damage_class")
    if dc not in LABEL_TO_CLASS:
        return {{"parse_status": "bad_class", "damage_class": None, "raw": raw}}
    return {{"parse_status": "ok", "damage_class": LABEL_TO_CLASS[dc], "confidence": obj.get("confidence"), "visual_evidence": obj.get("visual_evidence"), "raw": raw}}
''')

qasim_loader = '''"""qasim_inference.py — load Gemma 4 E2B base + vision LoRA adapter on a CUDA box.

This artifact ships the LoRA adapter only (not the merged 10GB model). The base
model name is in BASE_MODEL.txt; we attach the adapter via PEFT at load time.

Usage:
    pip install transformers accelerate peft pillow torch
    python qasim_inference.py path/to/image.jpg
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

# float16 works on T4/V100/P100/Ampere+. Use bfloat16 only if you know your GPU
# supports it (Ampere sm_80+).
processor = AutoProcessor.from_pretrained(BASE)
base_model = AutoModelForImageTextToText.from_pretrained(
    BASE, torch_dtype=torch.float16, device_map="cuda"
)
model = PeftModel.from_pretrained(base_model, MODEL_DIR)
model.eval()

img = Image.open(sys.argv[1]).convert("RGB")
messages = [{"role": "user", "content": [
    {"type": "image"},
    {"type": "text", "text": PROMPT},
]}]
# Apply chat template to get text-with-image-placeholder, then pass image
# explicitly to the processor. Image MUST be passed via the images= kwarg of
# the processor call (or as a separate positional arg) — putting it inside the
# message content dict does NOT auto-load it for most processors.
input_text = processor.apply_chat_template(messages, add_generation_prompt=True)
inputs = processor(
    text=input_text,
    images=img,
    add_special_tokens=False,
    return_tensors="pt",
).to("cuda")
with torch.no_grad():
    out = model.generate(**inputs, max_new_tokens=128, do_sample=False)
raw = processor.batch_decode(
    out[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True
)[0]
print(json.dumps(parse_model_output(raw), indent=2))
'''
(merged_dir / "qasim_inference.py").write_text(qasim_loader)

MODEL_SLUG = "ibrahimahmed7860/gemma4-e2b-xbd-vision-lora"
FRAMEWORK = "transformers"
VARIATION = "lora-merged-bf16"
n_eval_safe = max(1, len(eval_rows))
binary_acc_str = f"{binary_acc:.3f}" if binary_acc is not None else "n/a"
VERSION_NOTES = (
    f"smoke={SMOKE_TEST} | parse_ok={parse_rate_ok:.2f} | "
    f"binary_acc={binary_acc_str} | n_eval={n_eval_safe}"
)

(merged_dir / "model-instance-metadata.json").write_text(json.dumps({
    "ownerSlug": "ibrahimahmed7860",
    "modelSlug": "gemma4-e2b-xbd-vision-lora",
    "instanceSlug": VARIATION,
    "framework": FRAMEWORK,
    "overview": "Gemma 4 E2B + Unsloth vision LoRA, merged 16-bit. Load via qasim_inference.py.",
    "usage": "See qasim_inference.py bundled in this version.",
    "licenseName": "Apache 2.0",
    "fineTunable": True,
    "trainingData": ["tunguz/xview2-challenge-dataset-train-and-test"],
}, indent=2))


def run_kaggle(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


model_init_dir = WORK / "model_init"
model_init_dir.mkdir(exist_ok=True)
# v9 failed with "Key description not found in data" — Kaggle Models API requires
# title, description, and a few other fields. Adding all of them.
(model_init_dir / "model-metadata.json").write_text(json.dumps({
    "ownerSlug": "ibrahimahmed7860",
    "title": "Gemma 4 E2B Vision LoRA xBD damage",
    "slug": "gemma4-e2b-xbd-vision-lora",
    "subtitle": "Gemma 4 E2B fine-tuned on xBD via Unsloth LoRA",
    "description": (
        "Vision LoRA adapter for Gemma 4 E2B trained on the xBD building damage "
        "dataset (tunguz/xview2-challenge-dataset-train-and-test mirror). Output "
        "schema is a JSON envelope with damage_class, confidence, visual_evidence. "
        "Produced by FieldAgent / Gemma-Guardian for the Gemma 4 Good Hackathon "
        "(May 2026). Load via the bundled qasim_inference.py (PEFT + base + adapter)."
    ),
    "isPrivate": True,
    "licenseName": "Apache 2.0",
    "keywords": ["gemma", "vision", "lora", "xbd", "disaster-response"],
}, indent=2))

rc, out, err = run_kaggle(["kaggle", "models", "create", "-p", str(model_init_dir)])
if rc != 0 and "already exists" not in (out + err).lower():
    print(f"Model create failed (rc={rc}):\nSTDOUT: {out}\nSTDERR: {err}")
    tar_path = WORK / "artifacts.tar.gz"
    os.system(f"tar -czf {tar_path} -C {merged_dir.parent} {merged_dir.name}")
    print(f"Tarball: {tar_path}")
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
    print(f"Model version push failed (rc={rc}):\nSTDOUT: {out}\nSTDERR: {err}")
    tar_path = WORK / "artifacts.tar.gz"
    os.system(f"tar -czf {tar_path} -C {merged_dir.parent} {merged_dir.name}")
    print(f"Tarball: {tar_path}")
