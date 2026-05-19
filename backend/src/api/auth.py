"""Authentication API routes.

Covers local login, OAuth 2.0 flows, token refresh, and logout.
"""
from __future__ import annotations

import hashlib
from urllib.parse import urlparse

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.base import get_db
from src.middleware.rate_limit import check_rate_limit
from src.models.audit_event import AuditEvent
from src.services import auth_service, oauth_service
from src.services.token_service import hash_refresh_token

router = APIRouter(prefix="/auth", tags=["authentication"])


# ── Schemas ───────────────────────────────────────────────────────────────────


class LocalLoginRequest(BaseModel):
    email: EmailStr
    password: str
    redirect_uri: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = settings.access_token_ttl_minutes * 60


# ── Helpers ───────────────────────────────────────────────────────────────────


def _refresh_cookie_kwargs() -> dict:
    # Disable Secure flag only for local development (both localhost and 127.0.0.1)
    _base = settings.app_base_url
    _is_local = _base.startswith("http://localhost") or _base.startswith("http://127.0.0.1")
    return {
        "key": "refresh",
        "httponly": True,
        "secure": not _is_local,
        "samesite": "strict",
        "path": "/auth/refresh",
        "max_age": settings.refresh_token_ttl_days * 86400,
    }


def _is_allowed_redirect(url: str) -> bool:
    """Return True if the redirect URL's origin is in the configured allowlist."""
    try:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        return origin in settings.allowed_origins or url.startswith(settings.app_base_url)
    except Exception:
        return False


async def _log_event(
    session: AsyncSession,
    action_type: str,
    actor_user_id=None,
    target_user_id=None,
    target_app: str | None = None,
    metadata: dict | None = None,
) -> None:
    event = AuditEvent(
        actor_user_id=actor_user_id,
        action_type=action_type,
        target_user_id=target_user_id,
        target_app=target_app,
        metadata_=metadata,
    )
    session.add(event)
    await session.commit()


# ── Login page ────────────────────────────────────────────────────────────────


@router.get("/login")
async def login_page(redirect_after: str | None = None):
    """Redirect to frontend login portal."""
    url = f"{settings.app_base_url}/auth/login"
    if redirect_after:
        url += f"?redirect_after={redirect_after}"
    return RedirectResponse(url=url, status_code=302)


# ── Local login ───────────────────────────────────────────────────────────────


@router.post("/login", response_model=TokenResponse)
async def local_login(
    body: LocalLoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    """Authenticate with email + password."""
    client_ip = request.client.host if request.client else "unknown"
    await check_rate_limit(
        f"rl:login:{client_ip}",
        max_requests=settings.rate_limit_login_per_minute,
    )

    try:
        access_token, opaque_refresh = await auth_service.login_local(
            session, email=body.email, password=body.password
        )
    except ValueError as exc:
        # Log failed attempt — store hashed email only, never plaintext
        email_hash = hashlib.sha256(body.email.lower().encode()).hexdigest()[:16]
        await _log_event(session, "login_failed", metadata={"email_prefix": email_hash})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_credentials", "message": "Email or password is incorrect"},
        ) from exc

    response = JSONResponse(
        content=TokenResponse(access_token=access_token).model_dump(),
        status_code=200,
    )
    response.set_cookie(value=opaque_refresh, **_refresh_cookie_kwargs())
    return response


# ── OAuth initiation ──────────────────────────────────────────────────────────


@router.get("/login/{provider}")
async def oauth_login(provider: str, redirect_uri: str | None = None):
    """Redirect to OAuth provider authorisation page."""
    if provider not in ("google", "microsoft"):
        raise HTTPException(status_code=400, detail={"error": "unknown_provider"})
    try:
        url = await oauth_service.get_authorization_url(provider, redirect_after=redirect_uri)
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"error": "provider_error", "message": str(exc)}) from exc
    return RedirectResponse(url=url, status_code=302)


# ── OAuth callback ─────────────────────────────────────────────────────────────


@router.get("/callback/{provider}")
async def oauth_callback(
    provider: str,
    code: str,
    state: str,
    session: AsyncSession = Depends(get_db),
):
    """Handle OAuth provider callback: exchange code, upsert user, issue tokens."""
    if provider not in ("google", "microsoft"):
        raise HTTPException(status_code=400, detail={"error": "unknown_provider"})

    try:
        user_info = await oauth_service.exchange_code(provider, code, state)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "oauth_error", "message": str(exc)},
        ) from exc

    try:
        access_token, opaque_refresh = await auth_service.login_or_register_oauth(
            session,
            provider=provider,
            provider_user_id=user_info["sub"],
            email=user_info["email"],
            display_name=user_info["name"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=403, detail={"error": "account_inactive"}) from exc

    # Redirect to originating app with token
    redirect_after = user_info.get("redirect_after") or settings.app_base_url
    # Validate redirect target against allowlist to prevent open redirect
    if not _is_allowed_redirect(redirect_after):
        redirect_after = settings.app_base_url
    # Use URL fragment so the token is never sent to the server (not in logs or browser history)
    destination = f"{redirect_after}#access_token={access_token}&token_type=Bearer&expires_in={settings.access_token_ttl_minutes * 60}"

    response = RedirectResponse(url=destination, status_code=302)
    response.set_cookie(value=opaque_refresh, **_refresh_cookie_kwargs())
    return response


# ── Token refresh ─────────────────────────────────────────────────────────────


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    refresh: str | None = Cookie(default=None),
    session: AsyncSession = Depends(get_db),
):
    """Rotate refresh token and issue new access token."""
    client_ip = request.client.host if request.client else "unknown"
    await check_rate_limit(
        f"rl:refresh:{client_ip}",
        max_requests=settings.rate_limit_refresh_per_minute,
    )

    if not refresh:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "missing_refresh_token"},
        )
    try:
        new_access, new_opaque = await auth_service.refresh_tokens(session, refresh)
    except ValueError as exc:
        resp = JSONResponse(
            content={"error": "invalid_refresh_token", "message": str(exc)},
            status_code=401,
        )
        resp.delete_cookie("refresh", path="/auth/refresh")
        return resp

    response = JSONResponse(
        content=TokenResponse(access_token=new_access).model_dump(),
        status_code=200,
    )
    response.set_cookie(value=new_opaque, **_refresh_cookie_kwargs())
    return response


# ── Logout ────────────────────────────────────────────────────────────────────


@router.post("/logout", status_code=204, response_class=Response)
async def logout(
    refresh: str | None = Cookie(default=None),
    session: AsyncSession = Depends(get_db),
) -> Response:
    """Revoke the current refresh token."""
    if refresh:
        token_hash = hash_refresh_token(refresh)
        from sqlalchemy import update
        from src.models.refresh_token import RefreshToken
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.token_hash == token_hash)
            .values(revoked=True)
        )
        await session.commit()

    resp = Response(status_code=204)
    resp.delete_cookie("refresh", path="/auth/refresh")
    return resp


# TODO (Phase 5): POST /admin/users/{user_id}/revoke-sessions → call revoke_all_sessions()
