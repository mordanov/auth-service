"""Audit log query service."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.src.models.audit_event import AuditEvent


async def list_events(
    session: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    user_id: uuid.UUID | None = None,
    app_name: str | None = None,
    action_type: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Return paginated audit events (newest first).

    Returns (items, total_count).
    """
    filters = []
    if user_id:
        filters.append(
            (AuditEvent.actor_user_id == user_id) | (AuditEvent.target_user_id == user_id)
        )
    if app_name:
        filters.append(AuditEvent.target_app == app_name)
    if action_type:
        filters.append(AuditEvent.action_type == action_type)

    base_query = select(AuditEvent)
    if filters:
        base_query = base_query.where(and_(*filters))

    total = await session.scalar(
        select(func.count()).select_from(base_query.subquery())
    ) or 0

    events_result = await session.scalars(
        base_query.order_by(AuditEvent.created_at.desc()).offset(offset).limit(limit)
    )

    items = [
        {
            "id": str(e.id),
            "actor_user_id": str(e.actor_user_id) if e.actor_user_id else None,
            "actor_display_name": None,  # Enriched by join if needed
            "action_type": e.action_type,
            "target_user_id": str(e.target_user_id) if e.target_user_id else None,
            "target_user_display_name": None,
            "target_app": e.target_app,
            "metadata": e.metadata_,
            "created_at": e.created_at.isoformat(),
        }
        for e in events_result
    ]

    return items, total
