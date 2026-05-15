"""Local tests for the C2A victim-detection kernel's preprocess + I/O contract.

Tests the inlined helper functions from gemma4-victim-vision-lora.py.
Mirrors kaggle_work/tests/test_preprocess.py for parity coverage.

Run with: uv run pytest kaggle_work_c2a/tests/
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# Load the kernel script as a module (hyphenated filename → use importlib).
KERNEL_PATH = Path(__file__).resolve().parents[1] / "gemma4-victim-vision-lora.py"


def _load_kernel_pure():
    """Load the kernel script with side-effects stripped.

    The kernel runs `os.system("pip install ...")` and imports `unsloth` /
    `FastVisionModel` / `SFTTrainer` which only exist in Kaggle's environment.
    We strip those lines and exec the remaining pure-Python logic.
    """
    src_lines = KERNEL_PATH.read_text().splitlines()
    kept = []
    skip_block_imports = False
    for line in src_lines:
        # Skip pip installs.
        if "os.system(" in line and ("pip install" in line or "nvidia-smi" in line):
            kept.append("# stripped: " + line.strip())
            continue
        # Skip unsloth / trl / datasets imports + model load calls — Cell 3+
        if line.strip().startswith("from unsloth") or line.strip().startswith("from trl") or line.strip().startswith("from datasets") or line.strip().startswith("from sklearn"):
            skip_block_imports = True
            kept.append("# stripped: " + line.strip())
            continue
        # Skip lines that REFERENCE model/trainer/tokenizer (Cell 3+ logic)
        if any(tok in line for tok in (
            "FastVisionModel", "SFTTrainer", "SFTConfig",
            "UnslothVisionDataCollator", "Dataset.from_list",
            "tokenizer", "trainer.train", "classification_report",
            "confusion_matrix", "torch.no_grad", "model.generate",
            "model.save_pretrained", "model_init", "subprocess.run",
            "model.peft_config", "model.disable_adapters", "model.enable_adapters",
            "load_dataset",
        )):
            kept.append("# stripped: " + line.strip())
            continue
        kept.append(line)
    return "\n".join(kept)


def _build_module():
    """Build an executable module from the kernel's pure-logic section."""
    code = _load_kernel_pure()
    spec = importlib.util.spec_from_loader("kernel_pure", loader=None)
    module = importlib.util.module_from_spec(spec)
    try:
        exec(code, module.__dict__)
    except Exception as e:
        # If exec fails on the full script, fall back to extracting just
        # the constants + pure helpers via direct string slicing.
        src = KERNEL_PATH.read_text()
        start = src.find("FINDING_TYPES = ")
        end = src.find("# %% [markdown]\n# ## Cell 2")
        if end == -1:
            end = src.find("# %% [markdown]\n# ## Cell 3")
        if start == -1 or end == -1:
            raise RuntimeError(f"Could not slice kernel script: {e}")
        prelude = "import json\nimport re\nfrom typing import Optional\n"
        exec(prelude + src[start:end], module.__dict__)
    return module


@pytest.fixture(scope="module")
def kernel():
    return _build_module()


def _has_attr(kernel, name):
    """Skip helper for symbols that may not exist (e.g., parse_label_file lives
    in cell 2 alongside PIL imports which we may not load)."""
    if not hasattr(kernel, name):
        pytest.skip(f"kernel symbol {name!r} not present in pure-load — skipping")
    return getattr(kernel, name)


# ---------------------------------------------------------------------------
# FINDING_TYPES enum + to_chat_example schema
# ---------------------------------------------------------------------------

def test_finding_types_enum(kernel):
    assert kernel.FINDING_TYPES == ["victim", "none"]


def test_to_chat_example_victim(kernel):
    ex = kernel.to_chat_example("/tmp/test.jpg", "victim", scenario="collapsed_building", n_humans=3)
    assert ex["messages"][0]["role"] == "user"
    assert ex["messages"][1]["role"] == "assistant"
    assert isinstance(ex["messages"][0]["content"], list)
    assert isinstance(ex["messages"][1]["content"], list)
    envelope = json.loads(ex["messages"][1]["content"][0]["text"])
    assert envelope["finding_type"] == "victim"
    # v10: confidence varies by n_humans; 3 humans → 0.85
    assert envelope["confidence"] == 0.85
    assert "visual_evidence" in envelope
    # Evidence should mention "collapsed building" or rubble (scenario-keyed).
    assert any(k in envelope["visual_evidence"].lower() for k in ("collapsed", "building", "rubble", "damaged"))


def test_to_chat_example_none(kernel):
    ex = kernel.to_chat_example("/tmp/test.jpg", "none", scenario="normal")
    envelope = json.loads(ex["messages"][1]["content"][0]["text"])
    assert envelope["finding_type"] == "none"
    # v10: AIDER normal → 0.95 confidence (clearly no disaster, no victim).
    assert envelope["confidence"] == 0.95


def test_to_chat_example_varies_per_image_path(kernel):
    """v10 regression guard: different image paths should pick different
    evidence templates (deterministic via hash, but varied across rows)."""
    ex1 = kernel.to_chat_example("/tmp/img_001.jpg", "victim", scenario="collapsed_building", n_humans=3)
    ex2 = kernel.to_chat_example("/tmp/img_002.jpg", "victim", scenario="collapsed_building", n_humans=3)
    e1 = json.loads(ex1["messages"][1]["content"][0]["text"])["visual_evidence"]
    e2 = json.loads(ex2["messages"][1]["content"][0]["text"])["visual_evidence"]
    # Same scenario+n_humans → 3 template choices. Different image paths
    # should yield different choices most of the time. Try a few combos
    # to ensure at least one pair differs.
    paths = [f"/tmp/img_{i:03d}.jpg" for i in range(10)]
    evidences = {json.loads(kernel.to_chat_example(p, "victim", scenario="collapsed_building", n_humans=3)["messages"][1]["content"][0]["text"])["visual_evidence"] for p in paths}
    assert len(evidences) >= 2, f"Expected ≥2 unique evidence strings across 10 paths, got {len(evidences)}: {evidences}"


def test_to_chat_example_rejects_unknown(kernel):
    with pytest.raises(ValueError, match="Unknown finding type"):
        kernel.to_chat_example("/tmp/test.jpg", "not-a-type")


# ---------------------------------------------------------------------------
# parse_model_output — strict, no silent coercion
# ---------------------------------------------------------------------------

def test_parse_model_output_valid(kernel):
    raw = json.dumps({"finding_type": "victim", "confidence": 0.9, "visual_evidence": "Figure visible."})
    p = kernel.parse_model_output(raw)
    assert p["parse_status"] == "ok"
    assert p["finding_type"] == "victim"
    assert p["confidence"] == 0.9


def test_parse_model_output_embedded_json(kernel):
    raw = 'Looking at this image: {"finding_type": "none", "confidence": 0.95, "visual_evidence": "Empty scene."}'
    p = kernel.parse_model_output(raw)
    assert p["parse_status"] == "ok"
    assert p["finding_type"] == "none"


def test_parse_model_output_codefence(kernel):
    raw = '```json\n{"finding_type": "victim", "confidence": 0.85, "visual_evidence": "A figure."}\n```'
    p = kernel.parse_model_output(raw)
    assert p["parse_status"] == "ok"
    assert p["finding_type"] == "victim"


def test_parse_model_output_empty(kernel):
    for raw in ("", "   ", None):
        p = kernel.parse_model_output(raw)
        assert p["parse_status"] == "empty"
        assert p["finding_type"] is None


def test_parse_model_output_off_schema(kernel):
    p = kernel.parse_model_output("This image shows a destroyed building.")
    assert p["parse_status"] == "off_schema"
    assert p["finding_type"] is None


def test_parse_model_output_bad_class(kernel):
    raw = json.dumps({"finding_type": "fire", "confidence": 0.9, "visual_evidence": "smoke"})
    p = kernel.parse_model_output(raw)
    assert p["parse_status"] == "bad_class"
    assert p["finding_type"] is None


def test_parse_model_output_does_not_coerce(kernel):
    """Critical regression guard: parser must NEVER silently default to 'victim' or 'none'."""
    p = kernel.parse_model_output("totally garbage output")
    assert p["finding_type"] is None  # NOT "none" or "victim"


# ---------------------------------------------------------------------------
# parse_label_file — YOLO format
# ---------------------------------------------------------------------------

def test_parse_label_file_valid(kernel, tmp_path):
    p = tmp_path / "labels.txt"
    # YOLO format: <cls> <cx> <cy> <w> <h>
    p.write_text("0 0.5 0.5 0.1 0.2\n2 0.3 0.4 0.05 0.08\n")
    rows = _has_attr(kernel, 'parse_label_file')(p)
    assert len(rows) == 2
    assert rows[0] == (0, 0.5, 0.5, 0.1, 0.2)
    assert rows[1] == (2, 0.3, 0.4, 0.05, 0.08)


def test_parse_label_file_empty(kernel, tmp_path):
    p = tmp_path / "empty.txt"
    p.write_text("")
    assert _has_attr(kernel, 'parse_label_file')(p) == []


def test_parse_label_file_malformed(kernel, tmp_path):
    p = tmp_path / "bad.txt"
    p.write_text("not enough fields\n0 0.5 0.5 0.1 0.2\n")
    rows = _has_attr(kernel, 'parse_label_file')(p)
    # First line skipped (<5 fields), second line parsed.
    assert len(rows) == 1


def test_parse_label_file_missing(kernel, tmp_path):
    p = tmp_path / "missing.txt"  # never written
    assert _has_attr(kernel, 'parse_label_file')(p) == []


# ---------------------------------------------------------------------------
# Image extension resolution
# ---------------------------------------------------------------------------

def test_find_image_for_label_jpg(kernel, tmp_path):
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    (img_dir / "test_001.jpg").touch()
    lbl = tmp_path / "labels" / "test_001.txt"
    lbl.parent.mkdir()
    lbl.touch()
    found = _has_attr(kernel, 'find_image_for_label')(lbl, img_dir)
    assert found is not None
    assert found.name == "test_001.jpg"


def test_find_image_for_label_png(kernel, tmp_path):
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    (img_dir / "test_002.png").touch()
    lbl = tmp_path / "labels" / "test_002.txt"
    lbl.parent.mkdir()
    lbl.touch()
    found = _has_attr(kernel, 'find_image_for_label')(lbl, img_dir)
    assert found is not None
    assert found.name == "test_002.png"


def test_find_image_for_label_missing(kernel, tmp_path):
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    lbl = tmp_path / "labels" / "nonexistent.txt"
    lbl.parent.mkdir()
    lbl.touch()
    assert _has_attr(kernel, 'find_image_for_label')(lbl, img_dir) is None
