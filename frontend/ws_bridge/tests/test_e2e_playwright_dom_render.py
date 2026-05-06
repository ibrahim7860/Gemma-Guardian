"""Playwright e2e: agent → bridge → Flutter dashboard DOM (semantics tree).

Closes Gap #1's last hop. Builds on test_e2e_playwright_real_drone_findings.py
but adds the final assertion: the finding renders into the Flutter dashboard's
semantics tree, queryable via Chromium's accessibility tree.

Why semantics tree (not visible DOM): Flutter 3.41 web ships only CanvasKit,
which paints to <canvas>. Text content lives in the accessibility/semantics
overlay — Flutter's own equivalent of an ARIA tree, exposed as real
<flt-semantics> elements with `flt-semantics-identifier` attributes.
The dashboard auto-enables semantics on web at boot via
SemanticsBinding.instance.ensureSemantics() in main.dart, so the tree is
live from page load — no Tab keypress needed.

This test uses the OLLAMA MOCK for determinism. Real-Gemma e2e is covered by
test_e2e_playwright_real_drone_findings.py.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_for_port(port: int, deadline_s: float) -> bool:
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


@contextmanager
def _spawn(cmd: list[str], env: dict | None = None, name: str = "child"):
    proc = subprocess.Popen(
        cmd, cwd=str(REPO_ROOT),
        env={**os.environ, **(env or {})},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.mark.timeout(180)
def test_finding_renders_in_flutter_semantics_tree(tmp_path, flutter_static_server):
    if not shutil.which("redis-server"):
        pytest.skip("redis-server not on PATH")
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        pytest.skip("playwright not installed")

    redis_port = _free_port()
    ollama_port = _free_port()
    bridge_port = _free_port()

    redis_proc = subprocess.Popen(
        ["redis-server", "--port", str(redis_port), "--save", "", "--appendonly", "no"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    assert _wait_for_port(redis_port, 5), "redis did not come up"
    redis_url = f"redis://127.0.0.1:{redis_port}/0"
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    try:
        with _spawn(
            [sys.executable, "scripts/ollama_mock_server.py", "--port", str(ollama_port)],
            name="ollama-mock",
        ):
            assert _wait_for_port(ollama_port, 5), "ollama mock did not come up"

            scenario = "disaster_zone_v1"
            with _spawn(
                [sys.executable, "-m", "sim.waypoint_runner",
                 "--scenario", scenario, "--redis-url", redis_url],
                name="waypoint",
            ), _spawn(
                [sys.executable, "-m", "sim.frame_server",
                 "--scenario", scenario, "--redis-url", redis_url],
                name="frame",
            ), _spawn(
                [sys.executable, "-m", "agents.drone_agent",
                 "--drone-id", "drone1", "--scenario", scenario,
                 "--redis-url", redis_url,
                 "--ollama-endpoint", f"http://127.0.0.1:{ollama_port}"],
                env={"GG_LOG_DIR": str(log_dir)},
                name="drone-agent",
            ), _spawn(
                [sys.executable, "-m", "uvicorn", "frontend.ws_bridge.main:app",
                 "--host", "127.0.0.1", "--port", str(bridge_port)],
                env={"REDIS_URL": redis_url},
                name="bridge",
            ):
                assert _wait_for_port(bridge_port, 10), "bridge did not come up"

                # Capture the victim finding_id off Redis. The mock Ollama
                # makes the FIRST tool call a report_finding, so this is
                # bounded by the agent's first step latency (≤ a few seconds).
                import redis as _redis
                client = _redis.Redis.from_url(redis_url)
                pubsub = client.pubsub()
                pubsub.subscribe("drones.drone1.findings")
                pubsub.get_message(timeout=1)  # consume subscribe ack
                deadline = time.time() + 60
                victim_finding_id = None
                while time.time() < deadline:
                    msg = pubsub.get_message(timeout=1)
                    if msg and msg["type"] == "message":
                        payload = json.loads(msg["data"])
                        if payload.get("type") == "victim":
                            victim_finding_id = payload["finding_id"]
                            break
                pubsub.close()
                client.close()
                assert victim_finding_id, "no victim finding observed within 60s"

                # Drive Chromium against the patched dashboard.
                ws_url = f"ws://127.0.0.1:{bridge_port}/"
                dashboard_url = (
                    f"{flutter_static_server}/?ws={ws_url}"
                )

                from playwright.sync_api import sync_playwright

                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    context = browser.new_context()
                    page = context.new_page()
                    console_msgs: list[str] = []
                    page.on("console", lambda m: console_msgs.append(f"[{m.type}] {m.text}"))
                    page.goto(dashboard_url, wait_until="networkidle", timeout=30_000)

                    # Semantics auto-enabled by main.dart's
                    # SemanticsBinding.instance.ensureSemantics() — no Tab needed.
                    # Poll for our identifier in the semantics tree.
                    target_selector = (
                        f'[flt-semantics-identifier="finding-tile-{victim_finding_id}"]'
                    )
                    try:
                        page.wait_for_selector(target_selector, timeout=30_000,
                                               state="attached")
                    except Exception as e:
                        # Diagnostic dump to make failures actionable.
                        body_len = page.evaluate("document.body.outerHTML.length")
                        sem_sample = page.evaluate(
                            "Array.from(document.querySelectorAll("
                            "'flt-semantics, [flt-semantics-identifier], [id^=\"flt-semantic\"]'"
                            ")).slice(0,15).map(e => e.outerHTML.slice(0, 200))"
                        )
                        raise AssertionError(
                            f"selector {target_selector!r} not attached. "
                            f"body length={body_len}, "
                            f"semantics sample={sem_sample!r}, "
                            f"console tail={console_msgs[-15:]!r}"
                        ) from e

                    # Sanity: the accessible name should encode the finding type.
                    el = page.locator(target_selector).first
                    aria_label = el.get_attribute("aria-label") or ""
                    assert "VICTIM" in aria_label.upper(), (
                        f"semantics label missing VICTIM marker: {aria_label!r}"
                    )

                    browser.close()

    finally:
        redis_proc.terminate()
        try:
            redis_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            redis_proc.kill()
