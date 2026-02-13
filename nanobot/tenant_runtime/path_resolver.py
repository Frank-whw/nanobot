"""Tenant path resolver."""

from __future__ import annotations

from pathlib import Path

from nanobot.tenant_runtime.contracts import TenantContext
from nanobot.utils.helpers import ensure_dir, safe_filename


class TenantPathResolver:
    """Resolve isolated storage paths for a tenant context."""

    def __init__(self, root: Path):
        self.root = ensure_dir(root)

    def tenant_root(self, ctx: TenantContext) -> Path:
        tenant = safe_filename(ctx.tenant_id)
        return ensure_dir(self.root / "tenants" / tenant)

    def user_root(self, ctx: TenantContext) -> Path:
        user = safe_filename(ctx.user_id)
        return ensure_dir(self.tenant_root(ctx) / f"users_{user}")

    def project_root(self, ctx: TenantContext) -> Path:
        # Keep method for compatibility; storage layout no longer nests by project.
        return self.user_root(ctx)

    def workspace_dir(self, ctx: TenantContext) -> Path:
        return ensure_dir(self.project_root(ctx) / "workspace")

    def sessions_dir(self, ctx: TenantContext) -> Path:
        return ensure_dir(self.project_root(ctx) / "sessions")

    def cron_store_path(self, ctx: TenantContext) -> Path:
        cron_dir = ensure_dir(self.project_root(ctx) / "cron")
        return cron_dir / "jobs.json"

    def memory_dir(self, ctx: TenantContext) -> Path:
        return ensure_dir(self.workspace_dir(ctx) / "memory")

    def logs_dir(self, ctx: TenantContext) -> Path:
        return ensure_dir(self.project_root(ctx) / "logs")
