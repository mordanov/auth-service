"""Security headers middleware.

Injects hardened HTTP security headers on every response:

  Strict-Transport-Security  — enforce HTTPS for 1 year including subdomains
  Content-Security-Policy    — restrict resource loading to same origin
  X-Frame-Options            — deny embedding in iframes (clickjacking)
  X-Content-Type-Options     — disable MIME sniffing
  Referrer-Policy            — limit referrer leakage on cross-origin requests
  Permissions-Policy         — disable unused browser features

CSP is intentionally permissive for the /docs and /redoc Swagger endpoints so
that the interactive API explorer works in development.  Set
DISABLE_SWAGGER=true (removes docs_url/redoc_url in production) to serve the
strictest possible policy everywhere.
"""
from __future__ import annotations

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

_HSTS = "max-age=31536000; includeSubDomains"

# Strict policy — used on every endpoint except Swagger UI
_CSP_STRICT = (
    "default-src 'none'; "
    "script-src 'none'; "
    "style-src 'none'; "
    "img-src 'none'; "
    "connect-src 'self'; "
    "frame-ancestors 'none';"
)

# Relaxed policy — used only on /docs and /redoc to allow Swagger JS/CSS
_CSP_DOCS = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
    "font-src https://fonts.gstatic.com; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "connect-src 'self'; "
    "frame-ancestors 'none';"
)

_DOCS_PATHS = frozenset(["/docs", "/redoc", "/openapi.json"])


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every HTTP response."""

    async def dispatch(self, request: Request, call_next: object) -> Response:
        response: Response = await call_next(request)

        is_docs = request.url.path.rstrip("/") in _DOCS_PATHS or request.url.path.startswith(
            ("/docs/", "/redoc/")
        )

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), payment=()"
        )
        response.headers["Content-Security-Policy"] = _CSP_DOCS if is_docs else _CSP_STRICT

        # HSTS is only meaningful over HTTPS; set it unconditionally and let the
        # reverse proxy handle the HTTP→HTTPS redirect upstream.
        response.headers["Strict-Transport-Security"] = _HSTS

        return response
