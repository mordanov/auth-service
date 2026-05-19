"""Integration tests for admin grant endpoints."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(scope="session")]


def _make_admin_token(user_id: str = "admin-user-id") -> str:
    """Create a mock admin JWT that decode_access_token will accept."""
    return f"mock-admin-token-{user_id}"


async def test_non_admin_gets_403():
    """Non-admin user attempting to access admin endpoints gets 403."""
    from httpx import AsyncClient, ASGITransport
    from src.main import app

    # Token with no admin grant
    with patch(
        "src.api.admin.decode_access_token",
        return_value={"sub": "user-123", "grants": ["budget-site"], "exp": 9999999999},
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/admin/users",
                headers={"Authorization": "Bearer non-admin-token"},
            )
    assert resp.status_code == 403


async def test_missing_token_gets_401():
    """Request without Authorization header gets 401."""
    from httpx import AsyncClient, ASGITransport
    from src.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/admin/users")
    assert resp.status_code == 401
