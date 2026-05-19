"""OAuth 2.0 / OIDC service for Google and Microsoft providers."""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
from urllib.parse import urlencode

import httpx
import redis.asyncio as aioredis

from src.config import settings

_DISCOVERY_URLS: dict[str, str] = {
    "google": "https://accounts.google.com/.well-known/openid-configuration",
    "microsoft": (
        f"https://login.microsoftonline.com/{settings.microsoft_tenant_id}"
        "/v2.0/.well-known/openid-configuration"
    ),
}

_PROVIDER_CLIENT_IDS: dict[str, str] = {
    "google": settings.google_client_id,
    "microsoft": settings.microsoft_client_id,
}
_PROVIDER_CLIENT_SECRETS: dict[str, str] = {
    "google": settings.google_client_secret,
    "microsoft": settings.microsoft_client_secret,
}

_STATE_PREFIX = "oauth_state:"
_STATE_TTL = 600  # 10 minutes


def _get_redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


def _get_redirect_uri(provider: str) -> str:
    return f"{settings.app_base_url}/auth/callback/{provider}"


async def _fetch_oidc_metadata(provider: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(_DISCOVERY_URLS[provider], timeout=10)
        resp.raise_for_status()
        return resp.json()


def _pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for S256."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


async def get_authorization_url(provider: str, redirect_after: str | None = None) -> str:
    """Build the provider authorisation URL with PKCE + state.

    Stores state → {code_verifier, redirect_after} in Redis.
    """
    if provider not in _DISCOVERY_URLS:
        raise ValueError(f"Unknown provider: {provider}")

    metadata = await _fetch_oidc_metadata(provider)

    state = secrets.token_urlsafe(32)
    code_verifier, code_challenge = _pkce_pair()

    r = _get_redis()
    payload = json.dumps({"code_verifier": code_verifier, "redirect_after": redirect_after or ""})
    await r.setex(f"{_STATE_PREFIX}{state}", _STATE_TTL, payload)
    await r.aclose(close_connection_pool=True)

    params = {
        "client_id": _PROVIDER_CLIENT_IDS[provider],
        "response_type": "code",
        "redirect_uri": _get_redirect_uri(provider),
        "scope": "openid email profile",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return metadata["authorization_endpoint"] + "?" + urlencode(params)


async def exchange_code(provider: str, code: str, state: str) -> dict:
    """Exchange authorisation code → user info dict.

    Validates state, exchanges code with PKCE, calls userinfo endpoint.
    Returns dict with keys: sub, email, name, redirect_after.
    """
    if provider not in _DISCOVERY_URLS:
        raise ValueError(f"Unknown provider: {provider}")

    # Retrieve + delete state from Redis (one-time use)
    r = _get_redis()
    raw = await r.get(f"{_STATE_PREFIX}{state}")
    if not raw:
        await r.aclose(close_connection_pool=True)
        raise ValueError("Invalid or expired OAuth state")
    await r.delete(f"{_STATE_PREFIX}{state}")
    await r.aclose(close_connection_pool=True)

    state_data = json.loads(raw)
    code_verifier: str = state_data["code_verifier"]
    redirect_after: str = state_data.get("redirect_after") or ""

    metadata = await _fetch_oidc_metadata(provider)

    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        token_resp = await client.post(
            metadata["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _get_redirect_uri(provider),
                "client_id": _PROVIDER_CLIENT_IDS[provider],
                "client_secret": _PROVIDER_CLIENT_SECRETS[provider],
                "code_verifier": code_verifier,
            },
            timeout=15,
        )
        token_resp.raise_for_status()
        tokens = token_resp.json()

        access_token = tokens.get("access_token")
        if not access_token:
            raise ValueError("No access_token in provider response")

        # Fetch user info from userinfo endpoint
        userinfo_resp = await client.get(
            metadata["userinfo_endpoint"],
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        userinfo_resp.raise_for_status()
        userinfo = userinfo_resp.json()

    return {
        "sub": userinfo["sub"],
        "email": userinfo.get("email", ""),
        "name": userinfo.get("name") or userinfo.get("email", "User"),
        "redirect_after": redirect_after,
    }
