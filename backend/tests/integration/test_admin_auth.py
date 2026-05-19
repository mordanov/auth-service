"""Tests that admin endpoints enforce auth correctly."""
from __future__ import annotations

import pytest
from unittest.mock import patch

pytestmark = pytest.mark.integration


@pytest.mark.anyio
async def test_admin_audit_requires_admin_role():
    """GET /admin/audit returns 403 for non-admin JWT."""
    from httpx import AsyncClient, ASGITransport
    from src.main import app

    with patch(
        "src.services.token_service.decode_access_token",
        return_value={"sub": "user-xyz", "grants": [], "exp": 9999999999},
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/admin/audit",
                headers={"Authorization": "Bearer some-token"},
            )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_admin_grants_list_requires_auth():
    """GET /admin/users returns 401 when no token provided."""
    from httpx import AsyncClient, ASGITransport
    from src.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/admin/users")
    assert resp.status_code == 401
