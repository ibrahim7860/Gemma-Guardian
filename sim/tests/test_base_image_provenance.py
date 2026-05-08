"""Lockdown: every static aerial in sim/fixtures/base_images/ has matching
LICENSES.md attribution and meets the size/format constraints the Flutter
map_panel relies on.

Mirrors `sim/tests/test_fixture_provenance.py` for the per-tick frames
directory — the base_images dir got skipped in PR #36's first pass (only
the wire-format-to-bundle path translation bug was caught in /review;
this lockdown gap was the second informational finding). Catches: (a)
silent re-introduction of synthetic placeholders without attribution
updates, (b) accidentally-large fixtures that bloat git, (c) non-JPEG
content under a .jpg extension.

Why a separate file from test_fixture_provenance.py: the per-tick frames
have a tight ≤640×480 / ≤200KB envelope (FrameServer publishes them at
1 Hz, on-device perception runs against them). Static aerials get a
larger envelope (≤1024×1024 / ≤500KB) because the Flutter map_panel
zooms over a single image, not 30 of them per second."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from PIL import Image

BASE_IMAGES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "base_images"
LICENSES_PATH = BASE_IMAGES_DIR / "LICENSES.md"
MAX_W, MAX_H = 1024, 1024
MAX_SIZE_BYTES = 500_000  # 500KB ceiling — base aerial is one-shot, not per-tick

# Filenames every scenario YAML references via `base_image_path`. Update
# if a scenario adds a new aerial. Driving the parametrize off this set
# (not a glob) means a missing file is a hard failure, not a silently-
# empty parametrize that reports green.
EXPECTED_BASE_IMAGES = frozenset({
    "disaster_zone_v1_base.jpg",
})


@pytest.fixture(scope="module")
def license_text():
    return LICENSES_PATH.read_text()


def test_all_expected_base_images_present():
    on_disk = {p.name for p in BASE_IMAGES_DIR.glob("*.jpg")}
    missing = EXPECTED_BASE_IMAGES - on_disk
    extra = on_disk - EXPECTED_BASE_IMAGES
    assert not missing, f"missing expected base images: {sorted(missing)}"
    assert not extra, (
        f"unexpected base images present: {sorted(extra)} "
        f"(update EXPECTED_BASE_IMAGES if intentional)"
    )


@pytest.mark.parametrize("filename", sorted(EXPECTED_BASE_IMAGES))
def test_jpeg_magic_bytes(filename: str):
    path = BASE_IMAGES_DIR / filename
    assert path.read_bytes()[:2] == b"\xff\xd8", (
        f"{filename} missing JPEG magic bytes"
    )


@pytest.mark.parametrize("filename", sorted(EXPECTED_BASE_IMAGES))
def test_dimensions_under_cap(filename: str):
    path = BASE_IMAGES_DIR / filename
    with Image.open(path) as im:
        assert im.width <= MAX_W, f"{filename} width {im.width} > {MAX_W}"
        assert im.height <= MAX_H, f"{filename} height {im.height} > {MAX_H}"
        assert im.format == "JPEG"


@pytest.mark.parametrize("filename", sorted(EXPECTED_BASE_IMAGES))
def test_filesize_reasonable(filename: str):
    path = BASE_IMAGES_DIR / filename
    size = path.stat().st_size
    assert size <= MAX_SIZE_BYTES, (
        f"{filename} is {size} bytes (cap {MAX_SIZE_BYTES})"
    )


@pytest.mark.parametrize("filename", sorted(EXPECTED_BASE_IMAGES))
def test_has_license_entry(filename: str, license_text: str):
    assert f"## {filename}" in license_text, (
        f"{filename} has no entry in {LICENSES_PATH.relative_to(BASE_IMAGES_DIR.parent.parent)} — "
        "every base image must have full provenance attribution"
    )


def test_no_orphan_license_entries(license_text: str):
    """Reverse direction: every LICENSES.md entry maps to a real file
    in EXPECTED_BASE_IMAGES. Catches stale entries left after a deletion."""
    entries = re.findall(r"^## ([\w_]+\.jpg)$", license_text, re.MULTILINE)
    orphans = [e for e in entries if e not in EXPECTED_BASE_IMAGES]
    assert not orphans, f"LICENSES.md mentions files that don't exist: {orphans}"
