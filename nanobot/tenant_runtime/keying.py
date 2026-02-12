"""Isolation key builders."""

from nanobot.tenant_runtime.contracts import TenantContext


def build_isolation_key(ctx: TenantContext) -> str:
    """Per-turn execution key (serial order guarantee)."""
    thread_id = ctx.thread_id or "main"
    return f"{ctx.tenant_id}:{ctx.user_id}:{ctx.channel}:{thread_id}"


def build_runtime_key(ctx: TenantContext) -> str:
    """Per-runtime key (agent/workspace/session bucket)."""
    return f"{ctx.tenant_id}:{ctx.user_id}"
