"""Admin API routes — user management, grant/revoke, audit log, session revocation.

All routes require a valid JWT with "admin" in the grants[] claim.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.base import get_db
from src.services import audit_service, grant_service
from src.services.token_service import decode_access_token, JWTError

router = APIRouter(tags=["admin"])


# ── Auth guard ────────────────────────────────────────────────────────────────


def _get_admin_user_id(authorization: str | None) -> str:
    """Extract and verify admin JWT from Authorization header value. Returns sub.

    Raises HTTPException 401 if token is missing/invalid, 403 if admin role absent.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"error": "missing_token"})
    token = authorization[len("Bearer "):]
    try:
        payload = decode_access_token(token)
    except JWTError as exc:
        raise HTTPException(
            status_code=401,
            detail={"error": "invalid_token", "message": str(exc)},
        ) from exc
    if "admin" not in payload.get("grants", []):
        raise HTTPException(
            status_code=403,
            detail={"error": "forbidden", "message": "Admin role required"},
        )
    return payload["sub"]


# ── Schemas ───────────────────────────────────────────────────────────────────


class CreateGrantRequest(BaseModel):
    user_id: uuid.UUID
    app_name: str
    role: str = "user"


class RevokeGrantRequest(BaseModel):
    is_active: bool  # must be False


# ── User endpoints ─────────────────────────────────────────────────────────────


@router.get("/users")
async def list_users(
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db),
) -> dict:
    _get_admin_user_id(authorization or "")
    items, total = await grant_service.list_users(session, limit=limit, offset=offset, q=q)
    return {"items": items, "total": total}


@router.get("/users/{user_id}")
async def get_user(
    user_id: uuid.UUID,
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db),
) -> dict:
    _get_admin_user_id(authorization or "")
    detail = await grant_service.get_user_detail(session, user_id)
    if not detail:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return detail


@router.post("/users/{user_id}/revoke-sessions", status_code=204, response_class=Response)
async def revoke_user_sessions(
    user_id: uuid.UUID,
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db),
) -> Response:
    actor_id = uuid.UUID(_get_admin_user_id(authorization or ""))
    await grant_service.revoke_all_user_sessions(session, actor_id=actor_id, user_id=user_id)
    return Response(status_code=204)


# ── Grant endpoints ────────────────────────────────────────────────────────────


@router.post("/grants", status_code=201)
async def create_grant(
    body: CreateGrantRequest,
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db),
) -> dict:
    actor_id = uuid.UUID(_get_admin_user_id(authorization or ""))
    try:
        grant = await grant_service.create_grant(
            session,
            actor_id=actor_id,
            user_id=body.user_id,
            app_name=body.app_name,
            role=body.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"error": "conflict", "message": str(exc)}) from exc
    return grant_service._grant_to_dict(grant)


@router.patch("/grants/{grant_id}")
async def revoke_grant(
    grant_id: uuid.UUID,
    body: RevokeGrantRequest,
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db),
) -> dict:
    if body.is_active:
        raise HTTPException(status_code=400, detail={"error": "bad_request", "message": "is_active must be false for revocation"})
    actor_id = uuid.UUID(_get_admin_user_id(authorization or ""))
    grant = await grant_service.revoke_grant(session, actor_id=actor_id, grant_id=grant_id)
    if not grant:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return grant_service._grant_to_dict(grant)


# ── Audit endpoints ────────────────────────────────────────────────────────────


@router.get("/audit")
async def get_audit_log(
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    user_id: uuid.UUID | None = Query(default=None),
    app_name: str | None = Query(default=None),
    action_type: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db),
) -> dict:
    _get_admin_user_id(authorization or "")
    items, total = await audit_service.list_events(
        session,
        limit=limit,
        offset=offset,
        user_id=user_id,
        app_name=app_name,
        action_type=action_type,
    )
    return {"items": items, "total": total}
