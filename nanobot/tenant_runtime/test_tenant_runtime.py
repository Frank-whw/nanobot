"""Runtime self-tests for tenant isolation primitives.

These tests are colocated with the extension module because repository-level
`tests/` is gitignored in this project.
"""

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.session.manager import SessionManager
from nanobot.tenant_runtime.contracts import TenantContext
from nanobot.tenant_runtime.keying import build_isolation_key, build_runtime_key
from nanobot.tenant_runtime.path_resolver import TenantPathResolver
from nanobot.tenant_runtime.scheduler import PerKeyScheduler


def test_inbound_message_session_key_override() -> None:
    msg = InboundMessage(
        channel="telegram",
        sender_id="u1",
        chat_id="chat1",
        content="hello",
        metadata={"session_key": "tenant:u1:thread-a"},
    )
    assert msg.session_key == "tenant:u1:thread-a"


def test_tenant_context_from_inbound() -> None:
    now = datetime.now()
    msg = InboundMessage(
        channel="web",
        sender_id="sender",
        chat_id="chat-1",
        content="x",
        timestamp=now,
        metadata={
            "tenantId": "tenant-a",
            "userId": "user-a",
            "projectId": "project-a",
            "threadId": "th-1",
            "requestId": "req-1",
        },
    )
    ctx = TenantContext.from_inbound(msg)
    assert ctx.tenant_id == "tenant-a"
    assert ctx.user_id == "user-a"
    assert ctx.project_id == "project-a"
    assert ctx.channel == "web"
    assert ctx.thread_id == "th-1"
    assert build_isolation_key(ctx) == "tenant-a:user-a:web:th-1"
    assert build_runtime_key(ctx) == "tenant-a:user-a"


@pytest.mark.asyncio
async def test_per_key_scheduler_serializes_same_key() -> None:
    scheduler = PerKeyScheduler(max_global=8, per_key_queue_limit=10, task_timeout_s=5)
    output: list[int] = []

    async def job(v: int) -> int:
        await asyncio.sleep(0.01)
        output.append(v)
        return v

    await asyncio.gather(
        scheduler.run("k1", lambda: job(1)),
        scheduler.run("k1", lambda: job(2)),
        scheduler.run("k1", lambda: job(3)),
    )

    assert output == [1, 2, 3]


def test_path_resolver_isolation(tmp_path: Path) -> None:
    resolver = TenantPathResolver(root=tmp_path)
    msg_a = InboundMessage(
        channel="web",
        sender_id="u1",
        chat_id="c1",
        content="x",
        metadata={"tenant_id": "t1", "user_id": "u1", "project_id": "p1"},
    )
    msg_b = InboundMessage(
        channel="web",
        sender_id="u2",
        chat_id="c2",
        content="x",
        metadata={"tenant_id": "t2", "user_id": "u2", "project_id": "p2"},
    )
    ctx_a = TenantContext.from_inbound(msg_a)
    ctx_b = TenantContext.from_inbound(msg_b)

    assert resolver.tenant_root(ctx_a).name == "t1"
    assert resolver.tenant_root(ctx_a).parent.name == "tenants"
    assert resolver.user_root(ctx_a).name == "users_u1"
    assert resolver.workspace_dir(ctx_a) != resolver.workspace_dir(ctx_b)
    assert resolver.sessions_dir(ctx_a) != resolver.sessions_dir(ctx_b)
    assert resolver.cron_store_path(ctx_a) != resolver.cron_store_path(ctx_b)


def test_session_manager_supports_custom_sessions_dir(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    sessions_dir = tmp_path / "sessions_a"
    mgr = SessionManager(workspace=workspace, sessions_dir=sessions_dir)
    session = mgr.get_or_create("web:chat-1")
    session.add_message("user", "hello")
    mgr.save(session)

    files = list(sessions_dir.glob("*.jsonl"))
    assert len(files) == 1
