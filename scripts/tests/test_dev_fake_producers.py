"""Tests for dev_fake_producers.py CLI surface and emission gating.

We avoid spinning up Redis: ``_run`` is bypassed entirely by patching
``redis.Redis.from_url`` to a Mock that records ``publish`` calls.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts import dev_fake_producers as dfp  # noqa: E402


def test_parser_default_emits_all_channels():
    args = dfp._parse_args([])
    assert args.emit == ["state", "egs", "findings"]


def test_parser_emit_csv_subset():
    args = dfp._parse_args(["--emit", "egs,findings"])
    assert args.emit == ["egs", "findings"]


def test_parser_emit_rejects_unknown_token():
    with pytest.raises(SystemExit):
        dfp._parse_args(["--emit", "egs,bogus"])


def _stub_args(**overrides):
    """Build a SimpleNamespace mimicking argparse output for _run."""
    import types
    base = dict(
        redis_url="redis://localhost:6379",
        drone_id="drone1",
        tick_s=0.0,           # zero-sleep so the test never actually sleeps
        no_validate=False,
        emit=["state", "egs", "findings"],
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


def _channels_published(mock_client) -> list[str]:
    return [call.args[0] for call in mock_client.publish.call_args_list]


@patch("scripts.dev_fake_producers.time.sleep", side_effect=KeyboardInterrupt)
@patch("scripts.dev_fake_producers.redis.Redis.from_url")
def test_run_default_publishes_all_three_channels(mock_from_url, _mock_sleep):
    client = MagicMock()
    mock_from_url.return_value = client
    rc = dfp._run(_stub_args())
    assert rc == 0
    channels = _channels_published(client)
    # First tick (tick=0): state + egs + findings (8|0 and 2|0).
    assert "drones.drone1.state" in channels
    assert "egs.state" in channels
    assert "drones.drone1.findings" in channels


@patch("scripts.dev_fake_producers.time.sleep", side_effect=KeyboardInterrupt)
@patch("scripts.dev_fake_producers.redis.Redis.from_url")
def test_run_emit_findings_only_skips_state_and_egs(mock_from_url, _mock_sleep):
    client = MagicMock()
    mock_from_url.return_value = client
    rc = dfp._run(_stub_args(emit=["findings"]))
    assert rc == 0
    channels = _channels_published(client)
    assert "drones.drone1.findings" in channels
    assert "drones.drone1.state" not in channels
    assert "egs.state" not in channels


@patch("scripts.dev_fake_producers.time.sleep", side_effect=KeyboardInterrupt)
@patch("scripts.dev_fake_producers.redis.Redis.from_url")
def test_run_emit_egs_only_skips_drone_channels(mock_from_url, _mock_sleep):
    client = MagicMock()
    mock_from_url.return_value = client
    rc = dfp._run(_stub_args(emit=["egs"]))
    assert rc == 0
    channels = _channels_published(client)
    assert channels == ["egs.state"]


@patch("scripts.dev_fake_producers.time.sleep", side_effect=KeyboardInterrupt)
@patch("scripts.dev_fake_producers.redis.Redis.from_url")
def test_run_emit_egs_and_findings_is_the_hybrid_mode(mock_from_url, _mock_sleep):
    """The actual mode the orchestrator runs: fakes own egs + findings, real
    sim owns drones.<id>.state. This is the contract the cutover depends on."""
    client = MagicMock()
    mock_from_url.return_value = client
    rc = dfp._run(_stub_args(emit=["egs", "findings"]))
    assert rc == 0
    channels = _channels_published(client)
    assert "egs.state" in channels
    assert "drones.drone1.findings" in channels
    assert "drones.drone1.state" not in channels, (
        "hybrid mode must NOT emit drone state (sim owns that channel)"
    )
