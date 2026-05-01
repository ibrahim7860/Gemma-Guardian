"""Typed loader for shared/config.yaml.

Aborts startup with a clear error if contract_version drifts from
shared/VERSION. Exposes a CONFIG singleton.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from . import VERSION

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config.yaml"


class _MissionCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    drone_count: int = Field(ge=1)
    scenario_id: str = Field(min_length=1)


class _TransportCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    redis_url: str = Field(pattern=r"^redis(s)?://")
    channel_prefix: str = ""


class _FunctionCallPathCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    egs: Literal["native_tools", "structured_output"]
    drone: Literal["native_tools", "structured_output"]
    fallback: Literal["native_tools", "structured_output"]


class _InferenceCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    drone_model: str
    egs_model: str
    drone_sampling_hz: float = Field(gt=0)
    ollama_drone_endpoint: str
    ollama_egs_endpoint: str
    function_call_path: _FunctionCallPathCfg


class _MeshCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    range_meters: int = Field(ge=1)
    egs_link_range_meters: int = Field(ge=1)
    heartbeat_timeout_seconds: int = Field(ge=1)


class _ValidationCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_retries: int = Field(ge=0, le=10)


class _LoggingCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_dir: str
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class FieldAgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: str
    mission: _MissionCfg
    transport: _TransportCfg
    inference: _InferenceCfg
    mesh: _MeshCfg
    validation: _ValidationCfg
    logging: _LoggingCfg


def load_config(path: Path = CONFIG_PATH) -> FieldAgentConfig:
    raw = yaml.safe_load(path.read_text())
    cfg = FieldAgentConfig(**raw)
    if cfg.contract_version != VERSION:
        raise RuntimeError(
            f"config.yaml contract_version={cfg.contract_version!r} disagrees with "
            f"shared/VERSION={VERSION!r}. Bump both together."
        )
    return cfg


@lru_cache(maxsize=1)
def _default() -> FieldAgentConfig:
    return load_config()


CONFIG: FieldAgentConfig = _default()
