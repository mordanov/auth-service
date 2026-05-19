"""Sliding window rate limiter using Redis."""
from __future__ import annotations

import time
from typing import Callable

import redis.asyncio as aioredis
from fastapi import HTTPException, Request, status

from src.config import settings

_redis_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


async def close_redis() -> None:
    """Close the shared Redis client if it was initialized."""
    global _redis_client
    if _redis_client is None:
        return
    await _redis_client.aclose(close_connection_pool=True)
    _redis_client = None


async def check_rate_limit(key: str, max_requests: int, window_seconds: int = 60) -> None:
    """Sliding window rate limit. Raises HTTP 429 if limit exceeded."""
    r = get_redis()
    now = time.time()
    window_start = now - window_seconds

    async with r.pipeline() as pipe:
        pipe.zremrangebyscore(key, "-inf", window_start)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, window_seconds)
        results = await pipe.execute()
    count = results[2]

    if count > max_requests:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": "rate_limited", "message": "Too many requests. Try again later."},
            headers={"Retry-After": str(window_seconds)},
        )
