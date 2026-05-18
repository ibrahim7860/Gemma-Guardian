"""Lockdown test: every placeholder JPEG in sim/fixtures/frames/ has matching
LICENSES.md attribution and meets the size/format constraints that downstream
consumers (FrameServer, drone agent perception node) rely on.

This catches: (a) silent re-introduction of synthetic placeholders without
attribution updates, (b) accidentally-large fixtures that bloat git, (c)
non-JPEG content under a .jpg extension.

LOCKED FIX from plan-eng-review §3 #1: parametrize is driven off an explicit
EXPECTED_FIXTURES set, not a glob over the directory. A glob over an empty
directory would produce zero parametrized cases and the suite would report
green — locking down nothing. The explicit set means a missing fixture file
is a hard failure caught by test_all_expected_fixtures_present."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from PIL import Image

FRAMES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "frames"
LICENSES_PATH = FRAMES_DIR / "LICENSES.md"
MAX_W, MAX_H = 1280, 720
MAX_SIZE_BYTES = 350_000  # 350KB ceiling — accommodates C2A 1024x576 disaster aerials

# The 8 fixture filenames that disaster_zone_v1.yaml, single_drone_smoke.yaml,
# and resilience_v1.yaml all reference. Update if scenarios add new fixtures.
EXPECTED_FIXTURES = frozenset({
    "placeholder_block_a_01.jpg",
    "placeholder_block_a_02.jpg",
    "placeholder_block_b_01.jpg",
    "placeholder_debris_01.jpg",
    "placeholder_fire_01.jpg",
    "placeholder_intact_01.jpg",
    "placeholder_smoke_01.jpg",
    "placeholder_victim_01.jpg",
})


@pytest.fixture(scope="module")
def license_text():
    return LICENSES_PATH.read_text()


def test_all_expected_fixtures_present():
    """Sanity floor: every expected fixture exists on disk. Without this,
    the parametrized tests below would produce zero cases on an empty
    fixtures dir and the suite would report green — silently locking
    down nothing."""
    on_disk = {p.name for p in FRAMES_DIR.glob("placeholder_*.jpg")}
    missing = EXPECTED_FIXTURES - on_disk
    extra = on_disk - EXPECTED_FIXTURES
    assert not missing, f"missing expected fixtures: {sorted(missing)}"
    assert not extra, (
        f"unexpected fixtures present: {sorted(extra)} "
        f"(update EXPECTED_FIXTURES if intentional)"
    )


@pytest.mark.parametrize("filename", sorted(EXPECTED_FIXTURES))
def test_jpeg_magic_bytes(filename: str):
    path = FRAMES_DIR / filename
    assert path.read_bytes()[:2] == b"\xff\xd8", (
        f"{filename} missing JPEG magic bytes"
    )


@pytest.mark.parametrize("filename", sorted(EXPECTED_FIXTURES))
def test_dimensions_under_cap(filename: str):
    path = FRAMES_DIR / filename
    with Image.open(path) as im:
        assert im.width <= MAX_W, f"{filename} width {im.width} > {MAX_W}"
        assert im.height <= MAX_H, f"{filename} height {im.height} > {MAX_H}"
        assert im.format == "JPEG"


@pytest.mark.parametrize("filename", sorted(EXPECTED_FIXTURES))
def test_filesize_reasonable(filename: str):
    path = FRAMES_DIR / filename
    size = path.stat().st_size
    assert size <= MAX_SIZE_BYTES, (
        f"{filename} is {size} bytes (cap {MAX_SIZE_BYTES})"
    )


@pytest.mark.parametrize("filename", sorted(EXPECTED_FIXTURES))
def test_has_license_entry(filename: str, license_text: str):
    assert f"## {filename}" in license_text, (
        f"{filename} has no entry in LICENSES.md — "
        "every fixture file must have full provenance attribution"
    )


def test_no_orphan_license_entries(license_text: str):
    """Reverse direction: every LICENSES.md entry maps to a real file
    in EXPECTED_FIXTURES. Catches stale entries left after a deletion."""
    entries = re.findall(r"^## (placeholder_[\w_]+\.jpg)$", license_text, re.MULTILINE)
    orphans = [e for e in entries if e not in EXPECTED_FIXTURES]
    assert not orphans, f"LICENSES.md mentions files that don't exist: {orphans}"
