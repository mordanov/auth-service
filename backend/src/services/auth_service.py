"""Authentication service — login, registration, token lifecycle."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import bcrypt as _bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.app_grant import AppGrant
from src.models.identity_provider import IdentityProvider
from src.models.refresh_token import RefreshToken
from src.models.user import User
from src.services.token_service import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
)

def _hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt(rounds=12)).decode()


def _verify_password(password: str, password_hash: str) -> bool:
    return _bcrypt.checkpw(password.encode(), password_hash.encode())


# ── Registration ──────────────────────────────────────────────────────────────


async def register_local(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    display_name: str,
    skip_if_exists: bool = False,
) -> User:
    """Create a User + local IdentityProvider. Raises ValueError if duplicate."""
    existing = await session.scalar(
        select(IdentityProvider).where(
            IdentityProvider.provider == "local",
            IdentityProvider.email == email,
        )
    )
    if existing:
        if skip_if_exists:
            return await session.get(User, existing.user_id)  # type: ignore[return-value]
        raise ValueError(f"Account already exists for {email}")

    user = User(display_name=display_name)
    session.add(user)
    await session.flush()

    idp = IdentityProvider(
        user_id=user.id,
        provider="local",
        email=email,
        password_hash=_hash_password(password),
    )
    session.add(idp)
    await session.commit()
    await session.refresh(user)
    return user


async def ensure_admin_grant(session: AsyncSession, *, email: str) -> None:
    """Ensure the user identified by email has an 'admin' grant."""
    idp = await session.scalar(
        select(IdentityProvider).where(
            IdentityProvider.provider == "local",
            IdentityProvider.email == email,
        )
    )
    if not idp:
        return
    existing_grant = await session.scalar(
        select(AppGrant).where(
            AppGrant.user_id == idp.user_id,
            AppGrant.app_name == "admin",
        )
    )
    if not existing_grant:
        grant = AppGrant(user_id=idp.user_id, app_name="admin", role="admin")
        session.add(grant)
        await session.commit()


# ── Local login ───────────────────────────────────────────────────────────────


async def login_local(
    session: AsyncSession, *, email: str, password: str
) -> tuple[str, str]:
    """Verify local credentials and return (access_token, refresh_token_opaque).
    Raises ValueError on invalid credentials.
    """
    idp = await session.scalar(
        select(IdentityProvider).where(
            IdentityProvider.provider == "local",
            IdentityProvider.email == email,
        )
    )
    if not idp or not idp.password_hash:
        raise ValueError("Invalid credentials")
    if not _verify_password(password, idp.password_hash):
        raise ValueError("Invalid credentials")

    user = await session.get(User, idp.user_id)
    if not user or not user.is_active:
        raise ValueError("Account is inactive")

    return await issue_tokens(session, user)


# ── Token lifecycle ───────────────────────────────────────────────────────────


async def issue_tokens(session: AsyncSession, user: User) -> tuple[str, str]:
    """Issue (access_token, opaque_refresh_token) for the given user.

    Writes the refresh token to both PostgreSQL (for lookup by hash) and Redis
    (key: rt:{user_id}:{token_id}) for fast bulk-revocation via SCAN.
    """
    import redis.asyncio as aioredis

    # Gather active grants
    grants_result = await session.scalars(
        select(AppGrant).where(
            AppGrant.user_id == user.id,
            AppGrant.is_active == True,  # noqa: E712
        )
    )
    grant_names = [g.app_name for g in grants_result]

    access_token = create_access_token(str(user.id), grant_names)

    # Opaque refresh token
    opaque = generate_refresh_token()
    token_hash = hash_refresh_token(opaque)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_ttl_days)

    rt = RefreshToken(
        token_hash=token_hash,
        user_id=user.id,
        expires_at=expires_at,
    )
    session.add(rt)
    await session.flush()  # populate rt.token_id before Redis write

    # Mirror token existence into Redis for bulk-revocation support
    # Key pattern: rt:{user_id}:{token_id}  (matches revoke_all_sessions SCAN)
    try:
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        redis_key = f"rt:{user.id}:{rt.token_id}"
        ttl_seconds = settings.refresh_token_ttl_days * 86400
        await r.setex(redis_key, ttl_seconds, "1")
        await r.aclose()
    except Exception:
        # Redis write is supplementary — token is authoritative in Postgres
        pass

    await session.commit()
    return access_token, opaque


async def refresh_tokens(
    session: AsyncSession, opaque_token: str
) -> tuple[str, str]:
    """Rotate refresh token. Returns (new_access_token, new_opaque_refresh_token).

    Theft detection: if the presented token was already rotated (revoked=True),
    all sessions for the identified user are revoked immediately before raising.
    """
    token_hash = hash_refresh_token(opaque_token)

    rt = await session.get(RefreshToken, token_hash)
    if rt is None:
        raise ValueError("Refresh token invalid or already used")
    if rt.revoked:
        # Token reuse detected — revoke ALL sessions for this user immediately
        await revoke_all_sessions(session, rt.user_id)
        raise ValueError("Refresh token already used — all sessions have been revoked")

    if rt.expires_at < datetime.now(timezone.utc):
        raise ValueError("Refresh token expired")

    # Invalidate old token
    rt.revoked = True
    await session.flush()

    user = await session.get(User, rt.user_id)
    if not user or not user.is_active:
        raise ValueError("Account inactive")

    new_access, new_opaque = await issue_tokens(session, user)
    return new_access, new_opaque


async def revoke_all_sessions(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Mark all refresh tokens for user as revoked."""
    from sqlalchemy import update
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked == False)  # noqa: E712
        .values(revoked=True)
    )
    await session.commit()


async def login_or_register_oauth(
    session: AsyncSession,
    *,
    provider: str,
    provider_user_id: str,
    email: str,
    display_name: str,
) -> tuple[str, str]:
    """Upsert User + IdentityProvider from OAuth callback. Return token pair."""
    # Check if this provider identity already exists
    idp = await session.scalar(
        select(IdentityProvider).where(
            IdentityProvider.provider == provider,
            IdentityProvider.provider_user_id == provider_user_id,
        )
    )
    if idp:
        user = await session.get(User, idp.user_id)
        if not user or not user.is_active:
            raise ValueError("Account is inactive")
    else:
        # Check if a user with same email + same provider already exists (email reuse)
        existing_local = await session.scalar(
            select(IdentityProvider).where(
                IdentityProvider.provider == provider,
                IdentityProvider.email == email,
            )
        )
        if existing_local:
            # Link to existing user
            user = await session.get(User, existing_local.user_id)
        else:
            # New user
            user = User(display_name=display_name)
            session.add(user)
            await session.flush()

        idp = IdentityProvider(
            user_id=user.id,
            provider=provider,
            provider_user_id=provider_user_id,
            email=email,
        )
        session.add(idp)
        await session.commit()
        await session.refresh(user)

    return await issue_tokens(session, user)
