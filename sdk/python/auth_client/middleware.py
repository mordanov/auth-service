"""FastAPI and Django middleware for the auth-client SDK."""
from __future__ import annotations

from typing import Any, Callable

from auth_client.exceptions import AuthError, NoGrantError, TokenExpiredError
from auth_client.validator import validate_token


class AuthenticatedUser:
    """Minimal user object injected into request.state."""

    def __init__(self, sub: str, grants: list[str], payload: dict[str, Any]) -> None:
        self.sub = sub
        self.grants = grants
        self._payload = payload

    def __repr__(self) -> str:
        return f"AuthenticatedUser(sub={self.sub!r}, grants={self.grants!r})"


# ── FastAPI / Starlette middleware ────────────────────────────────────────────


class AuthMiddleware:
    """Starlette-compatible ASGI middleware.

    Usage (FastAPI):
        from auth_client import AuthMiddleware
        app.add_middleware(AuthMiddleware, app_name="budget-site", jwks_url="...")
    """

    def __init__(self, app: Any, *, app_name: str, jwks_url: str) -> None:
        self.app = app
        self.app_name = app_name
        self.jwks_url = jwks_url

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # Extract Bearer token
        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode()
        token: str | None = None
        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer "):]

        if not token:
            await self._respond_error(scope, send, 401, "missing_token", "Authorization header required")
            return

        try:
            payload = validate_token(token, self.app_name, self.jwks_url)
        except TokenExpiredError:
            await self._respond_error(scope, send, 401, "token_expired", "Access token has expired")
            return
        except NoGrantError as exc:
            await self._respond_error(scope, send, 403, exc.code, str(exc))
            return
        except AuthError as exc:
            await self._respond_error(scope, send, 401, exc.code, str(exc))
            return

        # Inject user into ASGI scope state
        scope.setdefault("state", {})
        scope["state"]["user"] = AuthenticatedUser(
            sub=payload["sub"],
            grants=payload.get("grants", []),
            payload=payload,
        )

        await self.app(scope, receive, send)

    @staticmethod
    async def _respond_error(scope: dict, send: Any, status: int, code: str, message: str) -> None:
        import json as _json
        body = _json.dumps({"error": code, "message": message}).encode()
        await send({"type": "http.response.start", "status": status, "headers": [
            [b"content-type", b"application/json"],
            [b"content-length", str(len(body)).encode()],
        ]})
        await send({"type": "http.response.body", "body": body})


# ── FastAPI Depends helper ────────────────────────────────────────────────────


def get_auth_dependency(app_name: str, jwks_url: str) -> Callable:
    """Return a FastAPI Depends-compatible callable that validates the token.

    Usage:
        from fastapi import Depends
        from auth_client import get_auth_dependency

        verify = get_auth_dependency("budget-site", JWKS_URL)

        @app.get("/protected")
        async def route(user = Depends(verify)):
            return {"sub": user.sub}
    """
    from fastapi import HTTPException, Request

    def _verify(request: Request) -> AuthenticatedUser:
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            raise HTTPException(status_code=401, detail={"error": "missing_token"})
        token = auth[len("Bearer "):]
        try:
            payload = validate_token(token, app_name, jwks_url)
        except TokenExpiredError as exc:
            raise HTTPException(status_code=401, detail={"error": "token_expired"}) from exc
        except NoGrantError as exc:
            raise HTTPException(status_code=403, detail={"error": exc.code, "app": exc.app_name}) from exc
        except AuthError as exc:
            raise HTTPException(status_code=401, detail={"error": exc.code}) from exc
        return AuthenticatedUser(sub=payload["sub"], grants=payload.get("grants", []), payload=payload)

    return _verify
