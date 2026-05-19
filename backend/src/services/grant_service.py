"""Grant service — CRUD for AppGrant + admin user listing."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.app_grant import AppGrant
from src.models.audit_event import AuditEvent
from src.models.identity_provider import IdentityProvider
from src.models.refresh_token import RefreshToken
from src.models.user import User


# ── User listing ──────────────────────────────────────────────────────────────


async def list_users(
    session: AsyncSession,
    *,
    limit: int = 20,
    offset: int = 0,
    q: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Return paginated users with their grants and identity providers.

    Returns (items, total_count).
    """
    base_query = select(User)
    if q:
        # Search by display_name or email (via identity_providers join)
        base_query = base_query.join(User.identity_providers).where(
            or_(
                User.display_name.ilike(f"%{q}%"),
                IdentityProvider.email.ilike(f"%{q}%"),
            )
        ).distinct()

    total = await session.scalar(
        select(func.count()).select_from(base_query.subquery())
    ) or 0

    users_result = await session.scalars(
        base_query.order_by(User.created_at.desc()).offset(offset).limit(limit)
    )
    users = list(users_result)

    items = []
    for user in users:
        # Load grants and identity providers eagerly
        grants_result = await session.scalars(
            select(AppGrant).where(AppGrant.user_id == user.id, AppGrant.is_active == True)  # noqa: E712
        )
        idps_result = await session.scalars(
            select(IdentityProvider).where(IdentityProvider.user_id == user.id)
        )
        items.append({
            "id": str(user.id),
            "display_name": user.display_name,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat(),
            "grants": [_grant_to_dict(g) for g in grants_result],
            "identity_providers": [_idp_to_dict(i) for i in idps_result],
        })

    return items, total


async def get_user_detail(
    session: AsyncSession, user_id: uuid.UUID
) -> dict[str, Any] | None:
    """Return full user detail with recent audit events, or None if not found."""
    user = await session.get(User, user_id)
    if not user:
        return None

    grants_result = await session.scalars(
        select(AppGrant).where(AppGrant.user_id == user_id)
    )
    idps_result = await session.scalars(
        select(IdentityProvider).where(IdentityProvider.user_id == user_id)
    )
    events_result = await session.scalars(
        select(AuditEvent)
        .where(
            or_(AuditEvent.actor_user_id == user_id, AuditEvent.target_user_id == user_id)
        )
        .order_by(AuditEvent.created_at.desc())
        .limit(10)
    )

    return {
        "id": str(user.id),
        "display_name": user.display_name,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat(),
        "grants": [_grant_to_dict(g) for g in grants_result],
        "identity_providers": [_idp_to_dict(i) for i in idps_result],
        "recent_events": [_event_to_dict(e) for e in events_result],
    }


# ── Grant CRUD ────────────────────────────────────────────────────────────────


async def create_grant(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    user_id: uuid.UUID,
    app_name: str,
    role: str = "user",
) -> AppGrant:
    """Create or reactivate an AppGrant. Raises ValueError if already active."""
    # Check for existing grant
    existing = await session.scalar(
        select(AppGrant).where(
            AppGrant.user_id == user_id,
            AppGrant.app_name == app_name,
        )
    )
    if existing:
        if existing.is_active:
            raise ValueError(f"Active grant already exists for {user_id} on {app_name}")
        # Reactivate soft-deleted grant
        existing.is_active = True
        existing.role = role
        existing.granted_by = actor_id
        await session.flush()
        await _write_audit(session, actor_id, "grant_created", user_id, app_name)
        await session.commit()
        return existing

    grant = AppGrant(
        user_id=user_id,
        granted_by=actor_id,
        app_name=app_name,
        role=role,
    )
    session.add(grant)
    await session.flush()
    await _write_audit(session, actor_id, "grant_created", user_id, app_name)
    await session.commit()
    await session.refresh(grant)
    return grant


async def revoke_grant(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    grant_id: uuid.UUID,
) -> AppGrant | None:
    """Soft-delete an AppGrant (set is_active=False). Returns updated grant or None."""
    grant = await session.get(AppGrant, grant_id)
    if not grant or not grant.is_active:
        return None

    grant.is_active = False
    await session.flush()
    await _write_audit(session, actor_id, "grant_revoked", grant.user_id, grant.app_name)
    await session.commit()
    await session.refresh(grant)
    return grant


async def revoke_all_user_sessions(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """Revoke all active refresh tokens for a user (emergency action)."""
    from sqlalchemy import update
    import redis.asyncio as aioredis
    from src.config import settings

    # Mark all DB refresh tokens revoked
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked == False)  # noqa: E712
        .values(revoked=True)
    )

    # Delete all Redis keys for this user
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    pattern = f"rt:{user_id}:*"
    async for key in r.scan_iter(pattern):
        await r.delete(key)
    await r.aclose(close_connection_pool=True)

    await _write_audit(session, actor_id, "token_revoked_all", user_id, None)
    await session.commit()


# ── Internal helpers ──────────────────────────────────────────────────────────


async def _write_audit(
    session: AsyncSession,
    actor_id: uuid.UUID,
    action_type: str,
    target_user_id: uuid.UUID | None,
    target_app: str | None,
    metadata: dict | None = None,
) -> None:
    event = AuditEvent(
        actor_user_id=actor_id,
        action_type=action_type,
        target_user_id=target_user_id,
        target_app=target_app,
        metadata_=metadata,
    )
    session.add(event)
    await session.flush()


def _grant_to_dict(g: AppGrant) -> dict:
    return {
        "id": str(g.id),
        "user_id": str(g.user_id),
        "app_name": g.app_name,
        "role": g.role,
        "granted_at": g.granted_at.isoformat(),
        "is_active": g.is_active,
        "granted_by_display_name": None,  # Enriched by API layer if needed
    }


def _idp_to_dict(i: IdentityProvider) -> dict:
    return {
        "provider": i.provider,
        "email": i.email,
        "created_at": i.created_at.isoformat(),
    }


def _event_to_dict(e: AuditEvent) -> dict:
    return {
        "id": str(e.id),
        "actor_user_id": str(e.actor_user_id) if e.actor_user_id else None,
        "actor_display_name": None,
        "action_type": e.action_type,
        "target_user_id": str(e.target_user_id) if e.target_user_id else None,
        "target_user_display_name": None,
        "target_app": e.target_app,
        "metadata": e.metadata_,
        "created_at": e.created_at.isoformat(),
    }
