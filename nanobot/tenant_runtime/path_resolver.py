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
        return ensure_dir(self.root / safe_filename(ctx.tenant_id))

    def user_root(self, ctx: TenantContext) -> Path:
        return ensure_dir(self.tenant_root(ctx) / "users" / safe_filename(ctx.user_id))

    def project_root(self, ctx: TenantContext) -> Path:
        return ensure_dir(self.user_root(ctx) / "projects" / safe_filename(ctx.project_id))

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
