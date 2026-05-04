"""
Pluggable HTTP rate limiters (sliding-window style ``is_limited`` contract).

Production scaling
------------------
**In-memory is NOT safe for multi-instance deployments.** Each process keeps its own
counters, so:

- Effective limits **multiply** by worker/replica count (each instance allows its own quota).
- Clients can **spread** requests across instances and exceed the intended global rate.

**Use Redis (or another shared store) in production** when you run more than one
process that handles HTTP traffic—e.g. multiple Uvicorn workers, Kubernetes replicas,
or autoscaling. Typical patterns: Redis with ``INCR``/``EXPIRE``, a sliding-window Lua
script, or rate limiting at an API gateway / edge instead of in-app.

This module defines a small ``RateLimiter`` protocol. The default implementation is
process-local only; ``RedisRateLimiter`` is a **placeholder** until a real Redis-backed
implementation is wired via ``setup_rate_limiter(app, backend=...)``.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class RateLimiter(Protocol):
    """Sliding-window rate limit check; swap implementations without changing middleware."""

    def is_limited(self, key: str, limit: int, window_seconds: int) -> bool:
        """
        Record this request attempt and return whether the key is over limit.

        Returns:
            True if the caller should reject the request (429).
            False if the request is allowed.
        """
        ...


class InMemoryRateLimiter:
    """
    Default: process-local sliding-window limiter.

    **NOT safe for production at scale** when more than one app process handles
    traffic—see module docstring. Suitable for development, single-worker setups,
    or as a fallback when no shared store is configured.
    """

    def __init__(self) -> None:
        self._request_counts: dict[str, list[float]] = defaultdict(list)

    def is_limited(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.time()
        window_start = now - window_seconds
        bucket = self._request_counts[key]
        self._request_counts[key] = [t for t in bucket if t > window_start]
        if len(self._request_counts[key]) >= limit:
            return True
        self._request_counts[key].append(now)
        return False


class RedisRateLimiter:
    """
    Placeholder for a Redis-backed rate limiter (not implemented).

    Intended wiring: ``redis.asyncio`` (or sync Redis behind ``asyncio.to_thread``),
    keys derived from ``key`` (e.g. ``f"rl:{key}"``), sliding window via sorted sets
    or Lua, and inject with ``setup_rate_limiter(app, backend=RedisRateLimiter(...))``.

    **Do not use in production until implemented**—``is_limited`` always raises.
    """

    def __init__(self, redis_url: Optional[str] = None) -> None:
        self._redis_url = redis_url

    def is_limited(self, key: str, limit: int, window_seconds: int) -> bool:
        raise NotImplementedError(
            "RedisRateLimiter is a placeholder. Implement Redis-backed counting and "
            "pass an instance to setup_rate_limiter(app, backend=...). "
            "Use InMemoryRateLimiter only for single-process / dev workloads."
        )


# Backwards-compatible names (older imports / docs).
RateLimiterBackend = RateLimiter
InMemoryRateLimiterBackend = InMemoryRateLimiter

__all__ = [
    "RateLimiter",
    "InMemoryRateLimiter",
    "RedisRateLimiter",
    "RateLimiterBackend",
    "InMemoryRateLimiterBackend",
]
