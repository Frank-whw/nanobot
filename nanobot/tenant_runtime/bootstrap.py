"""Bootstrap helpers for tenant runtime mode."""

from pathlib import Path

from nanobot.tenant_runtime.config import TenantRuntimeConfig
from nanobot.tenant_runtime.router import TenantRuntimeRouter


def build_tenant_router_if_enabled(
    *,
    bus,
    provider,
    model: str,
    max_iterations: int,
    brave_api_key: str | None,
    exec_config,
    restrict_to_workspace: bool,
    default_data_dir: Path,
) -> TenantRuntimeRouter | None:
    """Build tenant router when extension flag is enabled."""
    cfg = TenantRuntimeConfig.from_env(default_root=default_data_dir)
    if not cfg.enabled:
        return None
    return TenantRuntimeRouter(
        bus=bus,
        provider=provider,
        model=model,
        max_iterations=max_iterations,
        brave_api_key=brave_api_key,
        exec_config=exec_config,
        restrict_to_workspace=restrict_to_workspace,
        runtime_cfg=cfg,
    )
