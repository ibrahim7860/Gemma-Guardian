"""Phase 2 bridge configuration loaded from environment.

Single source of truth for tunables. Constructed once at app startup
inside the FastAPI lifespan; never mutated.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class BridgeConfig:
    redis_url: str
    tick_s: float
    max_findings: int
    reconnect_max_s: float
    broadcast_timeout_s: float

    @classmethod
    def from_env(cls) -> "BridgeConfig":
        return cls(
            redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379"),
            tick_s=float(os.environ.get("BRIDGE_TICK_S", "1.0")),
            max_findings=int(os.environ.get("BRIDGE_MAX_FINDINGS", "50")),
            reconnect_max_s=float(os.environ.get("BRIDGE_RECONNECT_MAX_S", "10")),
            broadcast_timeout_s=float(os.environ.get("BRIDGE_BROADCAST_TIMEOUT_S", "0.5")),
        )
