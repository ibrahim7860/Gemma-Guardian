"""CLI argument parsing for python -m agents.drone_agent."""
from __future__ import annotations

import pytest

from agents.drone_agent.__main__ import build_parser


def test_drone_id_required():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_defaults():
    parser = build_parser()
    args = parser.parse_args(["--drone-id", "drone1"])
    assert args.drone_id == "drone1"
    assert args.scenario == "disaster_zone_v1"
    assert args.redis_url.startswith("redis://")
    assert args.model
    assert args.ollama_endpoint
    assert args.max_retries >= 1
    assert args.zone_buffer_m >= 0


def test_explicit_overrides():
    parser = build_parser()
    args = parser.parse_args([
        "--drone-id", "drone2",
        "--scenario", "single_drone_smoke",
        "--redis-url", "redis://example:6379/2",
        "--model", "gemma4:e4b",
        "--ollama-endpoint", "http://10.0.0.5:11434",
        "--max-retries", "5",
        "--zone-buffer-m", "200",
    ])
    assert args.drone_id == "drone2"
    assert args.scenario == "single_drone_smoke"
    assert args.redis_url == "redis://example:6379/2"
    assert args.model == "gemma4:e4b"
    assert args.ollama_endpoint == "http://10.0.0.5:11434"
    assert args.max_retries == 5
    assert args.zone_buffer_m == 200.0
