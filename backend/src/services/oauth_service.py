"""OAuth 2.0 / OIDC service for Google and Microsoft providers.

Uses authlib AsyncOAuth2Client. State + PKCE code_verifier stored in Redis.
"""
from __future__ import annotations

import json
import secrets
from urllib.parse import urlencode

import redis.asyncio as aioredis
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.oidc.core import CodeIDToken

from backend.src.config import settings

# Provider OIDC discovery URLs
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

# Redis key prefix for OAuth state
_STATE_PREFIX = "oauth_state:"
_STATE_TTL = 600  # 10 minutes


def _get_redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


def _get_redirect_uri(provider: str) -> str:
    return f"{settings.app_base_url}/auth/callback/{provider}"


async def get_authorization_url(provider: str, redirect_after: str | None = None) -> str:
    """Generate the OAuth authorisation URL with PKCE + state.

    Stores state → {code_verifier, redirect_after} in Redis.
    Returns the provider authorisation URL to redirect the user to.
    """
    if provider not in _DISCOVERY_URLS:
        raise ValueError(f"Unknown provider: {provider}")

    client = AsyncOAuth2Client(
        client_id=_PROVIDER_CLIENT_IDS[provider],
        client_secret=_PROVIDER_CLIENT_SECRETS[provider],
        redirect_uri=_get_redirect_uri(provider),
        scope="openid email profile",
        code_challenge_method="S256",
    )

    # Fetch OIDC discovery
    metadata = await client.load_server_metadata(_DISCOVERY_URLS[provider])
    authorization_endpoint = metadata["authorization_endpoint"]

    # Generate state + PKCE
    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)

    # Store in Redis
    r = _get_redis()
    payload = json.dumps({"code_verifier": code_verifier, "redirect_after": redirect_after or ""})
    await r.setex(f"{_STATE_PREFIX}{state}", _STATE_TTL, payload)
    await r.aclose()

    # Build authorisation URL
    url, _ = client.create_authorization_url(
        authorization_endpoint,
        state=state,
        code_verifier=code_verifier,
    )
    return url


async def exchange_code(provider: str, code: str, state: str) -> dict:
    """Exchange authorisation code for id_token. Validates state.

    Returns dict with keys: sub, email, name, redirect_after
    Raises ValueError on invalid state or token.
    """
    if provider not in _DISCOVERY_URLS:
        raise ValueError(f"Unknown provider: {provider}")

    # Retrieve + delete state from Redis (one-time use)
    r = _get_redis()
    state_key = f"{_STATE_PREFIX}{state}"
    raw = await r.get(state_key)
    if not raw:
        await r.aclose()
        raise ValueError("Invalid or expired OAuth state")
    await r.delete(state_key)
    await r.aclose()

    state_data = json.loads(raw)
    code_verifier = state_data["code_verifier"]
    redirect_after = state_data.get("redirect_after") or ""

    # Fetch OIDC metadata
    client = AsyncOAuth2Client(
        client_id=_PROVIDER_CLIENT_IDS[provider],
        client_secret=_PROVIDER_CLIENT_SECRETS[provider],
        redirect_uri=_get_redirect_uri(provider),
        scope="openid email profile",
        code_challenge_method="S256",
    )
    metadata = await client.load_server_metadata(_DISCOVERY_URLS[provider])

    # Exchange code for tokens
    token_endpoint = metadata["token_endpoint"]
    token = await client.fetch_token(
        token_endpoint,
        code=code,
        code_verifier=code_verifier,
    )

    # Verify id_token
    id_token = token.get("id_token")
    if not id_token:
        raise ValueError("No id_token in OAuth response")

    jwks_uri = metadata["jwks_uri"]
    # Use authlib to fetch and verify
    claims = await client.parse_id_token(token, nonce=None)

    return {
        "sub": claims["sub"],
        "email": claims.get("email", ""),
        "name": claims.get("name", claims.get("email", "User")),
        "redirect_after": redirect_after,
    }
