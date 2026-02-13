"""Tenant-aware router for single-process multi-user isolation."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.cron.service import CronService
from nanobot.cron.types import CronJob
from nanobot.providers.base import LLMProvider
from nanobot.tenant_runtime.config import TenantRuntimeConfig
from nanobot.tenant_runtime.contracts import TenantContext
from nanobot.tenant_runtime.keying import build_isolation_key, build_runtime_key
from nanobot.tenant_runtime.path_resolver import TenantPathResolver
from nanobot.tenant_runtime.scheduler import PerKeyScheduler, SchedulerOverloadedError
from nanobot.tenant_runtime.session_repo import build_session_manager

if TYPE_CHECKING:
    from nanobot.config.schema import ExecToolConfig


@dataclass
class _TenantRuntimeState:
    """Runtime state for a single tenant/user/project bucket."""

    key: str
    context: TenantContext
    agent: AgentLoop
    cron: CronService
    last_used_s: float


class TenantRuntimeRouter:
    """Consumes bus inbound messages and routes them by tenant context."""

    def __init__(
        self,
        *,
        bus: MessageBus,
        provider: LLMProvider,
        model: str,
        max_iterations: int,
        brave_api_key: str | None,
        exec_config: "ExecToolConfig",
        restrict_to_workspace: bool,
        runtime_cfg: TenantRuntimeConfig,
    ):
        self.bus = bus
        self.provider = provider
        self.model = model
        self.max_iterations = max_iterations
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config
        self.restrict_to_workspace = restrict_to_workspace
        self.runtime_cfg = runtime_cfg
        self.resolver = TenantPathResolver(runtime_cfg.root_dir)
        self.scheduler = PerKeyScheduler(
            max_global=runtime_cfg.max_global,
            per_key_queue_limit=runtime_cfg.per_key_queue_limit,
            task_timeout_s=runtime_cfg.task_timeout_s,
            idle_ttl_s=runtime_cfg.idle_ttl_s,
        )
        self._runtimes: dict[str, _TenantRuntimeState] = {}
        self._runtime_lock = asyncio.Lock()
        self._running = False

    async def run(self) -> None:
        """Main router loop."""
        self._running = True
        logger.info("Tenant runtime router started")
        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
            except asyncio.TimeoutError:
                await self.scheduler.cleanup_idle_keys()
                continue

            ctx = TenantContext.from_inbound(msg)
            isolation_key = build_isolation_key(ctx)
            try:
                await self.scheduler.run(
                    isolation_key,
                    lambda: self._process_message(msg, ctx),
                )
            except SchedulerOverloadedError as exc:
                logger.warning(str(exc))
                await self.bus.publish_outbound(
                    OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content="System busy for this conversation, please retry shortly.",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(f"Tenant router failed to process message: {exc}")
                await self.bus.publish_outbound(
                    OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=f"Sorry, I encountered an error: {exc}",
                    )
                )

    async def stop(self) -> None:
        """Stop router and tenant runtimes."""
        self._running = False
        runtimes = list(self._runtimes.values())
        self._runtimes.clear()
        for runtime in runtimes:
            runtime.cron.stop()
            runtime.agent.stop()

    async def _process_message(self, msg: InboundMessage, ctx: TenantContext) -> None:
        runtime = await self._get_or_create_runtime(ctx)
        runtime.last_used_s = time.monotonic()

        response = await runtime.agent.process_direct(
            content=msg.content,
            session_key=msg.session_key,
            channel=msg.channel,
            chat_id=msg.chat_id,
            sender_id=msg.sender_id,
            metadata=msg.metadata,
            media=msg.media,
        )
        await self.bus.publish_outbound(
            OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=response,
                metadata=msg.metadata,
            )
        )

    async def _get_or_create_runtime(self, ctx: TenantContext) -> _TenantRuntimeState:
        runtime_key = build_runtime_key(ctx)
        async with self._runtime_lock:
            existing = self._runtimes.get(runtime_key)
            if existing:
                return existing

            workspace = self.resolver.workspace_dir(ctx)
            sessions = build_session_manager(ctx, self.resolver)
            cron = CronService(self.resolver.cron_store_path(ctx))

            agent = AgentLoop(
                bus=self.bus,
                provider=self.provider,
                workspace=workspace,
                model=self.model,
                max_iterations=self.max_iterations,
                brave_api_key=self.brave_api_key,
                exec_config=self.exec_config,
                cron_service=cron,
                restrict_to_workspace=self.restrict_to_workspace,
                session_manager=sessions,
            )

            async def on_cron_job(job: CronJob) -> str | None:
                result = await agent.process_direct(
                    content=job.payload.message,
                    session_key=f"cron:{ctx.project_id}:{job.id}",
                    channel=job.payload.channel or "cli",
                    chat_id=job.payload.to or "direct",
                    sender_id="cron",
                    metadata={
                        "tenant_id": ctx.tenant_id,
                        "user_id": ctx.user_id,
                        "project_id": ctx.project_id,
                    },
                )
                if job.payload.deliver and job.payload.to:
                    await self.bus.publish_outbound(
                        OutboundMessage(
                            channel=job.payload.channel or "cli",
                            chat_id=job.payload.to,
                            content=result or "",
                            metadata={
                                "tenant_id": ctx.tenant_id,
                                "user_id": ctx.user_id,
                                "project_id": ctx.project_id,
                            },
                        )
                    )
                return result

            cron.on_job = on_cron_job
            await cron.start()

            state = _TenantRuntimeState(
                key=runtime_key,
                context=ctx,
                agent=agent,
                cron=cron,
                last_used_s=time.monotonic(),
            )
            self._runtimes[runtime_key] = state
            logger.info(
                "Created tenant runtime: tenant={} user={} project={}",
                ctx.tenant_id,
                ctx.user_id,
                ctx.project_id,
            )
            return state
