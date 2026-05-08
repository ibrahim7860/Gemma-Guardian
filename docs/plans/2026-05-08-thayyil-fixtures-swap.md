# Thayyil Fixtures Swap — Programmatic Implementation Plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the 7 remaining synthetic placeholder fixture JPEGs with real public-domain post-disaster aerial imagery, expand the disaster_zone_v1 ground-truth manifest with eval-relevant fields, and prove both with tests — all without manual image hunting.

**Architecture:** A reproducible-fetch script (`scripts/fetch_disaster_fixtures.py`) consumes a checked-in JSON manifest of (placeholder_filename → source URL + crop spec + attribution), downloads via `urllib`, validates JPEG magic bytes, resizes via Pillow to ≤640×480 q85, writes to `sim/fixtures/frames/`, and appends LICENSES.md entries idempotently. The script is the audit trail: anyone can re-run it and get byte-identical fixtures. Ground-truth manifest expansion happens in the same PR — adds `expected_finding_type`, `expected_severity`, `min_confidence` per entry so Kaleel's perception evals have automated scoring targets.

**Tech Stack:** Python 3.11, `Pillow` (already in `[project.optional-dependencies].sim`), `urllib.request` (stdlib), pytest, JSON Schema (already wired via `shared.contracts.validate`).

---

## LOCKED DECISIONS (from `/plan-eng-review` 2026-05-08)

These four decisions came out of the review pass and are non-negotiable for the implementation:

1. **Q1 — Drift detection (Architecture):** Manifest gains a `source_sha256` field per entry. The script computes the sha256 of the upstream bytes BEFORE Pillow touches them and fails loudly if mismatched. This converts "wishful determinism" into an actual lockdown — future re-fetches that get re-encoded Wikimedia thumbnails fail visibly instead of silently corrupting fixtures. Affects Task 1, Task 2.
2. **Q2 — Validation pattern (Code Quality):** Manifest validation uses the project's JSON Schema infrastructure (`shared.contracts.validate(schema_name, payload)`) against a new `shared/schemas/fixtures_manifest.json`. NOT bespoke `REQUIRED_FIELDS` checks. Same pattern as Contract 4, Contract 11. Affects Task 1 (new schema file), Task 2 (call `validate` instead of field loop).
3. **Q3 — Resilience scope (Tests):** Eval fields (`expected_finding_type` / `expected_severity` / `min_confidence`) added to BOTH `disaster_zone_v1_groundtruth.json` AND `resilience_v1_groundtruth.json`. Schema test enforces both. Affects Task 5.
4. **Q4 — Static aerial bundle (Scope):** A new Task 8 ships the static aerial base image AND wires it into `disaster_zone_v1.yaml` + `frontend/flutter_dashboard/lib/widgets/map_panel.dart`, closing the `TODOS.md` "Static aerial base image for map panel" item in the same PR. Surface expands to Flutter; needs Hazim review on YAML schema change.

## LOCKED DESIGN DECISIONS (from `/plan-design-review` 2026-05-08, Task 8 only)

These three decisions came out of the design review pass on Task 8's Flutter map-panel work:

5. **D1 — Bbox semantics:** When `base_image_path` is present, the map panel locks bbox to `scenario.base_image_extents`. The existing data-driven `_computeBbox()` path is bypassed; the "Refit" button hides. Drones outside the image extents render with a chevron at the canvas edge in the drone's palette color, rotated to point toward the off-canvas position. Tap on chevron surfaces a toast: `"drone1 is 247m east"`. Without this lock, drones drift relative to actual landmarks in the photo.
6. **D2 — Image-load state:** Procedural grid renders synchronously on first paint. Aerial image layers on top via `AnimatedOpacity` 0→1 over 150ms when `Image.asset` reports loaded. Grid stays as the universal fallback for `base_image_path` absent, asset 404, or decode error (with a 4-second auto-dismissed toast: "Aerial overlay unavailable"). User never sees a blank-white flash.
7. **D3 — Marker contrast on photographic background:** Aerial image renders at `opacity: 0.80`. Drone-ID labels move from raw 10px black text into a white pill (`Container` with `padding: EdgeInsets.symmetric(horizontal: 6, vertical: 4)`, `borderRadius: 8`, `boxShadow: subtle drop shadow`) for legibility against rooftops/foliage. Finding circles get a 2px white outline matching the drone-halo treatment. Bundle a touch-target a11y fix in the same diff: `_droneHitRadius` 18→24, `_findingHitRadius` 14→24 (existing 36px / 28px targets are below the 44px iOS minimum — pre-existing gap, fixed while we're in the file).

**Simple fixes applied during execution without further questions** (from review Sections 1–3):
- `User-Agent` string uses a real maintainer email (not `ibrahim@...` placeholder); UA expectation is set by Wikimedia policy.
- `process_one()` validates crop-box bounds against source image dimensions before `img.crop()` to surface typos instead of silently clipping.
- `append_license_entry()` refuses to append when the header exists with stale metadata; requires explicit `--rewrite-license` flag for in-place updates.
- `test_fixture_provenance.py` drives parametrize off an explicit `EXPECTED_FIXTURES` set (8 names), not a glob — prevents silent-green when fixtures are accidentally deleted.
- New regression test `sim/tests/test_scenario_loads_with_real_fixtures.py` confirms `disaster_zone_v1.yaml` loads through `FrameServer` post-swap (covers the "manual sanity-run" gap with an automated test).
- `docs/sim-reproduction.md` block in Task 6 uses `~~~` for the outer code fence to avoid triple-backtick collision rendering bug.

**Why programmatic:** Reproducibility (license audit trail), zero-touch swaps if a source URL rots, no human-in-the-loop for an irreducibly mechanical task. Frees Thayyil for the human-judgment work (resilience polish, cold-run reproduction test, submission on-call).

**Why not xBD-proper:** xBD requires xView2.org account registration — credentials-gated and not programmatic. Public-domain disaster aerials (FEMA Photo Library, Wikimedia Commons, NASA Earth Observatory, USGS) are functionally equivalent for sim-vision iteration and demo footage. The fine-tune training pipeline (`ml/data_prep/download_xbd.py`) still requires real xBD via Kaleel's xView2 creds — that's a separate concern, not in scope here.

---

## Pre-flight: scope and constraints

**Hard constraints (do not violate):**
- **Filenames preserved.** `disaster_zone_v1.yaml`, `single_drone_smoke.yaml`, and `disaster_zone_v1_groundtruth.json` reference these placeholders by name. Zero edits to scenario YAMLs.
- **Dimensions ≤ 640×480, JPEG quality 85.** Per `placeholder_victim_01.jpg` precedent (commit `30577e7`).
- **Public-domain or CC0 only.** Each new file gets a full LICENSES.md entry: source URL, title, author, license, retrieval date, modifications, justification.
- **JPEG magic bytes intact.** `b"\xff\xd8"` prefix — `sim/tests/test_frame_server.py` already enforces this; new tests must keep it green.
- **No commits with broken tests.** Phase order matters: fetch → verify → license → manifest → tests → STATUS.

**Files already done (do not touch):**
- `placeholder_victim_01.jpg` — FEMA Katrina, public domain, attributed in `LICENSES.md` (commit `30577e7`).

**7 files to swap:**
| Filename | Semantic role | Used by | Source category |
|---|---|---|---|
| `placeholder_block_a_01.jpg` | Pre-disaster building (drone1 ticks 0–30) | disaster_zone_v1, smoke | Aerial of intact urban block |
| `placeholder_block_a_02.jpg` | **Damaged structure** (major_damage, ds_a2) | disaster_zone_v1 | Post-tornado/hurricane building damage aerial |
| `placeholder_block_b_01.jpg` | Pre-disaster building (drone2 ticks 0–60) | disaster_zone_v1 | Aerial of intact urban block |
| `placeholder_intact_01.jpg` | **Control: intact building** (negative example) | disaster_zone_v1, smoke | Pre-disaster aerial of intact suburb |
| `placeholder_fire_01.jpg` | **Active fire** (medium intensity, f01) | disaster_zone_v1 | Wildfire aerial with visible flames |
| `placeholder_smoke_01.jpg` | **Smoke plume** (low intensity, f02) | disaster_zone_v1 | Wildfire smoke aerial |
| `placeholder_debris_01.jpg` | **Blocked route** (br01) | disaster_zone_v1 | Post-disaster debris field aerial |

---

## File Structure

**Create:**
- `scripts/fetch_disaster_fixtures.py` — fetch + resize + write
- `scripts/fixtures_manifest.json` — checked-in source manifest (audit trail)
- `sim/tests/test_fixture_provenance.py` — dimension + license-presence + JPEG-validity checks for all real fixtures
- `sim/tests/test_groundtruth_schema.py` — schema test for expanded groundtruth (if no existing test covers it)

**Modify:**
- `sim/fixtures/frames/placeholder_block_a_01.jpg` (file content swap, name preserved)
- `sim/fixtures/frames/placeholder_block_a_02.jpg` (swap)
- `sim/fixtures/frames/placeholder_block_b_01.jpg` (swap)
- `sim/fixtures/frames/placeholder_intact_01.jpg` (swap)
- `sim/fixtures/frames/placeholder_fire_01.jpg` (swap)
- `sim/fixtures/frames/placeholder_smoke_01.jpg` (swap)
- `sim/fixtures/frames/placeholder_debris_01.jpg` (swap)
- `sim/fixtures/frames/LICENSES.md` (append 7 attribution entries, 1 per file)
- `sim/scenarios/disaster_zone_v1_groundtruth.json` (add `expected_finding_type`, `expected_severity`, `min_confidence` per entry)
- `docs/STATUS.md` (Thayyil row: mark items 1+2 done, credit script)
- `docs/sim-reproduction.md` (one-line note: "fixtures are reproducible via `python -m scripts.fetch_disaster_fixtures`")

**Test:**
- `sim/tests/test_fixture_provenance.py`
- `sim/tests/test_groundtruth_schema.py`
- `scripts/tests/test_fetch_disaster_fixtures.py` (unit-level: manifest parse, resize math, license-append idempotency)

---

## Task 1: Source manifest

**Files:**
- Create: `scripts/fixtures_manifest.json`

- [ ] **Step 1: Curate 7 source URLs.** For each placeholder filename, identify a public-domain post-disaster aerial that matches the semantic role. Sources in priority order:
  1. **FEMA Photo Library** (Wikimedia mirror): `commons.wikimedia.org/wiki/Category:Photographs_by_FEMA` — public domain US federal works.
  2. **NASA Earth Observatory:** `earthobservatory.nasa.gov` — public domain.
  3. **USGS / NOAA aerials:** public domain.
  4. **Wikimedia Commons CC0:** filtered by category (Hurricane damage, Wildfire aerials, Tornado damage, Earthquake damage).

  **Selection rule:** for damage/fire/smoke roles, pick obvious unambiguous imagery (a non-expert can tell what's happening) so Gemma 4 vision has a fighting chance pre-fine-tune. For `intact_01` and the `block_*` controls, pick clean aerials with no visible damage.

- [ ] **Step 2: Create JSON Schema** at `shared/schemas/fixtures_manifest.json` (per LOCKED DECISION Q2). Schema enforces every required field including the new `source_sha256` and validates types/enums:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "FixturesManifest",
  "type": "object",
  "required": ["schema_version", "fixtures"],
  "properties": {
    "schema_version": {"type": "string"},
    "fixtures": {
      "type": "array",
      "items": {
        "type": "object",
        "required": [
          "filename", "source_url", "source_sha256", "title", "author",
          "license", "license_url", "retrieved", "target_size",
          "jpeg_quality", "semantic_role", "scenario_use"
        ],
        "properties": {
          "filename": {"type": "string", "pattern": "^[a-z0-9_]+\\.(jpg|jpeg|png)$"},
          "source_url": {"type": "string", "format": "uri"},
          "source_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
          "title": {"type": "string", "minLength": 1},
          "author": {"type": "string", "minLength": 1},
          "license": {"type": "string", "minLength": 1},
          "license_url": {"type": "string", "format": "uri"},
          "retrieved": {"type": "string", "format": "date"},
          "crop_box": {
            "oneOf": [
              {"type": "null"},
              {"type": "array", "items": {"type": "integer", "minimum": 0}, "minItems": 4, "maxItems": 4}
            ]
          },
          "target_size": {"type": "array", "items": {"type": "integer", "minimum": 1}, "minItems": 2, "maxItems": 2},
          "jpeg_quality": {"type": "integer", "minimum": 1, "maximum": 100},
          "semantic_role": {"type": "string", "minLength": 1},
          "scenario_use": {"type": "string", "minLength": 1}
        },
        "additionalProperties": false
      }
    }
  },
  "additionalProperties": false
}
```

  Wire it into `shared/contracts/contracts.yaml` (or whatever loader registry the project uses) so `validate("fixtures_manifest", payload)` resolves.

- [ ] **Step 3: Write `scripts/fixtures_manifest.json`** with this exact shape (per LOCKED DECISION Q1: every entry includes `source_sha256`, computed via `sha256sum` on the downloaded source bytes the first time you fetch each one):

```json
{
  "schema_version": "1.0.0",
  "fixtures": [
    {
      "filename": "placeholder_block_a_01.jpg",
      "source_url": "https://upload.wikimedia.org/wikipedia/commons/...",
      "source_sha256": "<64-hex-char sha256 of upstream bytes>",
      "title": "...",
      "author": "...",
      "license": "Public Domain (US federal work)",
      "license_url": "https://en.wikipedia.org/wiki/Public_domain",
      "retrieved": "2026-05-08",
      "crop_box": null,
      "target_size": [640, 480],
      "jpeg_quality": 85,
      "semantic_role": "intact urban block aerial (pre-disaster control)",
      "scenario_use": "disaster_zone_v1 drone1 ticks 0–30; single_drone_smoke"
    }
    /* ...6 more entries... */
  ]
}
```

  **How to populate `source_sha256`:** run the script once with `--bootstrap-sha256` (a flag we add in Task 2) which fetches each URL and prints `filename: sha256` lines for you to paste into the manifest. After that bootstrap the manifest is locked and the script enforces sha256 match on every subsequent run.

  Notes:
  - `crop_box`: `[left, top, right, bottom]` in source-image pixels, or `null` for "use full image".
  - `target_size`: max dimensions; aspect ratio preserved via `Image.thumbnail`.
  - Every field is required. The fetch script validates the manifest before any network call.

- [ ] **Step 3: Commit the manifest alone.** This commit is reviewable in isolation by Hazim/Thayyil before any image bytes change.

```bash
git add scripts/fixtures_manifest.json
git commit -m "fixtures: add source manifest for 7 placeholder swaps (no fetch yet)"
```

---

## Task 2: Fetch script

**Files:**
- Create: `scripts/fetch_disaster_fixtures.py`

- [ ] **Step 1: Write the failing test first** at `scripts/tests/test_fetch_disaster_fixtures.py`:

```python
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from PIL import Image
from io import BytesIO

from scripts.fetch_disaster_fixtures import (
    FixtureSpec, load_manifest, process_one, append_license_entry,
)

def _make_jpeg_bytes(w=1024, h=768, color=(80, 80, 80)):
    img = Image.new("RGB", (w, h), color)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()

def test_load_manifest_validates_required_fields(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": "1.0.0", "fixtures": [{"filename": "x.jpg"}]}))
    with pytest.raises(ValueError, match="missing required field"):
        load_manifest(bad)

def test_process_one_resizes_and_writes_jpeg(tmp_path):
    spec = FixtureSpec(
        filename="placeholder_test.jpg",
        source_url="https://example.test/x.jpg",
        title="t", author="a", license="Public Domain",
        license_url="https://x", retrieved="2026-05-08",
        crop_box=None, target_size=(640, 480), jpeg_quality=85,
        semantic_role="r", scenario_use="u",
    )
    with patch("scripts.fetch_disaster_fixtures.urlopen") as mock_open:
        mock_open.return_value.__enter__.return_value.read.return_value = _make_jpeg_bytes()
        out = tmp_path / spec.filename
        process_one(spec, out_dir=tmp_path)
        assert out.exists()
        with Image.open(out) as im:
            assert im.width <= 640 and im.height <= 480
            assert im.format == "JPEG"
        assert out.read_bytes()[:2] == b"\xff\xd8"

def test_process_one_applies_crop_box(tmp_path):
    spec = FixtureSpec(
        filename="placeholder_crop.jpg",
        source_url="https://example.test/x.jpg",
        title="t", author="a", license="PD", license_url="x",
        retrieved="2026-05-08", crop_box=(0, 0, 512, 512),
        target_size=(640, 480), jpeg_quality=85,
        semantic_role="r", scenario_use="u",
    )
    with patch("scripts.fetch_disaster_fixtures.urlopen") as mock_open:
        mock_open.return_value.__enter__.return_value.read.return_value = _make_jpeg_bytes(1024, 1024)
        process_one(spec, out_dir=tmp_path)
        with Image.open(tmp_path / "placeholder_crop.jpg") as im:
            # 512x512 crop, then thumbnail to fit 640x480 → stays 480x480
            assert im.width == im.height

def test_append_license_idempotent(tmp_path):
    licenses = tmp_path / "LICENSES.md"
    licenses.write_text("# Fixture image provenance\n\n")
    spec = FixtureSpec(
        filename="placeholder_x.jpg", source_url="https://x", title="T",
        author="A", license="PD", license_url="https://lic",
        retrieved="2026-05-08", crop_box=None, target_size=(640, 480),
        jpeg_quality=85, semantic_role="r", scenario_use="u",
    )
    append_license_entry(licenses, spec)
    append_license_entry(licenses, spec)  # second call is a no-op
    text = licenses.read_text()
    assert text.count("## placeholder_x.jpg") == 1
```

- [ ] **Step 2: Run tests, confirm they fail with import errors.**

```bash
uv run pytest scripts/tests/test_fetch_disaster_fixtures.py -v
```
Expected: ImportError on `scripts.fetch_disaster_fixtures`.

- [ ] **Step 3: Implement `scripts/fetch_disaster_fixtures.py`.** Required structure (incorporates LOCKED DECISIONS Q1 sha256 verification + Q2 JSON Schema validation, plus the four simple fixes from review):

```python
"""Fetch and resize public-domain disaster aerials into sim/fixtures/frames/.

Reproducibility model (per LOCKED DECISION Q1): the manifest pins a
source_sha256 per entry. The script verifies the downloaded source bytes
against that sha256 BEFORE Pillow touches them. If Wikimedia/FEMA re-encodes
a thumbnail in the future, the fetch fails loudly with a clear "source has
changed; review manually before refreshing the manifest" error. This
converts wishful determinism into a hard lockdown.

Pillow JPEG q85 is deterministic for a given input, so the resized output
is byte-stable as long as the source sha256 matches.

Usage:
    python -m scripts.fetch_disaster_fixtures                  # normal fetch
    python -m scripts.fetch_disaster_fixtures --dry-run        # log URLs only
    python -m scripts.fetch_disaster_fixtures --only NAME      # one entry
    python -m scripts.fetch_disaster_fixtures --bootstrap-sha256
        # for first-time manifest population: fetch each URL, print
        # filename: sha256 lines, write nothing.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple
from urllib.request import urlopen, Request
from io import BytesIO
from PIL import Image
from shared.contracts import validate  # JSON Schema validator (LOCKED DECISION Q2)

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "scripts" / "fixtures_manifest.json"
FRAMES_DIR = REPO_ROOT / "sim" / "fixtures" / "frames"
LICENSES_PATH = FRAMES_DIR / "LICENSES.md"
# Real maintainer email per Wikimedia UA policy. Replace at execution time
# with darkmatter8789@gmail.com or whichever address you want to receive
# reachability complaints on.
USER_AGENT = "GemmaGuardian-Hackathon/1.0 (https://github.com/<owner>/<repo>; contact: darkmatter8789@gmail.com)"

@dataclass(frozen=True)
class FixtureSpec:
    filename: str
    source_url: str
    source_sha256: str
    title: str
    author: str
    license: str
    license_url: str
    retrieved: str
    crop_box: Optional[Tuple[int, int, int, int]]
    target_size: Tuple[int, int]
    jpeg_quality: int
    semantic_role: str
    scenario_use: str

def load_manifest(path: Path) -> list[FixtureSpec]:
    data = json.loads(path.read_text())
    # LOCKED DECISION Q2: validate via shared JSON Schema infra, not bespoke checks.
    validate("fixtures_manifest", data)
    out = []
    for entry in data["fixtures"]:
        out.append(FixtureSpec(
            filename=entry["filename"],
            source_url=entry["source_url"],
            source_sha256=entry["source_sha256"],
            title=entry["title"],
            author=entry["author"],
            license=entry["license"],
            license_url=entry["license_url"],
            retrieved=entry["retrieved"],
            crop_box=tuple(entry["crop_box"]) if entry.get("crop_box") else None,
            target_size=tuple(entry["target_size"]),
            jpeg_quality=int(entry["jpeg_quality"]),
            semantic_role=entry["semantic_role"],
            scenario_use=entry["scenario_use"],
        ))
    return out

def _validate_crop_box(crop_box, src_w, src_h, filename):
    """LOCKED FIX from review §2 #2: PIL silently clips OOB crops; we don't."""
    left, top, right, bottom = crop_box
    if not (0 <= left < right <= src_w and 0 <= top < bottom <= src_h):
        raise ValueError(
            f"{filename}: crop_box {crop_box} out of bounds for source "
            f"image {src_w}x{src_h}"
        )

def process_one(spec: FixtureSpec, *, out_dir: Path) -> Path:
    req = Request(spec.source_url, headers={"User-Agent": USER_AGENT})
    with urlopen(req) as resp:
        raw = resp.read()
    # LOCKED DECISION Q1: source-bytes drift detection. Verify sha256 BEFORE
    # any image processing. If this fails, the upstream changed and the
    # manifest must be reviewed manually — DO NOT auto-update.
    actual_sha = hashlib.sha256(raw).hexdigest()
    if actual_sha != spec.source_sha256:
        raise ValueError(
            f"{spec.filename}: source sha256 mismatch.\n"
            f"  expected: {spec.source_sha256}\n"
            f"  got:      {actual_sha}\n"
            f"  url:      {spec.source_url}\n"
            f"Upstream changed. Review manually before refreshing the manifest."
        )
    if raw[:2] != b"\xff\xd8" and raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{spec.filename}: source is not a JPEG or PNG (first bytes={raw[:4]!r})")
    img = Image.open(BytesIO(raw)).convert("RGB")
    if spec.crop_box:
        _validate_crop_box(spec.crop_box, img.width, img.height, spec.filename)
        img = img.crop(spec.crop_box)
    img.thumbnail(spec.target_size, Image.LANCZOS)
    out = out_dir / spec.filename
    img.save(out, format="JPEG", quality=spec.jpeg_quality, optimize=True)
    return out

def _existing_license_block(text: str, filename: str) -> Optional[str]:
    """Extract an existing block for `filename` from LICENSES.md, or None."""
    import re
    pattern = rf"^## {re.escape(filename)}\n.*?(?=^## |\Z)"
    m = re.search(pattern, text, flags=re.MULTILINE | re.DOTALL)
    return m.group(0) if m else None

def append_license_entry(licenses_path: Path, spec: FixtureSpec, *, rewrite: bool = False) -> None:
    """Append a provenance block for `spec`. Idempotent on identical content.
    If a block exists with DIFFERENT metadata (e.g., new author or URL),
    raise unless caller passes rewrite=True (LOCKED FIX from review §2 #3:
    don't silently let stale metadata stand).
    """
    text = licenses_path.read_text() if licenses_path.exists() else "# Fixture image provenance\n\n"
    new_block = (
        f"\n## {spec.filename}\n\n"
        f"- **Source URL:** {spec.source_url}\n"
        f"- **Source sha256:** `{spec.source_sha256}`\n"
        f"- **Title:** {spec.title}\n"
        f"- **Author / Credit:** {spec.author}\n"
        f"- **License:** {spec.license} ({spec.license_url})\n"
        f"- **Date retrieved:** {spec.retrieved}\n"
        f"- **Modifications:** "
        f"{'Cropped to ' + str(spec.crop_box) + '; ' if spec.crop_box else ''}"
        f"resized to ≤{spec.target_size[0]}×{spec.target_size[1]}, JPEG quality {spec.jpeg_quality}.\n"
        f"- **Semantic role:** {spec.semantic_role}\n"
        f"- **Scenario use:** {spec.scenario_use}\n"
    )
    existing = _existing_license_block(text, spec.filename)
    if existing is not None:
        if existing.strip() == new_block.strip():
            return  # truly idempotent, content matches
        if not rewrite:
            raise ValueError(
                f"{spec.filename}: LICENSES.md has an existing block with different "
                f"metadata. Pass --rewrite-license to replace it."
            )
        text = text.replace(existing, new_block.lstrip("\n"))
        licenses_path.write_text(text)
        return
    licenses_path.write_text(text + new_block)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", action="append", default=None)
    parser.add_argument("--rewrite-license", action="store_true",
                        help="Replace existing LICENSES.md blocks with new metadata")
    parser.add_argument("--bootstrap-sha256", action="store_true",
                        help="Fetch each URL, print 'filename: sha256' lines, write nothing")
    args = parser.parse_args()
    if args.bootstrap_sha256:
        # Bootstrap mode: skip schema validation (sha256 is what we're computing).
        data = json.loads(MANIFEST_PATH.read_text())
        for entry in data["fixtures"]:
            req = Request(entry["source_url"], headers={"User-Agent": USER_AGENT})
            with urlopen(req) as resp:
                raw = resp.read()
            print(f"{entry['filename']}: {hashlib.sha256(raw).hexdigest()}")
        return 0
    specs = load_manifest(MANIFEST_PATH)
    if args.only:
        specs = [s for s in specs if s.filename in set(args.only)]
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    for spec in specs:
        print(f"[{spec.filename}] {spec.source_url}")
        if args.dry_run:
            continue
        out = process_one(spec, out_dir=FRAMES_DIR)
        append_license_entry(LICENSES_PATH, spec, rewrite=args.rewrite_license)
        print(f"  -> {out} ({out.stat().st_size} bytes)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run unit tests, confirm green.**

```bash
uv run pytest scripts/tests/test_fetch_disaster_fixtures.py -v
```

- [ ] **Step 5: Commit.**

```bash
git add scripts/fetch_disaster_fixtures.py scripts/tests/test_fetch_disaster_fixtures.py
git commit -m "fixtures: fetch script with crop+resize+license-append (tests green)"
```

---

## Task 3: Run the fetch, swap real bytes

**Files:**
- Modify: `sim/fixtures/frames/placeholder_*.jpg` (7 files, content only)
- Modify: `sim/fixtures/frames/LICENSES.md` (append 7 entries)

- [ ] **Step 1: Dry run** to log every URL the script will hit.

```bash
uv run python -m scripts.fetch_disaster_fixtures --dry-run
```
Expected: 7 lines, each `[filename] URL`. No file writes. No network.

- [ ] **Step 2: Real run.**

```bash
uv run python -m scripts.fetch_disaster_fixtures
```
Expected: 7 file writes under `sim/fixtures/frames/`, 7 LICENSES.md sections appended.

- [ ] **Step 3: Verify dimensions and JPEG magic bytes manually.**

```bash
uv run python -c "
from PIL import Image
from pathlib import Path
for p in sorted(Path('sim/fixtures/frames').glob('placeholder_*.jpg')):
    with Image.open(p) as im:
        print(f'{p.name}: {im.width}x{im.height} {im.format}')
    assert p.read_bytes()[:2] == b'\xff\xd8'
"
```
Expected: every line shows `≤640 ≤480 JPEG`.

- [ ] **Step 4: Run existing frame-server tests to confirm no regression.**

```bash
uv run pytest sim/tests/test_frame_server.py -v
```
Expected: all green (the tests load the placeholder bytes, the swap doesn't change names or magic bytes).

- [ ] **Step 5: Commit the swap as a single atomic change.**

```bash
git add sim/fixtures/frames/placeholder_*.jpg sim/fixtures/frames/LICENSES.md
git commit -m "fixtures: swap placeholders for real public-domain disaster aerials (7 files)"
```

---

## Task 4: Provenance test (lockdown)

**Files:**
- Create: `sim/tests/test_fixture_provenance.py`

- [ ] **Step 1: Write the test.**

```python
"""Lockdown test: every placeholder JPEG in sim/fixtures/frames/ has
matching LICENSES.md attribution and meets the size/format constraints
that downstream consumers (FrameServer, drone agent perception node) rely on.

This catches: (a) silent re-introduction of synthetic placeholders without
attribution updates, (b) accidentally-large fixtures that bloat git, (c)
non-JPEG content under a .jpg extension."""
from __future__ import annotations
from pathlib import Path
from PIL import Image
import pytest

FRAMES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "frames"
LICENSES_PATH = FRAMES_DIR / "LICENSES.md"
MAX_W, MAX_H = 640, 480
MAX_SIZE_BYTES = 200_000  # 200KB ceiling — placeholders should be small

# LOCKED FIX from review §3 #1: drive parametrize off an explicit set, not a
# glob. A glob over an empty directory produces zero parametrized cases and
# the suite reports green — the lockdown locks down nothing. The explicit set
# means a missing fixture file is a hard failure.
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
    """Sanity floor: the expected set of fixtures all exist on disk.
    Without this, the parametrized tests below would silently produce zero
    cases on an empty fixtures dir and the suite would report green."""
    on_disk = {p.name for p in FRAMES_DIR.glob("placeholder_*.jpg")}
    missing = EXPECTED_FIXTURES - on_disk
    extra = on_disk - EXPECTED_FIXTURES
    assert not missing, f"missing expected fixtures: {sorted(missing)}"
    assert not extra, f"unexpected fixtures present: {sorted(extra)} (update EXPECTED_FIXTURES if intentional)"

@pytest.mark.parametrize("filename", sorted(EXPECTED_FIXTURES))
def test_jpeg_magic_bytes(filename: str):
    path = FRAMES_DIR / filename
    assert path.read_bytes()[:2] == b"\xff\xd8", f"{filename} missing JPEG magic bytes"

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
    assert size <= MAX_SIZE_BYTES, f"{filename} is {size} bytes (cap {MAX_SIZE_BYTES})"

@pytest.mark.parametrize("filename", sorted(EXPECTED_FIXTURES))
def test_has_license_entry(filename: str, license_text: str):
    assert f"## {filename}" in license_text, (
        f"{filename} has no entry in LICENSES.md — "
        "every fixture file must have full provenance attribution"
    )

def test_no_orphan_license_entries(license_text: str):
    """Reverse direction: every LICENSES.md entry maps to a real file."""
    import re
    entries = re.findall(r"^## (placeholder_[\w_]+\.jpg)$", license_text, re.MULTILINE)
    orphans = [e for e in entries if e not in EXPECTED_FIXTURES]
    assert not orphans, f"LICENSES.md mentions files that don't exist: {orphans}"
```

- [ ] **Step 2: Run, confirm green.**

```bash
uv run pytest sim/tests/test_fixture_provenance.py -v
```

- [ ] **Step 3: Commit.**

```bash
git add sim/tests/test_fixture_provenance.py
git commit -m "fixtures: add provenance lockdown tests (size/dim/license/orphan)"
```

---

## Task 5: Ground-truth manifest expansion + scenario-load regression

**Files:**
- Modify: `sim/scenarios/disaster_zone_v1_groundtruth.json`
- Modify: `sim/scenarios/resilience_v1_groundtruth.json` (LOCKED DECISION Q3)
- Create or extend: `sim/tests/test_groundtruth_schema.py`
- Create: `sim/tests/test_scenario_loads_with_real_fixtures.py` (LOCKED FIX from review §3 #2)

**Decision: what to add.** Keep filenames and existing entries unchanged. Add three eval-relevant fields per entry, all optional with defaults so nothing else breaks:
- `expected_finding_type`: one of `"victim" | "fire" | "smoke" | "damaged_structure" | "blocked_route"` (matches Contract 4 finding `type` enum).
- `expected_severity`: one of `"low" | "medium" | "high" | "critical"` (matches Contract 4 severity enum).
- `min_confidence`: float `0.0–1.0`. The threshold a perception eval should hit on this fixture before we call it a hit.

**Why these three:** they let an automated scorer count true positives (drone reports match expected_type ± min_confidence) and severity-class accuracy. Without them the manifest is descriptive metadata; with them it's a real eval target. Kaleel needs this to score his fine-tune on Day 10.

- [ ] **Step 1: Update `disaster_zone_v1_groundtruth.json`.** New shape:

```json
{
  "scenario_id": "disaster_zone_v1",
  "schema_version": "1.0.0",
  "extents": { "lat_min": 33.9990, "lat_max": 34.0010, "lon_min": -118.5010, "lon_max": -118.4990 },
  "victims": [
    {
      "id": "v01", "lat": 34.0006, "lon": -118.5004,
      "frame_file": "placeholder_victim_01.jpg",
      "in_or_near": "block_a",
      "expected_finding_type": "victim",
      "expected_severity": "high",
      "min_confidence": 0.55
    }
  ],
  "fires": [
    {
      "id": "f01", "lat": 34.0004, "lon": -118.4992,
      "frame_file": "placeholder_fire_01.jpg",
      "intensity": "medium",
      "expected_finding_type": "fire",
      "expected_severity": "high",
      "min_confidence": 0.6
    },
    {
      "id": "f02", "lat": 34.0006, "lon": -118.4994,
      "frame_file": "placeholder_smoke_01.jpg",
      "intensity": "low",
      "expected_finding_type": "smoke",
      "expected_severity": "medium",
      "min_confidence": 0.5
    }
  ],
  "damaged_structures": [
    {
      "id": "ds_a2", "lat": 34.0004, "lon": -118.5002,
      "frame_file": "placeholder_block_a_02.jpg",
      "damage_level": "major_damage",
      "expected_finding_type": "damaged_structure",
      "expected_severity": "high",
      "min_confidence": 0.55
    }
  ],
  "blocked_routes": [
    {
      "id": "br01", "lat": 34.0008, "lon": -118.4995,
      "frame_file": "placeholder_debris_01.jpg",
      "blockage_type": "debris",
      "expected_finding_type": "blocked_route",
      "expected_severity": "medium",
      "min_confidence": 0.5
    }
  ],
  "scripted_events": [
    {"t": 45,  "type": "drone_failure",  "drone_id": "drone1"},
    {"t": 60,  "type": "fire_spread",    "new_polygon": [[34.0005, -118.5005], [34.0008, -118.5005], [34.0008, -118.5001], [34.0005, -118.5001]]}
  ]
}
```

- [ ] **Step 2a (LOCKED DECISION Q3):** Apply the same eval-field expansion to `sim/scenarios/resilience_v1_groundtruth.json`. Every detection entry there gets `expected_finding_type`, `expected_severity`, and `min_confidence` with values matched to the resilience scenario's intent (the resilience scenario emphasizes drone failure and degraded coverage; severity values may skew higher to reflect "the operator must catch this even with one drone down").

- [ ] **Step 2b: Add schema test at `sim/tests/test_groundtruth_schema.py` covering BOTH manifests** (LOCKED DECISION Q3):

```python
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
FINDING_TYPES = {"victim", "fire", "smoke", "damaged_structure", "blocked_route"}
SEVERITIES = {"low", "medium", "high", "critical"}
DETECTION_KEYS = ("victims", "fires", "damaged_structures", "blocked_routes")
GROUNDTRUTH_FILES = (
    "disaster_zone_v1_groundtruth.json",
    "resilience_v1_groundtruth.json",
)

@pytest.fixture(scope="module", params=GROUNDTRUTH_FILES)
def groundtruth(request):
    return request.param, json.loads((GT_DIR / request.param).read_text())

@pytest.mark.parametrize("key", DETECTION_KEYS)
def test_each_entry_has_eval_fields(groundtruth, key: str):
    name, gt = groundtruth
    for entry in gt.get(key, []):
        ctx = f"{name}/{key}/{entry.get('id')}"
        assert "expected_finding_type" in entry, f"{ctx} missing expected_finding_type"
        assert entry["expected_finding_type"] in FINDING_TYPES, f"{ctx} bad type"
        assert "expected_severity" in entry, f"{ctx} missing expected_severity"
        assert entry["expected_severity"] in SEVERITIES, f"{ctx} bad severity"
        assert "min_confidence" in entry, f"{ctx} missing min_confidence"
        assert 0.0 <= entry["min_confidence"] <= 1.0, f"{ctx} confidence out of range"

def test_frame_files_exist(groundtruth):
    name, gt = groundtruth
    for key in DETECTION_KEYS:
        for entry in gt.get(key, []):
            ff = entry.get("frame_file")
            if ff:
                assert (FRAMES_DIR / ff).exists(), f"{name}/{key}/{entry['id']} references missing frame {ff}"
```

- [ ] **Step 2c (LOCKED FIX from review §3 #2): Add scenario-load regression test** at `sim/tests/test_scenario_loads_with_real_fixtures.py`. The plan's `--ticks 30 --dry-run` in Task 7 is a manual sanity-run; this is the automated equivalent. Catches the "I swapped the bytes but a corrupt JPEG breaks scenario load" failure mode.

```python
"""Regression: every scenario YAML that references the swapped fixtures
loads cleanly through FrameServer post-swap. Without this, a corrupt or
mis-encoded JPEG passes the lockdown tests but breaks the actual sim."""
from pathlib import Path
import pytest
from sim.frame_server import FrameServer
from sim.scenario import load_scenario

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FRAMES_DIR = REPO_ROOT / "sim" / "fixtures" / "frames"
SCENARIOS = (
    "disaster_zone_v1.yaml",
    "single_drone_smoke.yaml",
    "resilience_v1.yaml",
)

@pytest.mark.parametrize("scenario_name", SCENARIOS)
def test_scenario_loads_and_publishes_first_tick(scenario_name, fake_redis):
    scenario = load_scenario(REPO_ROOT / "sim" / "scenarios" / scenario_name)
    server = FrameServer(scenario, fake_redis, frames_dir=FRAMES_DIR)
    server.tick(tick_index=0)  # asserts no FileNotFoundError, no JPEG decode crash
```

- [ ] **Step 3: Run.**

```bash
uv run pytest sim/tests/test_groundtruth_schema.py -v
```

- [ ] **Step 4: Run full sim test suite to confirm no regression.**

```bash
uv run pytest sim/tests/ -v
```

- [ ] **Step 5: Commit.**

```bash
git add sim/scenarios/disaster_zone_v1_groundtruth.json sim/tests/test_groundtruth_schema.py
git commit -m "fixtures: expand groundtruth with expected_finding_type/severity/min_confidence"
```

---

## Task 6: Documentation updates

**Files:**
- Modify: `docs/STATUS.md`
- Modify: `docs/sim-reproduction.md`
- Modify: `docs/14-disaster-scene-design.md` (if it documents fixture sources)

- [ ] **Step 1: Update STATUS.md.** Edit the Thayyil row:

```markdown
### Thayyil — Simulation Co-Pilot (paired with Hazim)

**Done:** Co-author on sim PRs #11, #13, #14, #17, #18. Placeholder frames in
`sim/fixtures/frames/` swapped for real public-domain disaster aerials via
`scripts/fetch_disaster_fixtures.py` (reproducible from `scripts/fixtures_manifest.json`,
LICENSES.md complete, provenance + groundtruth lockdown tests green).
Ground-truth manifest expanded with `expected_finding_type` /
`expected_severity` / `min_confidence` for automated perception eval scoring.

**Left (Days 10–13):** Resilience scenario polish; integration testing prep
harness for Hazim.

**Left (Days 15–16):** Reproduction docs cold-tested from a fresh machine; on-call
for sim issues during submission.
```

  Also remove the "xBD frames not in `sim/fixtures/frames/` by Day 9" risk row
  (or strike it through with `~~...~~`-style closure noting the swap commit SHA).

- [ ] **Step 2: Update sim-reproduction.md.** Add one section near "Fixtures":

```markdown
### Reproducing fixture images

The 8 JPEGs under `sim/fixtures/frames/` are real public-domain disaster
aerials, not synthetic. The full source manifest lives at
`scripts/fixtures_manifest.json` and the fetch is fully reproducible:

```bash
uv run python -m scripts.fetch_disaster_fixtures --dry-run  # preview
uv run python -m scripts.fetch_disaster_fixtures            # fetch
```

Re-running produces byte-identical output (Pillow JPEG q85 is deterministic
for a given input). Every file has a full provenance entry in
`sim/fixtures/frames/LICENSES.md`. The provenance lockdown test at
`sim/tests/test_fixture_provenance.py` blocks any swap that drops attribution
or violates the ≤640×480 / ≤200KB constraint.
```

- [ ] **Step 3: Cross-check `docs/14-disaster-scene-design.md`.** If it
  references "synthetic placeholders" or "xBD-pending", update language.

- [ ] **Step 4: Commit docs.**

```bash
git add docs/STATUS.md docs/sim-reproduction.md docs/14-disaster-scene-design.md
git commit -m "docs: STATUS + sim-reproduction reflect fixture swap (Thayyil items 1+2 done)"
```

---

## Task 8: Static aerial base image (LOCKED DECISION Q4)

Closes the open `TODOS.md` item "Static aerial base image for map panel" in this same PR. Surface expands to scenario YAML + Flutter; needs Hazim review on the YAML schema change.

**Files:**
- Create: `sim/fixtures/base_images/disaster_zone_v1_base.jpg` (NOT under `frames/`; this is a one-shot scene aerial, not a per-tick frame)
- Modify: `scripts/fixtures_manifest.json` (add 8th entry for the base image)
- Modify: `sim/scenarios/disaster_zone_v1.yaml` (add `base_image_path` field at top level)
- Modify: `sim/fixtures/base_images/LICENSES.md` (new file with provenance)
- Modify: `frontend/flutter_dashboard/pubspec.yaml` (declare asset path)
- Modify: `frontend/flutter_dashboard/lib/widgets/map_panel.dart` (replace procedural grid background with `Image.asset` projected over the locked bbox)
- Test: `frontend/flutter_dashboard/test/map_panel_base_image_test.dart`

**Constraints:**
- Bbox must align to `disaster_zone_v1`'s `extents` (lat 33.999–34.001, lon -118.501 to -118.499 — a Los Angeles patch). USGS Earth Explorer or NASA Earth Observatory imagery for this lat/lon. If no clean USGS aerial exists for this exact extent, alternative: pick a different US-coastal-urban patch and update the scenario YAML's `extents` to match. Coordinate with Hazim before changing extents.
- Target size: 1024×1024 max (scene aerial; bigger than per-tick frames because Flutter zooms in/out). JPEG quality 85.
- Public-domain only. Same LICENSES.md treatment as the per-tick fixtures.

- [ ] **Step 1: Source curation.** Pick the aerial. Add an 8th entry to `scripts/fixtures_manifest.json` with `target_size: [1024, 1024]` and `scenario_use: "disaster_zone_v1 map_panel base background"`. Run `--bootstrap-sha256` to populate the sha256.

- [ ] **Step 2: Run the fetch script** for the new entry only:

```bash
uv run python -m scripts.fetch_disaster_fixtures --only disaster_zone_v1_base.jpg
```

- [ ] **Step 3: Wire the asset path.** Update `disaster_zone_v1.yaml`:

```yaml
# at top level, alongside scenario_id / origin / area_m
base_image_path: sim/fixtures/base_images/disaster_zone_v1_base.jpg
base_image_extents:
  lat_min: 33.9990
  lat_max: 34.0010
  lon_min: -118.5010
  lon_max: -118.4990
```

  Decide whether `base_image_extents` is required or optional. If Hazim's scenario loader (`sim/scenario.py`) currently rejects unknown top-level keys, gate the new fields on a schema bump and update the loader's allow-list.

- [ ] **Step 4: Update Flutter `pubspec.yaml`** to declare the asset:

```yaml
flutter:
  assets:
    - assets/base_images/disaster_zone_v1_base.jpg
```

  Copy the JPEG into `frontend/flutter_dashboard/assets/base_images/` (Flutter assets must live under the Flutter project root). Add a build-time check or a CI job that verifies the asset matches `sim/fixtures/base_images/disaster_zone_v1_base.jpg` byte-for-byte (sha256 compare). Otherwise the two copies drift.

- [ ] **Step 5: Replace procedural grid in `map_panel.dart` per LOCKED DESIGN DECISIONS D1, D2, D3.** Concrete spec:

  **5a. Plumb `base_image_path` and `base_image_extents` through state.** Extend `MissionState` to expose `String? baseImagePath` and `_Bbox? baseImageExtents`, populated from the `egs.state` WS payload. (Eng-review will validate the WS-bridge schema change with Qasim.)

  **5b. Lock bbox when image present (D1).** In `_MapPanelState.build()`:
  ```dart
  if (mission.baseImagePath != null && mission.baseImageExtents != null) {
    _bbox = mission.baseImageExtents;  // overrides the data-driven path
  } else {
    _bbox ??= _computeBbox(drones, findings);
    if (!_bboxStillCovers(_bbox!, drones, findings)) {
      _bbox = _computeBbox(drones, findings);
    }
  }
  ```
  Hide the "Refit" `IconButton` (`map_panel.dart:79-85`) when `baseImagePath != null`.

  **5c. Stack the layers (D2).** Replace the single `CustomPaint` background with a 3-layer stack:
  ```dart
  Stack(children: [
    // Layer 1: synchronous procedural grid (universal fallback / loading background)
    CustomPaint(size: Size.infinite, painter: _GridBackgroundPainter()),
    // Layer 2: aerial image fades in over 150ms when decoded
    if (mission.baseImagePath != null)
      AnimatedOpacity(
        opacity: _imageLoaded ? 0.80 : 0.0,
        duration: const Duration(milliseconds: 150),
        child: Image.asset(
          mission.baseImagePath!,
          fit: BoxFit.fill,
          errorBuilder: (_, _, _) {
            // schedule the toast on the next frame; layer stays transparent
            WidgetsBinding.instance.addPostFrameCallback((_) {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                  content: Text("Aerial overlay unavailable"),
                  duration: Duration(seconds: 4),
                ),
              );
            });
            return const SizedBox.shrink();
          },
          frameBuilder: (_, child, frame, _) {
            if (frame != null && !_imageLoaded) {
              WidgetsBinding.instance.addPostFrameCallback((_) {
                if (mounted) setState(() => _imageLoaded = true);
              });
            }
            return child;
          },
        ),
      ),
    // Layer 3: markers + projection painter (existing _ProjectionPainter, minus the bg paint)
    CustomPaint(size: Size.infinite, painter: _ProjectionPainter(...)),
    // ... existing finding+drone marker GestureDetectors unchanged
  ]);
  ```
  Move the existing background fill+grid lines from `_ProjectionPainter.paint()` (current `map_panel.dart:266-277`) into a new `_GridBackgroundPainter` so the marker painter is purely foreground.

  **5d. Marker contrast (D3).** In `_ProjectionPainter.paint()`:
  - **Drone-ID labels:** stop calling `TextPainter` directly. Replace with a `Positioned` widget rendered at the drone's projected `Offset` containing a white pill: `Container(padding: EdgeInsets.symmetric(horizontal: 6, vertical: 4), decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(8), boxShadow: [BoxShadow(color: Colors.black26, blurRadius: 2, offset: Offset(0, 1))]), child: Text(id, style: const TextStyle(fontSize: 11, color: Colors.black, fontWeight: FontWeight.w600)))`. Move label rendering OUT of the painter and into `_buildDroneMarkers()` so it's a real widget (a11y-discoverable, copyable, testable).
  - **Finding circles:** before the existing `canvas.drawCircle(p, 6, rect)`, draw a white outline first: `canvas.drawCircle(p, 7, Paint()..color = Colors.white)`. Net effect: 7px white halo, 6px colored disk on top.
  - **Touch targets a11y bundle:** `_droneHitRadius = 24` (was 18), `_findingHitRadius = 24` (was 14). Both meet the 44px iOS guideline. Pre-existing gap, fixed in this PR.

  **5e. Off-extents drone chevrons (D1 follow-on).** When a drone's projected `Offset` falls outside `[0, size.width] × [0, size.height]`, render a 16px filled triangle at the nearest canvas edge in the drone's palette color, rotated by `atan2(dy, dx)` toward the off-canvas position. On tap, show a SnackBar: `"drone1 is 247m east"` (compute distance from extents-edge to drone via Haversine, format as nearest cardinal). Add a unit test in `test/map_panel_offextents_test.dart` covering: (a) drone inside extents renders normal marker, (b) drone outside extents renders chevron, (c) tap on chevron surfaces correct distance+cardinal.

- [ ] **Step 6: Add Flutter widget tests** at `test/map_panel_base_image_test.dart` covering all three locked design decisions (D1, D2, D3):

```dart
testWidgets('D1: bbox locks to base_image_extents when path present', (tester) async {
  await tester.pumpWidget(MaterialApp(home: ChangeNotifierProvider.value(
    value: stateWithBaseImage(extents: testExtents),
    child: MapPanel(),
  )));
  await tester.pumpAndSettle();
  // Refit button must be hidden when image present (D1).
  expect(find.byTooltip('Refit'), findsNothing);
});

testWidgets('D1: drone outside extents renders as edge chevron', (tester) async {
  // Place drone1 at lat/lon outside testExtents; expect chevron, not marker.
  await tester.pumpWidget(...);
  expect(find.byKey(ValueKey('map-drone-chevron-drone1')), findsOneWidget);
  expect(find.byKey(ValueKey('map-drone-drone1')), findsNothing);
});

testWidgets('D2: grid renders synchronously, image fades in', (tester) async {
  await tester.pumpWidget(...);
  // First frame: grid painter present, image opacity 0.
  expect(find.byType(CustomPaint), findsWidgets);
  final opacity = tester.widget<AnimatedOpacity>(find.byType(AnimatedOpacity));
  expect(opacity.opacity, 0.0);
  // After image decodes: opacity reaches 0.80.
  await tester.pumpAndSettle(const Duration(milliseconds: 200));
  expect(tester.widget<AnimatedOpacity>(find.byType(AnimatedOpacity)).opacity, 0.80);
});

testWidgets('D2: missing-asset fallback shows toast, grid stays', (tester) async {
  await tester.pumpWidget(MaterialApp(home: MapPanel(/* path = bad_path.jpg */)));
  await tester.pumpAndSettle();
  expect(find.text('Aerial overlay unavailable'), findsOneWidget);
  // Grid still painted via _GridBackgroundPainter.
  expect(find.byType(CustomPaint), findsWidgets);
});

testWidgets('D3: drone label renders inside white pill, not raw text', (tester) async {
  await tester.pumpWidget(...);
  // Find the pill Container by the drone-id label widget key.
  final labelFinder = find.byKey(ValueKey('map-drone-label-drone1'));
  expect(labelFinder, findsOneWidget);
  final container = tester.widget<Container>(labelFinder);
  final decoration = container.decoration as BoxDecoration;
  expect(decoration.color, Colors.white);
  expect(decoration.borderRadius, BorderRadius.circular(8));
});

testWidgets('D3 a11y: touch targets are at least 44px', (tester) async {
  await tester.pumpWidget(...);
  final droneHit = tester.widget<SizedBox>(find.descendant(
    of: find.byKey(ValueKey('map-drone-drone1')),
    matching: find.byType(SizedBox),
  ));
  // _droneHitRadius bumped from 18 to 24, so target = 48px.
  expect(droneHit.width, greaterThanOrEqualTo(44.0));
});

testWidgets('fallback: map panel falls back to grid when path absent', (tester) async {
  await tester.pumpWidget(MaterialApp(home: MapPanel(state: stateWithoutBaseImage)));
  expect(find.byType(CustomPaint), findsWidgets);  // grid is CustomPaint
  expect(find.byType(AnimatedOpacity), findsNothing);  // no image layer
});
```

Also add `test/map_panel_offextents_test.dart` for the D1 chevron sub-spec (drone-inside-extents normal marker, drone-outside-extents chevron, tap surfaces correct distance+cardinal — see Step 5e).

- [ ] **Step 7: Update STATUS.md** Person 4 (you) row: add bullet noting the static aerial closed the TODO and is now visible in the demo capture path. Update Thayyil row to credit Person 5 contribution to the base-image source curation.

- [ ] **Step 8: Update `TODOS.md`** — mark `Static aerial base image for map panel` as **CLOSED** with a one-line resolution noting commit SHA.

- [ ] **Step 9: Commit.**

```bash
git add sim/fixtures/base_images/ sim/scenarios/disaster_zone_v1.yaml \
        scripts/fixtures_manifest.json \
        frontend/flutter_dashboard/pubspec.yaml \
        frontend/flutter_dashboard/lib/widgets/map_panel.dart \
        frontend/flutter_dashboard/assets/base_images/ \
        frontend/flutter_dashboard/test/map_panel_base_image_test.dart \
        docs/STATUS.md TODOS.md
git commit -m "fixtures: static aerial base image for disaster_zone_v1 map panel (closes TODOS.md item)"
```

---

## Task 7: Final verification

- [ ] **Step 1: Full test suite.**

```bash
uv run pytest sim/ scripts/ agents/drone_agent/ -v
```
Expected: every test green. Frame-server, fixture-provenance, groundtruth-schema,
fetch-script-unit, drone-agent perception integration — all pass.

- [ ] **Step 2: Sanity-run the disaster_zone_v1 scenario for 30 ticks** to
  confirm the new images flow through the FrameServer without surprises.

```bash
uv run python -m sim.frame_server --scenario disaster_zone_v1 --ticks 30 --dry-run
```
(Or whatever the existing dry-run flag is — check `sim/frame_server.py --help`.)

- [ ] **Step 3: Open PR.** Title: `fixtures: real public-domain disaster aerials + expanded groundtruth (Thayyil items 1+2)`.

  Body:
  ```
  ## Summary
  - Swap 7 synthetic placeholder JPEGs for real public-domain disaster aerials
    (FEMA / Wikimedia Commons / NASA), filenames preserved.
  - Reproducible via `scripts/fetch_disaster_fixtures.py` + `scripts/fixtures_manifest.json`.
  - LICENSES.md has full provenance for every file.
  - Groundtruth manifest expanded with expected_finding_type / expected_severity / min_confidence.
  - Provenance + groundtruth-schema lockdown tests added.

  ## Why programmatic
  Reproducibility (license audit trail, byte-identical re-fetches) and frees
  Thayyil for the Day 10–16 work that actually requires a human (resilience
  polish, cold-run reproduction test, submission on-call). xBD-proper
  (xView2 creds-gated, Kaleel's pipeline) is unaffected.

  ## Closes
  - STATUS.md risk row "xBD frames not in sim/fixtures/frames/ by Day 9"
  - Thayyil items 1 + 2 from STATUS.md

  ## Test plan
  - [x] sim/tests/test_frame_server.py green
  - [x] sim/tests/test_fixture_provenance.py green (new)
  - [x] sim/tests/test_groundtruth_schema.py green (new)
  - [x] scripts/tests/test_fetch_disaster_fixtures.py green (new)
  - [x] Dry-run + real fetch produce expected outputs
  - [x] disaster_zone_v1 30-tick dry run completes without errors
  ```

---

## Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Source URL rots between manifest commit and fetch run | Low | Low — pick another source, update manifest, re-run | Manifest is the audit trail; swap is one JSON edit |
| Wikimedia / FEMA rate-limits the fetch | Very low (7 requests, polite UA) | Low | `time.sleep(1)` between fetches if needed (not in initial cut) |
| Real images make the FrameServer test fixture-byte assertions non-deterministic | None | — | Tests load actual file bytes; swap is byte-stable per-commit |
| Image content doesn't actually match semantic role (e.g., "fire" image is just smoke) | Medium | Medium — Gemma vision quality drops | Curate carefully in Task 1; review with Hazim before Task 3 fetch |
| Filenames contain `xbd` references in docs that imply true xBD provenance | Low | Low — honesty issue | Task 6 Step 3 cross-check sweeps for misleading wording |

---

## NOT in scope

- **Real xBD downloads via xView2.** Credentials-gated; that's Kaleel's `ml/data_prep/download_xbd.py` pipeline. Rationale: separate concern, separate dataset, separate ownership.
- **Adding new groundtruth detection entries** (more victims, more fires). Rationale: requires scenario YAML coordination with Hazim and changes the test surface. Defer if Kaleel's GATE 3 eval reveals coverage gaps.
- **Pre-disaster paired imagery** (xBD's signature feature). Rationale: public-domain post-disaster aerials don't reliably come paired. Not blocking for sim-vision iteration.
- **Vision quality eval on the new fixtures.** Rationale: that's Kaleel's GATE 3 work using these as inputs. Out-of-scope here is "scoring quality"; in-scope here is "providing scoreable inputs".
- **Source-bytes cache repository** (committing raw upstream JPEGs alongside outputs as a bulletproof re-fetch fallback). Rationale: doubles storage, the `source_sha256` lockdown already converts drift to a loud failure rather than silent corruption. Re-add if drift events become frequent.

## What already exists

- `placeholder_victim_01.jpg` precedent (commit `30577e7`) — manual fetch, FEMA Katrina, full LICENSES.md entry. This plan generalizes that workflow.
- `sim/tests/test_frame_server.py` — tests that load fixture bytes off disk and assert frame-server serves them correctly. Stays valid post-swap (filenames preserved, magic bytes intact).
- `shared.contracts.validate(schema_name, payload)` — the project's JSON Schema validation pattern. Used by Contract 4, Contract 11, etc. This plan reuses it (LOCKED DECISION Q2) instead of building a parallel validation system.
- `Pillow` already in `[project.optional-dependencies].sim` extras — no new dep.
- `urllib.request` (stdlib) — no new dep.
- `disaster_zone_v1_groundtruth.json` and `resilience_v1_groundtruth.json` already exist with detection entries; this plan adds three eval fields per entry rather than restructuring.
- `frontend/flutter_dashboard/lib/widgets/map_panel.dart` already implements equirectangular projection with `cos(midLat)` longitude correction. Task 8 reuses this — only swaps the background paint, doesn't re-project.

## Worktree parallelization strategy

| Step | Modules touched | Depends on |
|------|----------------|------------|
| Task 1 (manifest + schema) | `scripts/`, `shared/schemas/` | — |
| Task 2 (fetch script) | `scripts/` | Task 1 |
| Task 3 (run fetch, swap bytes) | `sim/fixtures/frames/` | Task 2 |
| Task 4 (provenance test) | `sim/tests/` | Task 3 |
| Task 5 (groundtruth + scenario regression) | `sim/scenarios/`, `sim/tests/` | Task 3 |
| Task 6 (docs) | `docs/` | Task 3 |
| Task 8 (static aerial + Flutter) | `sim/fixtures/base_images/`, `sim/scenarios/`, `frontend/flutter_dashboard/` | Task 2 |
| Task 7 (final verification) | (read-only) | All above |

**Lanes:**
- Lane A (sequential, single worktree): Task 1 → Task 2 → Task 3 → Task 4. Each touches `scripts/` or `sim/`; sequential because Task 3 produces the byte-swap that Task 4 locks down.
- Lane B (parallel after Task 3): Task 5 (sim/scenarios + sim/tests) and Task 6 (docs/) — independent, no shared modules.
- Lane C (parallel after Task 2): Task 8 (Flutter + sim/fixtures/base_images) — does NOT need Task 3 done, only needs the fetch script working. Independent of Lanes A-tail and B.

**Execution order:** Run Task 1 → 2 → 3 sequentially. Then launch Tasks 4, 5, 6, 8 in parallel worktrees. Merge all. Then run Task 7 verification on the merged trunk.

**Conflict flags:** Task 5 and Task 8 both touch `sim/scenarios/disaster_zone_v1*` — Task 5 writes to `_groundtruth.json`, Task 8 writes to `disaster_zone_v1.yaml`. Different files, no merge conflict, but both reviewers should look at the YAML/JSON pair to confirm `frame_file` references stay consistent.

## Failure modes

| Codepath | Failure mode | Test? | Error handling? | User-visible? |
|---|---|---|---|---|
| `process_one()` source fetch | Network timeout | Surface via `urlopen` exception (no retry) | Yes (uncaught raises stop the loop) | Yes — script error message |
| `process_one()` source verify | sha256 drift | Yes (LOCKED Q1: explicit raise with diagnostic message) | Yes | Yes — clear "review manually" message |
| `process_one()` source format | Non-image bytes (HTML 404 page) | Implicit via existing magic-bytes check; covered by `test_process_one_resizes_and_writes_jpeg` mock variant | Yes — `ValueError` | Yes |
| `_validate_crop_box()` | OOB crop | Should be tested (LOCKED FIX from review §2 #2) | Yes — `ValueError` | Yes |
| `append_license_entry()` stale metadata | Existing block with different fields | Should be tested (LOCKED FIX from review §2 #3) | Yes — `ValueError` unless `--rewrite-license` | Yes |
| `test_fixture_provenance.py` empty fixtures dir | Glob returns zero, parametrize generates zero cases, suite green | LOCKED FIX from review §3 #1: `EXPECTED_FIXTURES` set + `test_all_expected_fixtures_present` | N/A | Test failure on missing fixture |
| `FrameServer` post-swap init | Corrupt JPEG that passes magic-bytes but fails Pillow decode | LOCKED FIX from review §3 #2: `test_scenario_loads_with_real_fixtures.py` | Existing `FileNotFoundError` from FrameServer init | Yes — sim startup fails |
| `map_panel.dart` Image.asset | Asset declared in pubspec but file missing | Flutter widget test (Task 8 Step 6) | Flutter renders error widget | Yes |

**Critical gaps after fixes:** none. All failure modes have either a test, error handling, or both.

---

## Completion Summary (from `/plan-eng-review` 2026-05-08)

- **Step 0 — Scope Challenge:** scope accepted; no reduction (4 logic files + 7 byte-swaps + docs is below complexity threshold).
- **Architecture Review:** 3 issues found — 1 contested (sha256 drift, LOCKED A), 2 simple-fix (UA placeholder, fallback risk acknowledged).
- **Code Quality Review:** 4 issues found — 1 contested (validation pattern, LOCKED A), 3 simple-fix (crop bounds, license-stale, markdown fence).
- **Test Review:** coverage diagram produced, 6 gaps identified — 1 CRITICAL silent-green (LOCKED FIX), 1 regression-class (LOCKED FIX), 1 contested (resilience scope, LOCKED A: bundle both).
- **Performance Review:** 0 issues.
- **NOT in scope:** written, 5 items with rationales.
- **What already exists:** written, 7 items.
- **TODOS.md updates:** 1 item proposed (static aerial bundle, LOCKED B: bundle into PR via Task 8). Item will be marked CLOSED when Task 8 ships.
- **Failure modes:** 8 paths analyzed, 0 critical gaps after fixes applied.
- **Outside voice:** skipped (small mechanical plan, low marginal value vs. cost).
- **Parallelization:** 3 lanes, Lane A sequential (Tasks 1→2→3→4), Lanes B+C parallel after Task 3 / Task 2 respectively.
- **Lake Score:** 4/4 contested decisions chose the complete option (sha256 verify, JSON Schema validation, both groundtruths, bundle base image).

**Unresolved decisions:** none.

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 11 issues, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 1 | CLEAR (FULL) | score: 3/10 → 9/10, 3 decisions |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

**UNRESOLVED:** 0
**VERDICT:** ENG + DESIGN CLEARED — ready to implement. Task 8 Step 5 spec now covers bbox locking (D1), image-load state machine (D2), and marker contrast on photographic background (D3). Task 8 Step 6 has widget tests for all three. Eng-review re-pass recommended ONLY if `base_image_extents` WS-bridge plumbing (Step 5a) raises schema concerns with Qasim.
