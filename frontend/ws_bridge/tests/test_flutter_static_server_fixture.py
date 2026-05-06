"""Smoke test: fixture builds Flutter web (if needed) and serves index.html.

Marked e2e because the underlying fixture requires the Flutter SDK and can
spend up to 5 minutes building build/web/ on a cold cache. CI's quick-run
filter (`-m "not e2e"`) excludes it; full-stack runs include it.
"""
from __future__ import annotations

import urllib.request

import pytest

pytestmark = pytest.mark.e2e


def test_flutter_static_server_serves_index(flutter_static_server):
    with urllib.request.urlopen(f"{flutter_static_server}/") as r:
        body = r.read().decode()
    assert r.status == 200
    assert "<!DOCTYPE html>" in body
    # Flutter bootstrap loader is a stable sentinel across Flutter 3.x web.
    assert "flutter_bootstrap.js" in body
