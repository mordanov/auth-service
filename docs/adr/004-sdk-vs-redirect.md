# ADR-004: Client Integration Pattern — SDK vs Redirect-Based vs Middleware

**Status**: Accepted
**Date**: 2026-05-09
**Deciders**: Architect Agent

---

## Context

Six existing client applications need to integrate with the centralised auth service.
We need to decide how each client app verifies that an incoming request is
authenticated and authorised for that application.

## Options Considered

### Option A — Full redirect-based SSO (client apps redirect every unauthenticated request)
Client apps do not perform any local token validation. Every unauthenticated request
is redirected to `https://auth.example.com/auth/login?redirect_uri=...`.

**Pros**: Client apps have zero auth code; uniform experience.
**Cons**: Requires session cookies or a shared session store; does not work for
API-only clients; each page load that misses a session triggers a redirect round-trip;
difficult to support non-browser clients (CLI tools, mobile apps, API consumers).

### Option B — Shared session middleware (reverse proxy handles auth)
A reverse proxy (nginx, Traefik) validates the session token via an `auth_request`
subrequest to the auth service on every request.

**Pros**: Zero code change in client apps.
**Cons**: Adds auth service as a synchronous dependency on every single request
(network latency on hot path); complex nginx `auth_request` config; hard to pass
user context (sub, grants) into application code.

### Option C — Thin SDK middleware (distribute JWT validation + grants check as a package)
Client apps install a thin package (`auth_client` for Python, `@auth-service/client`
for JS). The middleware validates the RS256 JWT locally (JWKS public key, cached)
and checks the `grants` claim. The auth service is not called on the hot path.

**Pros**: Zero auth service latency on every request (public key cached); works for
API-only clients; passes `request.user` context cleanly; one-line integration;
easy to test independently; works if auth service is temporarily unreachable.
**Cons**: Revocation window = access token TTL (≤ 15 min — acceptable per SC-005);
requires distributing and versioning SDK packages.

## Decision

**Option C — Thin SDK middleware**.

This is the only option that satisfies SC-003 (token validation < 10 ms with no
network call) while giving client apps clean access to user context.

The integration contract is stable across auth-service minor versions:
- JWT claims (`sub`, `grants`) remain the same structure
- JWKS endpoint URL is fixed
- SDK version is pinned in each client app's dependency manifest

## Integration Contract (stable API)

```python
# Python (FastAPI) — 1 line per app
from auth_client import AuthMiddleware
app.add_middleware(AuthMiddleware, app_name="budget-site", jwks_url=AUTH_JWKS_URL)

# Python (Django) — settings.py
MIDDLEWARE = ["auth_client.DjangoAuthMiddleware"]
AUTH_CLIENT_APP_NAME = "news-site"
AUTH_CLIENT_JWKS_URL = "https://auth.example.com/.well-known/jwks.json"
```

```typescript
// Express (Node.js) — 1 line per app
import { createMiddleware } from '@auth-service/client'
app.use(createMiddleware({ appName: 'reminders-app', jwksUrl: AUTH_JWKS_URL }))
```

## Consequences

- SDK packages live in `sdk/python/` and `sdk/js/` in this repo
- Each client app pins a SDK version (e.g., `auth-client==0.1.0`)
- SDK updates are backwards-compatible within a minor version
- Breaking changes to the JWT claim structure require a major SDK version bump
- Apps must handle 401 (invalid/expired token) and 403 (no grant) and redirect to
  `https://auth.example.com/auth/login?redirect_uri=<current_url>`
