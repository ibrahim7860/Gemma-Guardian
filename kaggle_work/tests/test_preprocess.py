"""Local tests for the Kaggle kernel's preprocess + I/O contract.

Run with:
    uv run pytest kaggle_work/tests/

Covers:
  - find_xbd_root layout discovery (standard, nested, missing)
  - crop_buildings: WKT parse, tiny-skip, malformed JSON, unreadable image
  - to_chat_example: schema parity with ml/data_prep/format_for_gemma.py
  - parse_model_output: strict mode (no silent coercion), all error modes
  - class_balance: cap enforced, multi-class handled
  - split_by_disaster: held-out disasters land in correct splits
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from PIL import Image

# Make kaggle_work/ importable in tests.
KAGGLE_WORK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KAGGLE_WORK))
sys.path.insert(0, str(KAGGLE_WORK.parent))  # for ml.data_prep parity check

import prompts
import preprocess


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_tile(tmp_path: Path) -> tuple[Path, Path]:
    """Create a 256x256 fake post-disaster image + matching label JSON.

    Labels: one destroyed building (large), one no-damage building (tiny — should
    be skipped), one un-classified (should be skipped), one malformed WKT (skipped).
    """
    img_dir = tmp_path / "train" / "images"
    lbl_dir = tmp_path / "train" / "labels"
    img_dir.mkdir(parents=True)
    lbl_dir.mkdir(parents=True)

    img = Image.new("RGB", (256, 256), color=(120, 120, 120))
    stem = "hurricane-harvey_00000001_post_disaster"
    img_path = img_dir / f"{stem}.png"
    img.save(img_path)

    lbl_path = lbl_dir / f"{stem}.json"
    lbl_path.write_text(json.dumps({
        "metadata": {"disaster": "hurricane-harvey"},
        "features": {"xy": [
            {
                "properties": {"subtype": "destroyed", "uid": "b001"},
                "wkt": "POLYGON ((40 40, 200 40, 200 200, 40 200, 40 40))",
            },
            {
                "properties": {"subtype": "no-damage", "uid": "b002"},
                # 2x2 — below the 8px crop floor → skip.
                "wkt": "POLYGON ((10 10, 12 10, 12 12, 10 12, 10 10))",
            },
            {
                "properties": {"subtype": "un-classified", "uid": "b003"},
                "wkt": "POLYGON ((50 50, 150 50, 150 150, 50 150, 50 50))",
            },
            {
                "properties": {"subtype": "minor-damage", "uid": "b004"},
                "wkt": "NOT_VALID_WKT",
            },
        ]},
    }))
    return img_path, lbl_path


# ---------------------------------------------------------------------------
# find_xbd_root
# ---------------------------------------------------------------------------

def test_find_xbd_root_standard_layout(synthetic_tile, tmp_path: Path):
    # synthetic_tile creates tmp_path/train/images/... — find_xbd_root(tmp_path) returns tmp_path.
    root = preprocess.find_xbd_root(tmp_path)
    assert (root / "train" / "images").exists()


def test_find_xbd_root_nested_layout(tmp_path: Path):
    nested = tmp_path / "xbd_unzipped" / "train" / "images"
    nested.mkdir(parents=True)
    (tmp_path / "xbd_unzipped" / "train" / "labels").mkdir()
    root = preprocess.find_xbd_root(tmp_path)
    assert root == tmp_path / "xbd_unzipped"


def test_find_xbd_root_missing_raises(tmp_path: Path):
    (tmp_path / "random_unrelated").mkdir()
    with pytest.raises(RuntimeError, match="Could not find xBD layout"):
        preprocess.find_xbd_root(tmp_path)


# ---------------------------------------------------------------------------
# crop_buildings
# ---------------------------------------------------------------------------

def test_crop_buildings_happy_path(synthetic_tile, tmp_path: Path):
    img_path, lbl_path = synthetic_tile
    out_dir = tmp_path / "out"
    rows = preprocess.crop_buildings(img_path, lbl_path, out_dir)

    # Only the destroyed building survives (no-damage too small, un-classified
    # filtered, malformed WKT dropped).
    assert len(rows) == 1
    r = rows[0]
    assert r["label"] == "destroyed"
    assert r["disaster"] == "hurricane-harvey"
    assert r["building_uid"] == "b001"
    assert Path(r["path"]).exists()
    # Output should be class-organized.
    assert "destroyed" in r["path"]


def test_crop_buildings_resizes_to_target_size(synthetic_tile, tmp_path: Path):
    img_path, lbl_path = synthetic_tile
    rows = preprocess.crop_buildings(img_path, lbl_path, tmp_path / "out")
    crop = Image.open(rows[0]["path"])
    assert crop.size == (preprocess.TARGET_SIZE, preprocess.TARGET_SIZE)
    assert preprocess.TARGET_SIZE == 224  # C3 — must match ml/data_prep


def test_crop_buildings_unreadable_image_returns_empty(tmp_path: Path):
    img_path = tmp_path / "broken.png"
    img_path.write_bytes(b"not a real png")
    lbl_path = tmp_path / "lbl.json"
    lbl_path.write_text("{}")
    rows = preprocess.crop_buildings(img_path, lbl_path, tmp_path / "out")
    assert rows == []


def test_crop_buildings_malformed_json_returns_empty(synthetic_tile, tmp_path: Path):
    img_path, _ = synthetic_tile
    bad_lbl = tmp_path / "bad.json"
    bad_lbl.write_text("{ this is not json")
    rows = preprocess.crop_buildings(img_path, bad_lbl, tmp_path / "out")
    assert rows == []


# ---------------------------------------------------------------------------
# Chat format schema parity — A1 critical
# ---------------------------------------------------------------------------

def test_to_chat_example_matches_format_for_gemma():
    """Our notebook's chat format MUST byte-equal ml/data_prep/format_for_gemma."""
    from ml.data_prep.format_for_gemma import to_example as ml_to_example

    img = "/tmp/fake.jpg"
    for label in prompts.CLASS_LABELS:
        ours = prompts.to_chat_example(img, label)
        theirs = ml_to_example(img, label)
        assert ours == theirs, (
            f"Chat schema diverged from ml/data_prep for label={label}.\n"
            f"OURS:   {json.dumps(ours, indent=2)}\n"
            f"THEIRS: {json.dumps(theirs, indent=2)}"
        )


def test_to_chat_example_rejects_unknown_class():
    with pytest.raises(ValueError, match="Unknown damage class"):
        prompts.to_chat_example("/tmp/x.jpg", "not-a-class")


# ---------------------------------------------------------------------------
# parse_model_output — A5 critical, NO silent coercion
# ---------------------------------------------------------------------------

def test_parse_model_output_valid_envelope():
    raw = json.dumps({
        "damage_class": "destroyed",
        "confidence": 0.92,
        "visual_evidence": "Structure reduced to rubble.",
    })
    p = prompts.parse_model_output(raw)
    assert p["parse_status"] == "ok"
    assert p["damage_class"] == "destroyed"
    assert p["confidence"] == 0.92


def test_parse_model_output_embedded_json_in_prose():
    raw = 'Looking at this image, I see: {"damage_class": "major_damage", "confidence": 0.7, "visual_evidence": "partial collapse"}'
    p = prompts.parse_model_output(raw)
    assert p["parse_status"] == "ok"
    assert p["damage_class"] == "major-damage"


def test_parse_model_output_empty():
    for raw in ("", "   ", None):
        p = prompts.parse_model_output(raw)
        assert p["parse_status"] == "empty"
        assert p["damage_class"] is None


def test_parse_model_output_off_schema_prose():
    p = prompts.parse_model_output("This building looks destroyed.")
    assert p["parse_status"] == "off_schema"
    assert p["damage_class"] is None


def test_parse_model_output_bad_class():
    raw = json.dumps({"damage_class": "fictional_class", "confidence": 0.9, "visual_evidence": "x"})
    p = prompts.parse_model_output(raw)
    assert p["parse_status"] == "bad_class"
    assert p["damage_class"] is None


def test_parse_model_output_does_not_coerce_to_no_damage():
    """A5 regression: predict() previously silently coerced off-schema to no-damage."""
    p = prompts.parse_model_output("totally garbage output")
    assert p["damage_class"] is None  # NOT "no-damage"


# ---------------------------------------------------------------------------
# class_balance — P2
# ---------------------------------------------------------------------------

def test_class_balance_caps_per_class():
    rows = (
        [{"path": f"/p/{i}.jpg", "label": "no-damage", "disaster": "h"} for i in range(1000)] +
        [{"path": f"/p/d{i}.jpg", "label": "destroyed", "disaster": "h"} for i in range(20)]
    )
    capped = preprocess.class_balance(rows, max_per_class=50)
    from collections import Counter
    dist = Counter(r["label"] for r in capped)
    assert dist["no-damage"] == 50
    assert dist["destroyed"] == 20  # below cap, no truncation


def test_class_balance_deterministic_with_seed():
    rows = [{"path": f"/p/{i}.jpg", "label": "no-damage", "disaster": "h"} for i in range(100)]
    a = preprocess.class_balance(rows, max_per_class=10, seed=42)
    b = preprocess.class_balance(rows, max_per_class=10, seed=42)
    assert a == b


# ---------------------------------------------------------------------------
# split_by_disaster — honest generalization split
# ---------------------------------------------------------------------------

def test_split_by_disaster_routes_to_correct_split():
    rows = [
        {"label": "destroyed", "disaster": "hurricane-harvey", "path": "/a"},  # → train
        {"label": "no-damage", "disaster": "mexico-earthquake", "path": "/b"},  # → val
        {"label": "minor-damage", "disaster": "joplin-tornado", "path": "/c"},  # → test
        {"label": "major-damage", "disaster": "unknown-disaster", "path": "/d"},  # → train (default)
    ]
    s = preprocess.split_by_disaster(rows)
    assert len(s["train"]) == 2
    assert s["val"][0]["disaster"] == "mexico-earthquake"
    assert s["test"][0]["disaster"] == "joplin-tornado"


# ---------------------------------------------------------------------------
# JSONL output shape
# ---------------------------------------------------------------------------

def test_write_chat_jsonl_writes_valid_rows(tmp_path: Path):
    rows = [
        {"path": "/img1.jpg", "label": "destroyed", "disaster": "h"},
        {"path": "/img2.jpg", "label": "no-damage", "disaster": "h"},
    ]
    out = tmp_path / "out.jsonl"
    n = preprocess.write_chat_jsonl(rows, out)
    assert n == 2
    lines = out.read_text().strip().split("\n")
    assert len(lines) == 2
    for line in lines:
        obj = json.loads(line)
        assert "messages" in obj
        assert obj["messages"][0]["role"] == "user"
        assert obj["messages"][1]["role"] == "assistant"
        # Assistant content must be a JSON envelope per A1.
        envelope = json.loads(obj["messages"][1]["content"])
        assert "damage_class" in envelope
        assert "confidence" in envelope
        assert "visual_evidence" in envelope
