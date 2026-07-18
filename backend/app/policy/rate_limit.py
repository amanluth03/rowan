"""Minimal in-process rate limiter for public endpoints (CLAUDE.md:
"rate-limit all public endpoints" — security-reviewer blocking finding,
2026-07-18).

# ASSUMPTION: an in-memory fixed-window-ish (sliding log) limiter is
sufficient for v1's single-instance deployment (ADR 0003: "a modular
monolith... not separate services"). It does NOT share state across
multiple app instances/processes — a real multi-instance production
deployment needs a shared store (e.g. Upstash Redis, already available on
the Vercel Marketplace per the project's stack) instead of this. Flagged
as a follow-up, not fixed here, to stay in scope for this pass.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, *, max_requests: int, window_seconds: float) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def allow(self, key: str) -> bool:
        """Returns True if the request is allowed, False if rate-limited.
        Records the hit only when allowing it (rejected attempts don't
        consume budget for a subsequent legitimate retry after backoff)."""
        now = time.monotonic()
        async with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window_seconds:
                hits.popleft()
            if len(hits) >= self.max_requests:
                return False
            hits.append(now)
            return True
