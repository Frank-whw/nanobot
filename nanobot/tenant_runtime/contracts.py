"""Contracts for tenant-aware ingress and routing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from nanobot.bus.events import InboundMessage


def _pick_str(data: dict[str, Any], *keys: str) -> str | None:
    """Pick the first non-empty string value from candidate keys."""
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


@dataclass(frozen=True)
class TenantIngress:
    """Validated ingress envelope for a single turn."""

    tenant_id: str
    user_id: str
    project_id: str
    channel: str
    thread_id: str
    message: str
    request_id: str
    timestamp: datetime
    metadata: dict[str, Any]
    media: list[str]


@dataclass(frozen=True)
class TenantContext:
    """Canonical tenant context used by runtime routing/storage."""

    tenant_id: str
    user_id: str
    project_id: str
    channel: str
    thread_id: str
    request_id: str
    timestamp: datetime

    @classmethod
    def from_inbound(cls, msg: InboundMessage) -> "TenantContext":
        """Build context from inbound metadata with safe defaults."""
        metadata = msg.metadata or {}
        tenant_id = _pick_str(metadata, "tenant_id", "tenantId") or "default"
        user_id = _pick_str(metadata, "user_id", "userId") or str(msg.sender_id)
        project_id = _pick_str(metadata, "project_id", "projectId") or "default"
        thread_id = (
            _pick_str(metadata, "thread_id", "threadId")
            or str(msg.chat_id)
            or "main"
        )
        request_id = _pick_str(metadata, "request_id", "requestId") or ""
        timestamp = metadata.get("timestamp")
        if isinstance(timestamp, str):
            try:
                ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                ts = msg.timestamp
        elif isinstance(timestamp, datetime):
            ts = timestamp
        else:
            ts = msg.timestamp

        return cls(
            tenant_id=tenant_id,
            user_id=user_id,
            project_id=project_id,
            channel=msg.channel,
            thread_id=thread_id,
            request_id=request_id,
            timestamp=ts,
        )

    def session_key(self) -> str:
        """Return a stable session key namespace for this context."""
        return f"{self.channel}:{self.thread_id}"
