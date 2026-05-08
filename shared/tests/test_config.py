"""Config loader: defaults + drift detection."""
from __future__ import annotations

import pytest
import yaml

from shared.contracts import VERSION, load_config
from shared.contracts.config import CONFIG_PATH


def test_default_config_loads():
    cfg = load_config()
    assert cfg.contract_version == VERSION
    assert cfg.mission.drone_count >= 1
    assert cfg.transport.redis_url.startswith("redis://")
    assert cfg.inference.function_call_path.drone in ("native_tools", "structured_output")
    assert cfg.mesh.range_meters > 0
    assert cfg.validation.max_retries >= 0
    assert cfg.logging.level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def test_drift_detected(tmp_path):
    bad = yaml.safe_load(CONFIG_PATH.read_text())
    bad["contract_version"] = "9.9.9"
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(bad))
    with pytest.raises(RuntimeError, match="contract_version"):
        load_config(p)


def test_invalid_redis_url_rejected(tmp_path):
    bad = yaml.safe_load(CONFIG_PATH.read_text())
    bad["transport"]["redis_url"] = "http://localhost:6379"
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(bad))
    with pytest.raises(Exception):  # pydantic ValidationError
        load_config(p)


def test_extra_field_rejected(tmp_path):
    bad = yaml.safe_load(CONFIG_PATH.read_text())
    bad["surprise"] = "no"
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(bad))
    with pytest.raises(Exception):
        load_config(p)


def test_redis_url_env_override(monkeypatch):
    """REDIS_URL env override beats whatever YAML says.

    Closes a runbook footgun: ephemeral test stacks (pytest fixtures,
    Capture-3 of the demo recapture runbook) need to point agents at a
    private `redis-server` on a free port. Without this override, the
    EGS hardcodes `redis://localhost:6379/0` from shared/config.yaml and
    silently lands on the wrong broker — producers/consumers split,
    `egs.state` never reaches the bridge, demo dies. Discovered during
    the 2026-05-08 demo recapture (docs/plans/2026-05-08-demo-recapture.md).
    """
    monkeypatch.setenv("REDIS_URL", "redis://test-host:1234/3")
    cfg = load_config()
    assert cfg.transport.redis_url == "redis://test-host:1234/3"


def test_redis_url_env_override_validated(monkeypatch):
    """Bad override hits the same ^redis(s)?:// guard the YAML does.

    Critical: env overrides bypassing validation would mean a typo
    (REDIS_URL=redis//... missing a colon, or http://...) corrupts the
    config silently and explodes deep inside an asyncio reconnect loop.
    Re-route the override through Pydantic so the failure is loud and
    early."""
    monkeypatch.setenv("REDIS_URL", "http://not-redis:6379")
    with pytest.raises(Exception):  # pydantic ValidationError
        load_config()


def test_redis_url_env_override_empty_string_ignored(monkeypatch):
    """Setting REDIS_URL='' should NOT override (no override is implied).

    A common shell footgun: `unset REDIS_URL` and `REDIS_URL=` look
    the same to the user but only the former clears the env. Treat
    empty as absent so a stray `REDIS_URL=` in a launcher script
    doesn't fail the pattern check."""
    monkeypatch.setenv("REDIS_URL", "")
    cfg = load_config()
    assert cfg.transport.redis_url.startswith("redis://")


def test_redis_url_env_unset_uses_yaml(monkeypatch):
    """Without the env var, the YAML value is unchanged."""
    monkeypatch.delenv("REDIS_URL", raising=False)
    cfg = load_config()
    yaml_value = yaml.safe_load(CONFIG_PATH.read_text())["transport"]["redis_url"]
    assert cfg.transport.redis_url == yaml_value
