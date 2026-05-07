"""Smoke test: fixture builds Flutter web (if needed) and serves index.html.

Marked e2e because the underlying fixture requires the Flutter SDK and can
spend up to 5 minutes building build/web/ on a cold cache. CI's quick-run
filter (`-m "not e2e"`) excludes it; full-stack runs include it.

The staleness-detector unit tests below are NOT marked e2e — they exercise
``_flutter_bundle_is_stale`` against a synthetic tmp_path tree, so they
need no Flutter SDK and run in the default quick suite.
"""
from __future__ import annotations

import os
import time
import urllib.request

import pytest

from frontend.ws_bridge.tests.conftest import _flutter_bundle_is_stale


@pytest.mark.e2e
def test_flutter_static_server_serves_index(flutter_static_server):
    with urllib.request.urlopen(f"{flutter_static_server}/") as r:
        body = r.read().decode()
    assert r.status == 200
    assert "<!DOCTYPE html>" in body
    # Flutter bootstrap loader is a stable sentinel across Flutter 3.x web.
    assert "flutter_bootstrap.js" in body


# --- staleness detector unit tests (no Flutter SDK required) ----------------

def _touch(path, mtime):
    """Set both atime and mtime on path to the given epoch seconds."""
    os.utime(path, (mtime, mtime))


def test_flutter_bundle_is_stale_returns_false_when_build_is_newer(tmp_path):
    """Common case: bundle was built after the last source edit."""
    lib = tmp_path / "lib"
    lib.mkdir()
    src = lib / "main.dart"
    src.write_text("void main() {}")
    _touch(src, time.time() - 100)  # source: 100s ago

    build = tmp_path / "build" / "web"
    build.mkdir(parents=True)
    index = build / "index.html"
    index.write_text("<!DOCTYPE html>")
    _touch(index, time.time())  # build: now

    assert _flutter_bundle_is_stale(index, lib) is False


def test_flutter_bundle_is_stale_returns_true_when_source_is_newer(tmp_path):
    """Stale-bundle case: a developer edited a Dart source after the last build.

    This is the exact scenario from the bug report: ``findings_panel.dart``
    gained ``FindingsCountSummary`` after the last ``flutter build web``,
    so the bundle no longer reflects the source.
    """
    lib = tmp_path / "lib"
    (lib / "widgets").mkdir(parents=True)
    src = lib / "widgets" / "findings_panel.dart"
    src.write_text("// new widget")

    build = tmp_path / "build" / "web"
    build.mkdir(parents=True)
    index = build / "index.html"
    index.write_text("<!DOCTYPE html>")
    _touch(index, time.time() - 100)  # build: 100s ago
    _touch(src, time.time())  # source: now

    assert _flutter_bundle_is_stale(index, lib) is True


def test_flutter_bundle_is_stale_only_walks_dart_files(tmp_path):
    """Non-Dart files (e.g. *.md, *.iml) must not trigger a rebuild."""
    lib = tmp_path / "lib"
    lib.mkdir()
    dart_src = lib / "main.dart"
    dart_src.write_text("void main() {}")
    _touch(dart_src, time.time() - 100)

    other_src = lib / "README.md"  # not Dart; should be ignored
    other_src.write_text("# notes")

    build = tmp_path / "build" / "web"
    build.mkdir(parents=True)
    index = build / "index.html"
    index.write_text("<!DOCTYPE html>")
    _touch(index, time.time() - 50)

    _touch(other_src, time.time())  # newer non-Dart file

    assert _flutter_bundle_is_stale(index, lib) is False


def test_flutter_bundle_is_stale_returns_false_when_index_missing(tmp_path):
    """Missing index.html is the existing fixture's auto-build trigger;
    the staleness detector must defer to that path (return False so the
    fixture's existing missing-file branch handles it)."""
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "main.dart").write_text("void main() {}")

    build = tmp_path / "build" / "web"
    build.mkdir(parents=True)
    index = build / "index.html"  # not created

    assert _flutter_bundle_is_stale(index, lib) is False


def test_flutter_bundle_is_stale_handles_nested_lib_subdirs(tmp_path):
    """Nested ``lib/widgets/foo/bar.dart`` must be detected via rglob."""
    lib = tmp_path / "lib"
    nested = lib / "widgets" / "deep"
    nested.mkdir(parents=True)
    src = nested / "bar.dart"
    src.write_text("// deep")

    build = tmp_path / "build" / "web"
    build.mkdir(parents=True)
    index = build / "index.html"
    index.write_text("<!DOCTYPE html>")
    _touch(index, time.time() - 100)
    _touch(src, time.time())

    assert _flutter_bundle_is_stale(index, lib) is True
