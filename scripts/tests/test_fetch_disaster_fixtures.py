"""Unit tests for scripts/fetch_disaster_fixtures.py.

Network is fully mocked via patching scripts.fetch_disaster_fixtures._fetch_bytes,
so this suite runs offline and deterministically. The integration test that
actually hits Wikimedia/FEMA lives elsewhere (Task 7 verification, manual)."""
from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from scripts.fetch_disaster_fixtures import (
    FixtureSpec,
    append_license_entry,
    load_manifest,
    process_one,
    _format_license_block,
    _existing_license_block,
    _validate_crop_box,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_jpeg_bytes(w=1024, h=768, color=(80, 80, 80)) -> bytes:
    img = Image.new("RGB", (w, h), color)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _spec(**overrides) -> FixtureSpec:
    base = dict(
        filename="placeholder_test.jpg",
        source_url="https://example.test/x.jpg",
        source_sha256="a" * 64,
        title="Test image",
        author="Test author",
        license="Public Domain",
        license_url="https://example.test/lic",
        retrieved="2026-05-08",
        crop_box=None,
        target_size=(640, 480),
        jpeg_quality=85,
        semantic_role="test role",
        scenario_use="test use",
    )
    base.update(overrides)
    return FixtureSpec(**base)


# ---------------------------------------------------------------------------
# load_manifest: schema validation + parsing
# ---------------------------------------------------------------------------


def test_load_manifest_valid_round_trip(tmp_path: Path):
    manifest = {
        "schema_version": "1.0.0",
        "fixtures": [{
            "filename": "placeholder_x.jpg",
            "source_url": "https://example.test/x.jpg",
            "source_sha256": "a" * 64,
            "title": "T", "author": "A",
            "license": "PD", "license_url": "https://example.test/lic",
            "retrieved": "2026-05-08",
            "crop_box": None,
            "target_size": [640, 480],
            "jpeg_quality": 85,
            "semantic_role": "r", "scenario_use": "u",
        }],
    }
    path = tmp_path / "m.json"
    path.write_text(json.dumps(manifest))
    specs = load_manifest(path)
    assert len(specs) == 1
    s = specs[0]
    assert s.filename == "placeholder_x.jpg"
    assert s.source_sha256 == "a" * 64
    assert s.target_size == (640, 480)
    assert s.crop_box is None


def test_load_manifest_rejects_missing_source_sha256(tmp_path: Path):
    bad = {
        "schema_version": "1.0.0",
        "fixtures": [{
            "filename": "placeholder_x.jpg",
            "source_url": "https://example.test/x.jpg",
            # source_sha256 missing — the load-bearing field per Q1
            "title": "T", "author": "A",
            "license": "PD", "license_url": "https://example.test/lic",
            "retrieved": "2026-05-08",
            "target_size": [640, 480],
            "jpeg_quality": 85,
            "semantic_role": "r", "scenario_use": "u",
        }],
    }
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="source_sha256"):
        load_manifest(path)


def test_load_manifest_rejects_malformed_sha256(tmp_path: Path):
    bad = {
        "schema_version": "1.0.0",
        "fixtures": [{
            "filename": "placeholder_x.jpg",
            "source_url": "https://example.test/x.jpg",
            "source_sha256": "XXX",  # not 64 hex chars
            "title": "T", "author": "A",
            "license": "PD", "license_url": "https://example.test/lic",
            "retrieved": "2026-05-08",
            "target_size": [640, 480],
            "jpeg_quality": 85,
            "semantic_role": "r", "scenario_use": "u",
        }],
    }
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="source_sha256"):
        load_manifest(path)


def test_load_manifest_carries_crop_box_as_tuple(tmp_path: Path):
    manifest = {
        "schema_version": "1.0.0",
        "fixtures": [{
            "filename": "placeholder_x.jpg",
            "source_url": "https://example.test/x.jpg",
            "source_sha256": "a" * 64,
            "title": "T", "author": "A",
            "license": "PD", "license_url": "https://example.test/lic",
            "retrieved": "2026-05-08",
            "crop_box": [0, 0, 512, 512],
            "target_size": [640, 480],
            "jpeg_quality": 85,
            "semantic_role": "r", "scenario_use": "u",
        }],
    }
    path = tmp_path / "m.json"
    path.write_text(json.dumps(manifest))
    [spec] = load_manifest(path)
    assert spec.crop_box == (0, 0, 512, 512)
    assert isinstance(spec.crop_box, tuple)


# ---------------------------------------------------------------------------
# process_one: sha256 verification, format guard, crop bounds, resize
# ---------------------------------------------------------------------------


def test_process_one_resizes_and_writes_jpeg(tmp_path: Path):
    raw = _make_jpeg_bytes(1024, 768)
    spec = _spec(source_sha256=hashlib.sha256(raw).hexdigest())
    with patch("scripts.fetch_disaster_fixtures._fetch_bytes", return_value=raw):
        out = process_one(spec, out_dir=tmp_path)
    assert out.exists()
    assert out.read_bytes()[:2] == b"\xff\xd8"
    with Image.open(out) as im:
        assert im.width <= 640 and im.height <= 480
        assert im.format == "JPEG"


def test_process_one_sha256_mismatch_raises_with_context(tmp_path: Path):
    """LOCKED Q1: drift detection. The error must clearly say what the
    operator should do."""
    raw = _make_jpeg_bytes()
    spec = _spec(source_sha256="b" * 64)  # not the real sha
    with patch("scripts.fetch_disaster_fixtures._fetch_bytes", return_value=raw):
        with pytest.raises(ValueError) as exc:
            process_one(spec, out_dir=tmp_path)
    msg = str(exc.value)
    assert "sha256 mismatch" in msg
    assert "expected:" in msg and "got:" in msg
    assert "Review manually" in msg


def test_process_one_rejects_html_response_masquerading_as_jpg(tmp_path: Path):
    """A 404 page returned with Content-Type: image/jpeg has happened in the wild.
    The magic-bytes check is the last line of defense before Pillow."""
    html = b"<html><body>404 Not Found</body></html>"
    spec = _spec(source_sha256=hashlib.sha256(html).hexdigest())
    with patch("scripts.fetch_disaster_fixtures._fetch_bytes", return_value=html):
        with pytest.raises(ValueError, match="not a JPEG or PNG"):
            process_one(spec, out_dir=tmp_path)


def test_process_one_applies_crop_box(tmp_path: Path):
    raw = _make_jpeg_bytes(1024, 1024)
    spec = _spec(
        source_sha256=hashlib.sha256(raw).hexdigest(),
        crop_box=(0, 0, 512, 512),
    )
    with patch("scripts.fetch_disaster_fixtures._fetch_bytes", return_value=raw):
        process_one(spec, out_dir=tmp_path)
    with Image.open(tmp_path / spec.filename) as im:
        # 512×512 crop, then thumbnail into 640×480 → stays square 480×480
        assert im.width == im.height
        assert im.width <= 480


def test_process_one_rejects_oob_crop_box(tmp_path: Path):
    """LOCKED FIX from review §2 #2: PIL silently clips OOB crops; we don't."""
    raw = _make_jpeg_bytes(1024, 768)
    spec = _spec(
        source_sha256=hashlib.sha256(raw).hexdigest(),
        crop_box=(0, 0, 99999, 99999),
    )
    with patch("scripts.fetch_disaster_fixtures._fetch_bytes", return_value=raw):
        with pytest.raises(ValueError, match="out of bounds"):
            process_one(spec, out_dir=tmp_path)


def test_validate_crop_box_accepts_inclusive_max():
    """Boundary: a crop box that exactly hits the source dimensions is valid."""
    _validate_crop_box((0, 0, 1024, 768), 1024, 768, "x.jpg")  # no raise


def test_validate_crop_box_rejects_zero_area():
    with pytest.raises(ValueError, match="out of bounds"):
        _validate_crop_box((10, 10, 10, 10), 1024, 768, "x.jpg")


# ---------------------------------------------------------------------------
# append_license_entry: idempotency + stale-metadata guard
# ---------------------------------------------------------------------------


def test_append_license_idempotent_on_identical_content(tmp_path: Path):
    licenses = tmp_path / "LICENSES.md"
    licenses.write_text("# Fixture image provenance\n\n")
    spec = _spec(filename="placeholder_x.jpg")
    append_license_entry(licenses, spec)
    append_license_entry(licenses, spec)  # second call is a no-op
    text = licenses.read_text()
    assert text.count("## placeholder_x.jpg") == 1


def test_append_license_raises_on_stale_without_rewrite_flag(tmp_path: Path):
    """LOCKED FIX from review §2 #3."""
    licenses = tmp_path / "LICENSES.md"
    licenses.write_text("# Fixture image provenance\n\n")
    spec_old = _spec(filename="placeholder_x.jpg", author="Original Author")
    append_license_entry(licenses, spec_old)
    spec_new = _spec(filename="placeholder_x.jpg", author="Different Author")
    with pytest.raises(ValueError, match="rewrite-license"):
        append_license_entry(licenses, spec_new)


def test_append_license_rewrite_flag_replaces_block(tmp_path: Path):
    licenses = tmp_path / "LICENSES.md"
    licenses.write_text("# Fixture image provenance\n\n")
    spec_old = _spec(filename="placeholder_x.jpg", author="Original Author")
    append_license_entry(licenses, spec_old)
    spec_new = _spec(filename="placeholder_x.jpg", author="Different Author")
    append_license_entry(licenses, spec_new, rewrite=True)
    text = licenses.read_text()
    assert text.count("## placeholder_x.jpg") == 1
    assert "Different Author" in text
    assert "Original Author" not in text


def test_append_license_creates_file_if_missing(tmp_path: Path):
    licenses = tmp_path / "subdir" / "LICENSES.md"
    spec = _spec(filename="placeholder_x.jpg")
    append_license_entry(licenses, spec)
    assert licenses.exists()
    text = licenses.read_text()
    assert "# Fixture image provenance" in text
    assert "## placeholder_x.jpg" in text


def test_existing_license_block_extracts_until_next_heading():
    text = (
        "# Fixture image provenance\n\n"
        "## placeholder_a.jpg\n\n"
        "- foo\n- bar\n\n"
        "## placeholder_b.jpg\n\n"
        "- baz\n"
    )
    block_a = _existing_license_block(text, "placeholder_a.jpg")
    assert block_a is not None
    assert "- foo" in block_a and "- bar" in block_a
    assert "placeholder_b.jpg" not in block_a
    assert "- baz" not in block_a


def test_format_license_block_includes_sha256():
    spec = _spec(source_sha256="d" * 64)
    block = _format_license_block(spec)
    assert "Source sha256" in block
    assert "d" * 64 in block


def test_format_license_block_omits_crop_when_none():
    spec = _spec(crop_box=None)
    block = _format_license_block(spec)
    assert "Cropped to" not in block


def test_format_license_block_includes_crop_when_set():
    spec = _spec(crop_box=(10, 20, 100, 200))
    block = _format_license_block(spec)
    assert "Cropped to (10, 20, 100, 200)" in block


# ---------------------------------------------------------------------------
# is_base_image routing
# ---------------------------------------------------------------------------


def test_is_base_image_routes_correctly():
    assert _spec(filename="placeholder_block_a_01.jpg").is_base_image is False
    assert _spec(filename="placeholder_victim_01.jpg").is_base_image is False
    assert _spec(filename="disaster_zone_v1_base.jpg").is_base_image is True


# ---------------------------------------------------------------------------
# _fetch_bytes hard caps (review fix #3)
# ---------------------------------------------------------------------------


def test_fetch_bytes_aborts_on_oversized_payload():
    """A multi-GB malicious payload would OOM resp.read() with no cap.
    We read FETCH_MAX_BYTES+1 — if the +1 byte appears, abort."""
    from scripts.fetch_disaster_fixtures import _fetch_bytes, FETCH_MAX_BYTES

    class _FakeResp:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, n=None):
            # Simulate upstream returning more than the cap.
            return b"X" * (FETCH_MAX_BYTES + 100)

    with patch("scripts.fetch_disaster_fixtures.urlopen", return_value=_FakeResp()):
        with pytest.raises(ValueError, match="exceeds .* byte cap"):
            _fetch_bytes("https://example.test/huge.jpg")


def test_fetch_bytes_under_cap_returns_normally():
    from scripts.fetch_disaster_fixtures import _fetch_bytes

    class _FakeResp:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, n=None):
            return b"OK" * 10

    with patch("scripts.fetch_disaster_fixtures.urlopen", return_value=_FakeResp()):
        out = _fetch_bytes("https://example.test/small.jpg")
        assert out == b"OK" * 10


def test_fetch_bytes_passes_timeout_to_urlopen():
    from scripts.fetch_disaster_fixtures import _fetch_bytes, FETCH_TIMEOUT_S

    class _FakeResp:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, n=None):
            return b"OK"

    with patch("scripts.fetch_disaster_fixtures.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _FakeResp()
        _fetch_bytes("https://example.test/x.jpg")
        # The second positional arg or `timeout` kwarg must equal FETCH_TIMEOUT_S.
        call = mock_urlopen.call_args
        timeout = call.kwargs.get("timeout") if call.kwargs else None
        if timeout is None and len(call.args) >= 2:
            timeout = call.args[1]
        assert timeout == FETCH_TIMEOUT_S, (
            f"expected timeout={FETCH_TIMEOUT_S}, got {timeout}"
        )


# ---------------------------------------------------------------------------
# License-block regex anchoring (review fix #4)
# ---------------------------------------------------------------------------


def test_existing_license_block_ignores_mid_line_double_hash():
    """A `## ` substring appearing mid-line inside a license body shouldn't
    truncate the block. With re.MULTILINE + ^ anchor, only line-leading
    `## ` headings act as terminators."""
    text = (
        "# Fixture image provenance\n\n"
        "## placeholder_a.jpg\n\n"
        "- **Note:** This image was rated `## 5 stars` by reviewers (literal markdown).\n"
        "- **Source URL:** https://example.test/x.jpg\n\n"
        "## placeholder_b.jpg\n\n"
        "- **Source URL:** https://example.test/y.jpg\n"
    )
    block_a = _existing_license_block(text, "placeholder_a.jpg")
    assert block_a is not None
    assert "rated `## 5 stars`" in block_a, (
        "block was truncated at mid-line `## ` — regex isn't anchored to ^"
    )
    assert "placeholder_b.jpg" not in block_a
