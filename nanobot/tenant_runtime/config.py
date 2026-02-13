"""Tenant runtime configuration from environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _is_true(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class TenantRuntimeConfig:
    """Config knobs for tenant runtime mode."""

    enabled: bool
    root_dir: Path
    max_global: int
    per_key_queue_limit: int
    task_timeout_s: int
    idle_ttl_s: int

    @classmethod
    def from_env(cls, default_root: Path) -> "TenantRuntimeConfig":
        return cls(
            enabled=_is_true(os.getenv("NANOBOT_TENANT_RUNTIME_ENABLED")),
            root_dir=Path(os.getenv("NANOBOT_TENANT_ROOT", str(default_root))).expanduser(),
            max_global=int(os.getenv("NANOBOT_TENANT_MAX_GLOBAL", "8")),
            per_key_queue_limit=int(os.getenv("NANOBOT_TENANT_PER_KEY_LIMIT", "50")),
            task_timeout_s=int(os.getenv("NANOBOT_TENANT_TASK_TIMEOUT_S", "60")),
            idle_ttl_s=int(os.getenv("NANOBOT_TENANT_IDLE_TTL_S", "300")),
        )
