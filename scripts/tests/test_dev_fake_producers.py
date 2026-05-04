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
