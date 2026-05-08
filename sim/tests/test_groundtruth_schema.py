"""Lockdown test: groundtruth manifests have the expanded eval fields
(expected_finding_type, expected_severity, min_confidence) on every detection
entry, with values inside the locked enums. Without this, Kaleel's perception
eval has no automated scoring target.

Per LOCKED DECISION Q3 (2026-05-08 plan-eng-review): both disaster_zone_v1
AND resilience_v1 are enforced — no rule-with-one-exception."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

GT_DIR = Path(__file__).resolve().parent.parent / "scenarios"
FRAMES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "frames"

# Matches Contract 4 finding `type` enum + Contract 4 `severity` integer
# range (locked in shared/schemas/_common.json: severity is integer 1-5).
# Adversarial-review fix: original plan used string severities which don't
# compare against the integer Contract 4 field — silent eval failure.
FINDING_TYPES = {"victim", "fire", "smoke", "damaged_structure", "blocked_route"}
SEVERITY_MIN, SEVERITY_MAX = 1, 5
DETECTION_KEYS = ("victims", "fires", "damaged_structures", "blocked_routes")
GROUNDTRUTH_FILES = (
    "disaster_zone_v1_groundtruth.json",
    "resilience_v1_groundtruth.json",
)


@pytest.fixture(scope="module", params=GROUNDTRUTH_FILES, ids=lambda n: n.split("_")[0] + "_v1")
def groundtruth(request):
    name = request.param
    return name, json.loads((GT_DIR / name).read_text())


@pytest.mark.parametrize("key", DETECTION_KEYS)
def test_each_entry_has_eval_fields(groundtruth, key: str):
    name, gt = groundtruth
    for entry in gt.get(key, []):
        ctx = f"{name}/{key}/{entry.get('id')}"
        assert "expected_finding_type" in entry, f"{ctx} missing expected_finding_type"
        assert entry["expected_finding_type"] in FINDING_TYPES, (
            f"{ctx} bad type: {entry['expected_finding_type']!r} not in {FINDING_TYPES}"
        )
        assert "expected_severity" in entry, f"{ctx} missing expected_severity"
        sev = entry["expected_severity"]
        assert isinstance(sev, int) and not isinstance(sev, bool), (
            f"{ctx} expected_severity must be int (Contract 4 alignment), got {type(sev).__name__}"
        )
        assert SEVERITY_MIN <= sev <= SEVERITY_MAX, (
            f"{ctx} expected_severity {sev} outside Contract 4 range [{SEVERITY_MIN}, {SEVERITY_MAX}]"
        )
        assert "min_confidence" in entry, f"{ctx} missing min_confidence"
        assert isinstance(entry["min_confidence"], (int, float)), (
            f"{ctx} min_confidence must be numeric"
        )
        assert 0.0 <= entry["min_confidence"] <= 1.0, (
            f"{ctx} min_confidence {entry['min_confidence']} out of [0, 1]"
        )


def test_frame_files_exist(groundtruth):
    name, gt = groundtruth
    for key in DETECTION_KEYS:
        for entry in gt.get(key, []):
            ff = entry.get("frame_file")
            if ff:
                assert (FRAMES_DIR / ff).exists(), (
                    f"{name}/{key}/{entry['id']} references missing frame {ff}"
                )


def test_finding_type_matches_detection_key(groundtruth):
    """Sanity: an entry under `victims[]` should declare expected_finding_type
    "victim", not "fire". Catches copy-paste errors in the manifest."""
    name, gt = groundtruth
    key_to_type = {
        "victims": "victim",
        "fires": ("fire", "smoke"),  # smoke entries live under fires[]
        "damaged_structures": "damaged_structure",
        "blocked_routes": "blocked_route",
    }
    for key, expected in key_to_type.items():
        for entry in gt.get(key, []):
            actual = entry.get("expected_finding_type")
            if isinstance(expected, tuple):
                assert actual in expected, (
                    f"{name}/{key}/{entry.get('id')}: expected_finding_type {actual!r} "
                    f"not in {expected}"
                )
            else:
                assert actual == expected, (
                    f"{name}/{key}/{entry.get('id')}: expected_finding_type {actual!r} "
                    f"should be {expected!r}"
                )
