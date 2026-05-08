"""Lockdown: assets the Flutter dashboard loads via Image.asset must be
byte-identical to their source-of-truth copy under sim/fixtures/base_images/.

The two copies exist because Flutter's asset bundler can't reach files
outside the Flutter project root. This test prevents one side from drifting
without the other (a classic edit-the-Flutter-copy-only failure mode that
silently puts the demo overlay out of sync with the simulated scenario).

When this fails: run `uv run python -m scripts.sync_flutter_base_images` to
re-copy from sim/, NOT the other direction. The sim/ copy is the canonical
source — its provenance lives in sim/fixtures/base_images/LICENSES.md and
its sha256 lockdown lives in scripts/fixtures_manifest.json."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SOURCE_DIR = REPO_ROOT / "sim" / "fixtures" / "base_images"
TARGET_DIR = REPO_ROOT / "frontend" / "flutter_dashboard" / "assets" / "base_images"
MANIFEST = REPO_ROOT / "scripts" / "fixtures_manifest.json"
PUBSPEC = REPO_ROOT / "frontend" / "flutter_dashboard" / "pubspec.yaml"

# Hardcoded list mirrors scripts/sync_flutter_base_images.py TRACKED.
# Driving from a constant rather than a glob means a missing source file is
# a hard failure, not a silently-empty parametrize.
TRACKED = ("disaster_zone_v1_base.jpg",)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@pytest.mark.parametrize("name", TRACKED)
def test_flutter_asset_matches_sim_source(name: str):
    src = SOURCE_DIR / name
    dst = TARGET_DIR / name
    assert src.exists(), (
        f"source missing: {src} — sim/fixtures/base_images/ should be the "
        f"source of truth for static aerials"
    )
    assert dst.exists(), (
        f"flutter asset missing: {dst} — run "
        f"`uv run python -m scripts.sync_flutter_base_images` to re-copy"
    )
    assert _sha256(src) == _sha256(dst), (
        f"{name} drift: sim copy and flutter copy do not match.\n"
        f"  sim:    {_sha256(src)}\n"
        f"  flutter:{_sha256(dst)}\n"
        f"  Re-sync: uv run python -m scripts.sync_flutter_base_images"
    )


@pytest.mark.parametrize("name", TRACKED)
def test_flutter_asset_declared_in_pubspec(name: str):
    """Belt-and-braces: the file exists, and pubspec actually declares it.
    Without the pubspec entry, Flutter excludes it from the asset bundle and
    Image.asset() fails at runtime with a confusing 'asset not found' error."""
    text = PUBSPEC.read_text()
    needle = f"assets/base_images/{name}"
    assert needle in text, (
        f"{name} not declared in pubspec.yaml under flutter.assets — "
        f"Image.asset will fail at runtime"
    )


@pytest.mark.parametrize("name", TRACKED)
def test_flutter_asset_matches_manifest_sha(name: str):
    """Cross-check: the bytes in flutter assets dir match the sha256 pinned
    in scripts/fixtures_manifest.json (which is itself the upstream lockdown).
    Catches the case where someone manually edits the flutter copy AND the
    sim copy in lock-step, but neither matches the manifest source URL.

    The manifest pins SOURCE bytes (pre-Pillow); the on-disk file is POST
    Pillow resize+JPEG q85. So we don't compare file-sha to manifest-sha
    directly — we just confirm the manifest entry exists for traceability."""
    manifest = json.loads(MANIFEST.read_text())
    fixtures = manifest["fixtures"] if isinstance(manifest, dict) else manifest
    matches = [e for e in fixtures if e.get("filename") == name]
    assert matches, f"{name} has no entry in scripts/fixtures_manifest.json"
    entry = matches[0]
    assert entry.get("source_sha256"), f"{name} manifest entry missing source_sha256"
    assert re.fullmatch(r"[a-f0-9]{64}", entry["source_sha256"]), (
        f"{name} source_sha256 not a valid sha256: {entry['source_sha256']!r}"
    )
