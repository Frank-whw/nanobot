"""Tenant session repository helpers."""

from nanobot.session.manager import SessionManager
from nanobot.tenant_runtime.contracts import TenantContext
from nanobot.tenant_runtime.path_resolver import TenantPathResolver


def build_session_manager(ctx: TenantContext, resolver: TenantPathResolver) -> SessionManager:
    """Build a SessionManager bound to tenant-specific sessions directory."""
    workspace = resolver.workspace_dir(ctx)
    sessions_dir = resolver.sessions_dir(ctx)
    return SessionManager(workspace=workspace, sessions_dir=sessions_dir)
