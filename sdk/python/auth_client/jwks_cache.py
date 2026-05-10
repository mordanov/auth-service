"""JWKS public key cache with 5-minute TTL and kid-based rotation.

Thread-safe: a threading.Lock prevents concurrent fetch storms in multi-threaded
WSGI environments (e.g. gunicorn with sync workers).
"""
from __future__ import annotations

import threading
import time
from typing import Any

import httpx

_cache: dict[str, Any] = {}  # kid → public key object
_cache_fetched_at: float = 0.0
_CACHE_TTL = 300  # 5 minutes
_lock = threading.Lock()


def _fetch_keys(jwks_url: str) -> dict[str, Any]:
    """Fetch and parse JWKS, return dict of kid → JWK dict."""
    resp = httpx.get(jwks_url, timeout=5.0)
    resp.raise_for_status()
    data = resp.json()
    return {key["kid"]: key for key in data.get("keys", [])}


def get_key(jwks_url: str, kid: str) -> Any:
    """Return the public key for the given kid, fetching JWKS if needed.

    Refreshes if the cache is stale (> 5 min) or if kid is not found.
    Raises InvalidTokenError if the kid is still not found after a fresh fetch.
    Thread-safe via module-level lock.
    """
    from auth_client.exceptions import InvalidTokenError

    global _cache, _cache_fetched_at

    # Fast path: check without locking first (read-only, safe for the check)
    if kid in _cache and (time.monotonic() - _cache_fetched_at) < _CACHE_TTL:
        return _cache[kid]

    # Slow path: acquire lock and refresh
    with _lock:
        # Re-check inside lock — another thread may have refreshed already
        if kid in _cache and (time.monotonic() - _cache_fetched_at) < _CACHE_TTL:
            return _cache[kid]

        _cache = _fetch_keys(jwks_url)
        _cache_fetched_at = time.monotonic()

    if kid not in _cache:
        raise InvalidTokenError(f"Unknown key ID: {kid}")

    return _cache[kid]


def invalidate() -> None:
    """Force cache invalidation (useful in tests)."""
    global _cache, _cache_fetched_at
    with _lock:
        _cache = {}
        _cache_fetched_at = 0.0
