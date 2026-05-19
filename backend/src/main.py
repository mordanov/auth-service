"""FastAPI application factory."""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.api import auth, jwks, admin
from src.middleware.security_headers import SecurityHeadersMiddleware


def create_app() -> FastAPI:
    # Disable interactive docs in production to enforce strictest CSP
    disable_swagger = os.environ.get("DISABLE_SWAGGER", "").lower() in ("1", "true", "yes")
    app = FastAPI(
        title="Auth Service",
        version="1.0.0",
        docs_url=None if disable_swagger else "/docs",
        redoc_url=None if disable_swagger else "/redoc",
    )

    # Security headers — HSTS, CSP, X-Frame-Options, etc.
    app.add_middleware(SecurityHeadersMiddleware)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(auth.router)
    app.include_router(jwks.router)
    app.include_router(admin.router, prefix="/admin")

    @app.on_event("startup")
    async def on_startup() -> None:
        await _seed_admin()

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        from src.db.base import engine
        from src.middleware.rate_limit import close_redis

        await close_redis()
        await engine.dispose()

    return app


async def _seed_admin() -> None:
    """Create the initial admin account if SEED_ADMIN_EMAIL is configured."""
    if not settings.seed_admin_email or not settings.seed_admin_password:
        return
    from src.db.base import AsyncSessionLocal
    from src.services.auth_service import register_local, ensure_admin_grant
    async with AsyncSessionLocal() as session:
        await register_local(
            session,
            email=settings.seed_admin_email,
            password=settings.seed_admin_password,
            display_name="Admin",
            skip_if_exists=True,
        )
        await ensure_admin_grant(session, email=settings.seed_admin_email)


app = create_app()
