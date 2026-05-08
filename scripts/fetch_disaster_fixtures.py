"""Fetch and resize public-domain disaster aerials into sim/fixtures/frames/.

Reproducibility model (per LOCKED DECISION Q1 in
docs/plans/2026-05-08-thayyil-fixtures-swap.md): the manifest pins a
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
    python -m scripts.fetch_disaster_fixtures --rewrite-license
        # replace existing LICENSES.md blocks instead of erroring on stale
        # metadata (e.g., when an attribution actually changed upstream).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple
from urllib.request import Request, urlopen

from PIL import Image

from shared.contracts import validate

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "scripts" / "fixtures_manifest.json"
FRAMES_DIR = REPO_ROOT / "sim" / "fixtures" / "frames"
BASE_IMAGES_DIR = REPO_ROOT / "sim" / "fixtures" / "base_images"
FRAMES_LICENSES_PATH = FRAMES_DIR / "LICENSES.md"
BASE_IMAGES_LICENSES_PATH = BASE_IMAGES_DIR / "LICENSES.md"

# Real maintainer email per Wikimedia UA policy. Wikimedia rejects requests
# from generic curl/python UAs and asks for a contact in the UA string.
USER_AGENT = (
    "GemmaGuardian-Hackathon/1.0 "
    "(https://github.com/ibrahim7860/Gemma-Guardian; "
    "contact: darkmatter8789@gmail.com)"
)
# Hard caps for `_fetch_bytes` (review fix #3): a hung Wikimedia mirror
# blocks CI; a malicious or compromised mirror could OOM the process via
# `resp.read()` with no size limit. The downstream sha256 check protects
# integrity but not availability — these caps protect availability.
FETCH_TIMEOUT_S = 30
FETCH_MAX_BYTES = 50 * 1024 * 1024  # 50 MB


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

    @property
    def is_base_image(self) -> bool:
        """Base scene aerials live under sim/fixtures/base_images/, NOT under
        sim/fixtures/frames/. They aren't per-tick frames, they're a static
        scene background for the Flutter map panel."""
        return "base" in self.filename and "placeholder" not in self.filename


def load_manifest(path: Path) -> list[FixtureSpec]:
    """Read manifest JSON, validate against shared.contracts schema, return
    a list of FixtureSpec (LOCKED DECISION Q2)."""
    data = json.loads(path.read_text())
    outcome = validate("fixtures_manifest", data)
    if not outcome.valid:
        raise ValueError(
            f"manifest at {path} failed schema validation:\n  "
            + "\n  ".join(f"{e.field_path}: {e.message}" for e in outcome.errors)
        )
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
    """LOCKED FIX from review §2 #2: PIL silently clips out-of-bounds crops;
    we don't. A typo like [0, 0, 99999, 99999] should be a loud error."""
    left, top, right, bottom = crop_box
    if not (0 <= left < right <= src_w and 0 <= top < bottom <= src_h):
        raise ValueError(
            f"{filename}: crop_box {crop_box} out of bounds for source "
            f"image {src_w}x{src_h}"
        )


def _fetch_bytes(url: str) -> bytes:
    """Fetch URL with timeout + size cap. Raises ValueError on overrun.

    Adversarial-review fix: bare urlopen has no timeout (default is global
    socket timeout, often None) and no size cap. Either failure mode hangs
    or kills CI. We read up to FETCH_MAX_BYTES + 1 — if the +1 byte appears,
    the upstream exceeds our cap and we abort before allocating more memory.
    """
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=FETCH_TIMEOUT_S) as resp:
        raw = resp.read(FETCH_MAX_BYTES + 1)
    if len(raw) > FETCH_MAX_BYTES:
        raise ValueError(
            f"{url}: upstream payload exceeds {FETCH_MAX_BYTES} byte cap "
            f"(read {len(raw)} bytes before stopping)"
        )
    return raw


def process_one(spec: FixtureSpec, *, out_dir: Path) -> Path:
    raw = _fetch_bytes(spec.source_url)
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
        raise ValueError(
            f"{spec.filename}: source is not a JPEG or PNG "
            f"(first bytes={raw[:4]!r})"
        )
    img = Image.open(BytesIO(raw)).convert("RGB")
    if spec.crop_box:
        _validate_crop_box(spec.crop_box, img.width, img.height, spec.filename)
        img = img.crop(spec.crop_box)
    img.thumbnail(spec.target_size, Image.LANCZOS)
    out = out_dir / spec.filename
    out_dir.mkdir(parents=True, exist_ok=True)
    img.save(out, format="JPEG", quality=spec.jpeg_quality, optimize=True)
    return out


def _existing_license_block(text: str, filename: str) -> Optional[str]:
    """Extract an existing block for `filename` from LICENSES.md, or None.
    A block runs from `## filename` up to the next `## ` heading at the
    start of a line, or EOF.

    Adversarial-review fix: anchor the heading match to start-of-line via
    re.MULTILINE so a `## ` substring appearing mid-line in license body
    text doesn't truncate the block."""
    pattern = rf"^## {re.escape(filename)}\n.*?(?=\n^## |\Z)"
    m = re.search(pattern, text, flags=re.DOTALL | re.MULTILINE)
    return m.group(0) if m else None


def _format_license_block(spec: FixtureSpec) -> str:
    crop_str = (
        f"Cropped to {spec.crop_box}; "
        if spec.crop_box else ""
    )
    return (
        f"## {spec.filename}\n\n"
        f"- **Source URL:** {spec.source_url}\n"
        f"- **Source sha256:** `{spec.source_sha256}`\n"
        f"- **Title:** {spec.title}\n"
        f"- **Author / Credit:** {spec.author}\n"
        f"- **License:** {spec.license} ({spec.license_url})\n"
        f"- **Date retrieved:** {spec.retrieved}\n"
        f"- **Modifications:** {crop_str}"
        f"resized to ≤{spec.target_size[0]}×{spec.target_size[1]}, "
        f"JPEG quality {spec.jpeg_quality}.\n"
        f"- **Semantic role:** {spec.semantic_role}\n"
        f"- **Scenario use:** {spec.scenario_use}\n"
    )


def append_license_entry(licenses_path: Path, spec: FixtureSpec, *, rewrite: bool = False) -> None:
    """Append a provenance block for `spec`. Idempotent on identical content.
    If a block exists with DIFFERENT metadata (e.g., new author or URL),
    raise unless caller passes rewrite=True (LOCKED FIX from review §2 #3:
    don't silently let stale metadata stand).
    """
    if licenses_path.exists():
        text = licenses_path.read_text()
    else:
        licenses_path.parent.mkdir(parents=True, exist_ok=True)
        text = "# Fixture image provenance\n\n"
    new_block = _format_license_block(spec)
    existing = _existing_license_block(text, spec.filename)
    if existing is not None:
        if existing.strip() == new_block.strip():
            return  # truly idempotent, content matches
        if not rewrite:
            raise ValueError(
                f"{spec.filename}: LICENSES.md has an existing block with different "
                f"metadata. Pass --rewrite-license to replace it."
            )
        text = text.replace(existing, new_block.rstrip())
        licenses_path.write_text(text)
        return
    sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    licenses_path.write_text(text + sep + new_block)


def _out_dir_for(spec: FixtureSpec) -> Path:
    return BASE_IMAGES_DIR if spec.is_base_image else FRAMES_DIR


def _licenses_path_for(spec: FixtureSpec) -> Path:
    return BASE_IMAGES_LICENSES_PATH if spec.is_base_image else FRAMES_LICENSES_PATH


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="print URLs that would be fetched, write nothing")
    parser.add_argument("--only", action="append", default=None,
                        help="filename to fetch (can be passed multiple times)")
    parser.add_argument("--rewrite-license", action="store_true",
                        help="replace existing LICENSES.md blocks with new metadata")
    parser.add_argument("--bootstrap-sha256", action="store_true",
                        help="fetch each URL, print 'filename: sha256' lines, write nothing")
    args = parser.parse_args(argv)

    if args.bootstrap_sha256:
        # Bootstrap: skip schema validation (sha256 is what we're computing).
        # Print "filename: sha256" lines for the operator to paste back into the manifest.
        data = json.loads(MANIFEST_PATH.read_text())
        for entry in data["fixtures"]:
            raw = _fetch_bytes(entry["source_url"])
            print(f"{entry['filename']}: {hashlib.sha256(raw).hexdigest()}")
        return 0

    specs = load_manifest(MANIFEST_PATH)
    if args.only:
        wanted = set(args.only)
        specs = [s for s in specs if s.filename in wanted]
        missing = wanted - {s.filename for s in specs}
        if missing:
            raise SystemExit(f"--only filenames not in manifest: {sorted(missing)}")

    for spec in specs:
        out_dir = _out_dir_for(spec)
        licenses_path = _licenses_path_for(spec)
        print(f"[{spec.filename}] {spec.source_url}")
        if args.dry_run:
            continue
        out = process_one(spec, out_dir=out_dir)
        append_license_entry(licenses_path, spec, rewrite=args.rewrite_license)
        print(f"  -> {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
