# Auth Service

Centralised authentication for the `web-projects` platform. Replaces per-app login code in **budget-site**, **family-admin-routine**, **family-archive**, **news-site**, **poetry-site**, and **reminders-app** with a single service.

## What it does

- **Sign in via Google, Microsoft, or username/password** — one consistent login page for all apps.
- **Issues RS256 JWTs** — client apps validate tokens locally in < 10 ms with no auth-service round-trip.
- **Per-app access grants** — a user only reaches an app if an admin has explicitly granted them access.
- **Admin panel** — web UI to list users, grant/revoke per-app access, and view an immutable audit log.
- **Thin SDK** — Python and JS/TS middleware for client apps; replace existing auth with a single import.

## Quick start (local)

```bash
cp .env.example .env          # add GOOGLE_CLIENT_ID, MICROSOFT_CLIENT_ID, DB/Redis URLs
docker-compose up --build
```

| Service | URL |
|---------|-----|
| Login portal | http://localhost:8000/auth/login |
| Admin panel | http://localhost:3000/admin |
| JWKS endpoint | http://localhost:8000/.well-known/jwks.json |
| API docs | http://localhost:8000/docs |

On first start, set `SEED_ADMIN_EMAIL` + `SEED_ADMIN_PASSWORD` in `.env` to bootstrap the admin account.

## Integrating a client app

**Python (FastAPI / Django)**:
```python
from auth_client.middleware import require_auth

@app.get("/dashboard")
async def dashboard(user = Depends(require_auth(app_name="budget-site"))):
    ...
```

**JavaScript / TypeScript (Express / Next.js)**:
```typescript
import { authMiddleware } from "auth-client";
app.use(authMiddleware({ appName: "news-site", authServiceUrl: "https://auth.example.com" }));
```

The middleware validates the JWT locally (cached JWKS public key), checks the `grants` claim for your app, and injects the decoded user. Returns 401 for an invalid token, 403 for a missing grant.

## Key design decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Token format | RS256 JWT | Clients verify without calling the service |
| OAuth library | authlib | OIDC discovery + PKCE built in |
| Refresh tokens | Opaque, Redis-backed | Rotatable and revocable; reuse detection |
| Grant propagation | JWT `grants` claim | No per-request DB lookup; takes effect on next refresh |
| Admin panel | Standalone React SPA | No auth logic in client apps; clean separation |

## Tech stack

`Python 3.12 / FastAPI` · `PostgreSQL 16` · `Redis 7` · `React 18 / Vite` · `authlib` · `python-jose` · `shadcn/ui`

## Documentation

- [`FULL_DESCRIPTION.md`](./FULL_DESCRIPTION.md) — architecture, data model, API reference, security model, deployment, migration guide
- [`docs/api-spec.yaml`](./docs/api-spec.yaml) — OpenAPI 3.1 spec *(generated in Phase 1)*
- [`docs/migration-guide.md`](./docs/migration-guide.md) — step-by-step client app migration *(Phase 6)*
- [`docs/adr/`](./docs/adr/) — architectural decision records

## Agent collaboration

This project uses [brainstorm-mcp](https://github.com/TheodorStorm/brainstorm-mcp) for multi-agent design coordination and [speckit-mcp-x](https://www.npmjs.com/package/speckit-mcp-x) for spec-driven task generation. Agent prompts are in [`agents/`](./agents/).
