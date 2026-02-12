"""Per-key serial scheduler with global concurrency guard."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


class SchedulerOverloadedError(RuntimeError):
    """Raised when queue limits are exceeded."""


class PerKeyScheduler:
    """Serialize jobs by key while enforcing a global concurrency limit."""

    def __init__(
        self,
        max_global: int = 8,
        per_key_queue_limit: int = 50,
        task_timeout_s: int = 60,
        idle_ttl_s: int = 300,
    ):
        self._global = asyncio.Semaphore(max_global)
        self._per_key_locks: dict[str, asyncio.Lock] = {}
        self._pending_by_key: dict[str, int] = defaultdict(int)
        self._last_used: dict[str, float] = {}
        self._guard = asyncio.Lock()
        self.per_key_queue_limit = per_key_queue_limit
        self.task_timeout_s = task_timeout_s
        self.idle_ttl_s = idle_ttl_s

    async def run(self, key: str, job: Callable[[], Awaitable[T]]) -> T:
        """Run a job serialized by key and bounded by global semaphore."""
        lock = await self._reserve_key(key)
        try:
            async with lock:
                async with self._global:
                    return await asyncio.wait_for(job(), timeout=self.task_timeout_s)
        finally:
            await self._release_key(key)

    async def cleanup_idle_keys(self) -> None:
        """Drop idle key state to avoid unbounded dict growth."""
        now = time.monotonic()
        async with self._guard:
            stale = [
                key
                for key, ts in self._last_used.items()
                if now - ts > self.idle_ttl_s and self._pending_by_key.get(key, 0) == 0
            ]
            for key in stale:
                self._last_used.pop(key, None)
                self._pending_by_key.pop(key, None)
                self._per_key_locks.pop(key, None)

    async def _reserve_key(self, key: str) -> asyncio.Lock:
        async with self._guard:
            pending = self._pending_by_key[key]
            if pending >= self.per_key_queue_limit:
                raise SchedulerOverloadedError(
                    f"Queue overflow for key={key} (limit={self.per_key_queue_limit})"
                )
            self._pending_by_key[key] = pending + 1
            self._last_used[key] = time.monotonic()
            lock = self._per_key_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._per_key_locks[key] = lock
            return lock

    async def _release_key(self, key: str) -> None:
        async with self._guard:
            pending = self._pending_by_key.get(key, 0)
            if pending <= 1:
                self._pending_by_key[key] = 0
            else:
                self._pending_by_key[key] = pending - 1
            self._last_used[key] = time.monotonic()
