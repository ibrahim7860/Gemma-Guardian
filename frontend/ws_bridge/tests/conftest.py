"""Shared fixtures for bridge WS tests.

Discovered automatically by pytest — no import needed at call site.

Convention: every fixture here is function-scoped, monkeypatch-aware,
and pinned to the running pytest-asyncio loop. The pytest.ini setting
``asyncio_default_fixture_loop_scope = function`` is what makes
fakeredis bind to the same loop as the test.
"""
from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import fakeredis.aioredis as fakeredis_async
import pytest
import pytest_asyncio

REPO_ROOT_FOR_FLUTTER = Path(__file__).resolve().parents[3]


@pytest_asyncio.fixture
async def fake_client():
    """A fakeredis client bound to the running pytest-asyncio loop.

    Used by every test that needs the bridge to talk to a Redis-compatible
    backend without spawning a real redis-server.
    """
    client = fakeredis_async.FakeRedis()
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def app_and_redis(monkeypatch, fake_client):
    """Yields ``(app, fake_redis)`` with the bridge's lifespan active.

    Each test constructs its own ``ASGIWebSocketTransport`` +
    ``httpx.AsyncClient`` via ``make_test_client(app)`` from ``_helpers.py``.
    This avoids httpx-ws 0.8's strict same-task entry/exit check, which
    pytest-asyncio's split fixture setup/teardown otherwise violates.
    """
    import redis.asyncio as redis_async

    monkeypatch.setattr(
        redis_async.Redis,
        "from_url",
        staticmethod(lambda url, **kw: fake_client),
    )

    from frontend.ws_bridge.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        yield app, fake_client


def _free_port_sync() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_for_http_ok(port: int, deadline_s: float = 5.0) -> bool:
    import urllib.request
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=0.5) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.1)
    return False


@pytest.fixture(scope="session")
def flutter_web_build_dir() -> Path:
    """Returns Path to a built Flutter web bundle. Skips if Flutter SDK absent.

    Builds on first call per session if build/web/index.html is missing.
    Subsequent fixtures reuse the artifact.
    """
    flutter_root = REPO_ROOT_FOR_FLUTTER / "frontend" / "flutter_dashboard"
    build_dir = flutter_root / "build" / "web"
    flutter_bin = shutil.which("flutter") or "/Users/appleuser/CS Work/flutter/bin/flutter"
    if not Path(flutter_bin).exists():
        pytest.skip(f"Flutter SDK not found at {flutter_bin}")

    index_html = build_dir / "index.html"
    if not index_html.exists():
        proc = subprocess.run(
            [flutter_bin, "build", "web", "--release"],
            cwd=str(flutter_root),
            capture_output=True, text=True, timeout=300,
        )
        if proc.returncode != 0 or not index_html.exists():
            pytest.skip(
                f"flutter build web failed (rc={proc.returncode}); "
                f"stderr tail: {proc.stderr[-500:]}"
            )
    return build_dir


@pytest.fixture
def flutter_static_server(flutter_web_build_dir):
    """Yields the URL of an http.server serving the Flutter web bundle.

    Function-scoped so each test gets a clean server (cheap; ~50ms boot).
    """
    port = _free_port_sync()
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=str(flutter_web_build_dir),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if not _wait_for_http_ok(port, 5.0):
            raise RuntimeError("flutter static server did not start")
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
