"""Tenant cron repository helpers."""

from collections.abc import Awaitable, Callable

from nanobot.cron.service import CronService
from nanobot.cron.types import CronJob
from nanobot.tenant_runtime.contracts import TenantContext
from nanobot.tenant_runtime.path_resolver import TenantPathResolver


def build_cron_service(
    ctx: TenantContext,
    resolver: TenantPathResolver,
    on_job: Callable[[CronJob], Awaitable[str | None]] | None = None,
) -> CronService:
    """Build cron service with isolated store path."""
    return CronService(store_path=resolver.cron_store_path(ctx), on_job=on_job)
