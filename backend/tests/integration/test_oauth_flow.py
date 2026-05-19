"""Integration tests for OAuth 2.0 callback flow (mocked provider)."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_oauth_login_redirect():
    """GET /auth/login/google redirects to provider URL."""
    from httpx import AsyncClient, ASGITransport
    from src.main import app

    with patch(
        "src.services.oauth_service.get_authorization_url",
        new=AsyncMock(return_value="https://accounts.google.com/o/oauth2/auth?state=abc&..."),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
        ) as client:
            resp = await client.get("/auth/login/google")

    assert resp.status_code == 302
    assert "accounts.google.com" in resp.headers["location"]


@pytest.mark.anyio
async def test_oauth_callback_creates_user():
    """OAuth callback upserts user and issues tokens."""
    from httpx import AsyncClient, ASGITransport
    from src.main import app

    mock_user_info = {
        "sub": "google-sub-12345",
        "email": "oauth_user@gmail.com",
        "name": "OAuth User",
        "redirect_after": "http://localhost:3001",
    }

    with patch(
        "src.services.oauth_service.exchange_code",
        new=AsyncMock(return_value=mock_user_info),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
        ) as client:
            resp = await client.get(
                "/auth/callback/google",
                params={"code": "fake_code", "state": "fake_state"},
            )

    assert resp.status_code == 302
    location = resp.headers["location"]
    assert "access_token=" in location
    assert "refresh" in resp.cookies


@pytest.mark.anyio
async def test_oauth_invalid_state():
    """OAuth callback with invalid state returns 401."""
    from httpx import AsyncClient, ASGITransport
    from src.main import app

    with patch(
        "src.services.oauth_service.exchange_code",
        new=AsyncMock(side_effect=ValueError("Invalid or expired OAuth state")),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
        ) as client:
            resp = await client.get(
                "/auth/callback/google",
                params={"code": "code", "state": "bad_state"},
            )

    assert resp.status_code == 401
