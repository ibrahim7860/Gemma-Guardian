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
