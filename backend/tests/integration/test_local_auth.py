"""Integration tests for local (username/password) authentication flow."""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# These tests require a running database + redis.
# Marked as integration — run with: pytest -m integration
pytestmark = pytest.mark.integration


@pytest.fixture
def app():
    """Return the FastAPI app instance."""
    from src.main import app as _app
    return _app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_local_login_success(app):
    """Successful login returns a valid JWT and sets refresh cookie."""
    from authlib.jose import JsonWebKey, jwt as authlib_jwt
    from src.config import settings

    # First register a test user
    from src.db.base import AsyncSessionLocal
    from src.services.auth_service import register_local

    async with AsyncSessionLocal() as session:
        await register_local(
            session,
            email="testuser@example.com",
            password="testpassword123",
            display_name="Test User",
            skip_if_exists=True,
        )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/auth/login",
            json={"email": "testuser@example.com", "password": "testpassword123"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "Bearer"

    # Decode and verify JWT structure
    public_key = JsonWebKey.import_key(settings.jwt_public_key.encode(), {"kty": "RSA"})
    claims = authlib_jwt.decode(data["access_token"], public_key)
    claims.validate()
    payload = dict(claims)
    assert "sub" in payload
    assert "grants" in payload
    assert isinstance(payload["grants"], list)

    # Refresh cookie must be set
    assert "refresh" in resp.cookies


@pytest.mark.anyio
async def test_local_login_wrong_password(app):
    """Login with wrong password returns 401."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/auth/login",
            json={"email": "testuser@example.com", "password": "wrongpassword"},
        )
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"] == "invalid_credentials"


@pytest.mark.anyio
async def test_token_refresh_and_rotation(app):
    """Refresh endpoint rotates the refresh token."""
    from src.db.base import AsyncSessionLocal
    from src.services.auth_service import register_local

    async with AsyncSessionLocal() as session:
        await register_local(
            session,
            email="refresh_test@example.com",
            password="refreshpass123",
            display_name="Refresh Test",
            skip_if_exists=True,
        )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Login
        login_resp = await client.post(
            "/auth/login",
            json={"email": "refresh_test@example.com", "password": "refreshpass123"},
        )
        assert login_resp.status_code == 200
        original_refresh = login_resp.cookies.get("refresh")
        assert original_refresh

        # Refresh → get new token
        refresh_resp = await client.post("/auth/refresh")
        assert refresh_resp.status_code == 200
        new_access = refresh_resp.json()["access_token"]
        assert new_access != login_resp.json()["access_token"]

        # The old refresh cookie is now invalid (rotated)
        # Re-use old token → expect 401
        client.cookies.set("refresh", original_refresh)
        reuse_resp = await client.post("/auth/refresh")
        assert reuse_resp.status_code == 401
