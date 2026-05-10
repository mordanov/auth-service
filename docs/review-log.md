# Review Log

## Phase 1 + Architecture — Review

**Reviewer**: Reviewer Agent
**Date**: 2026-05-09
**Status**: CHANGES REQUESTED

---

### Summary

The architecture documents, ADRs, data model, API contracts, and Phase 1 scaffolding are
coherent and well-aligned with the constitution. The security foundations are sound —
RS256+JWKS, PKCE+state, refresh rotation with theft detection, and deny-by-default RBAC
are all correctly specified. Two blockers must be resolved before Phase 2 code merges:
the `access_token` is passed as a URL query parameter on the OAuth redirect (token leakage
in server logs and Referer headers), and the docker-compose Redis service has no volume
mount (restart wipes all refresh tokens and rate-limit state, effectively logging everyone
out). Several major and minor issues are noted below.

---

### Findings

| # | Severity | File | Finding | Action |
|---|----------|------|---------|--------|
| 1 | Blocker | `docs/architecture.md`, `specs/.../contracts/auth-api.yaml` | Access token delivered via `redirect_uri?access_token=JWT` query parameter after OAuth callback. Query params appear in server access logs, browser history, and Referer headers — leaking the JWT to any server the user visits next. | Replace with fragment (`#access_token=...`) which never leaves the browser, or POST to the redirect_uri, or issue a short-lived one-time code that the client app exchanges for the token via a back-channel. Fragment (`#`) is the standard OIDC implicit/hybrid pattern and prevents log exposure. |
| 2 | Blocker | `docker-compose.yml` | Redis service has no named volume. On `docker-compose down` or container restart, the Redis data volume is lost. This destroys all active refresh tokens and OAuth state, instantly invalidating every user session, and also destroys all rate-limit and account-lockout state. | Add `redis_data` named volume and mount it at `/data` in the Redis service; add `--save 60 1` or `appendonly yes` to persist data across restarts. |
| 3 | Major | `docs/architecture.md` (Token Strategy table) | The JWT `grants` claim embeds all app grants at issuance time. If a user has grants for 5 apps and their access to one is revoked, their current access token (valid up to 15 min) still contains the revoked grant. The architecture acknowledges the 15-min window but does not document any emergency revocation path. No endpoint or process exists to force-expire a specific user's access tokens before their TTL. | Document the operational procedure for emergency revocation (e.g., admin-triggered "revoke all sessions" which forces re-login, thereby issuing a new JWT without the revoked grant). This already exists for refresh token reuse; expose it explicitly as an admin action in the Admin API. |
| 4 | Major | `specs/.../contracts/auth-api.yaml` | `POST /auth/login` 401 response does not specify a `Retry-After` header or rate-limit guidance. The rate-limit trigger is on the `/auth/login` endpoint but the password login 401 response body provides no distinction between "bad credentials" and "account locked out", making it impossible for a client to display a useful message. The spec only defines `429` for rate-limiting but the lockout is a business-logic 401. | Add a distinct 423 (Locked) or 429 response for account lockout on `POST /auth/login`. Add `Retry-After` to the 429 response of `POST /auth/login` (it is already on the generic `RateLimited` response component but not referenced from the login path). |
| 5 | Major | `specs/.../contracts/admin-api.yaml` | `DELETE /admin/grants/{grantId}` hard-deletes the grant record. The data model uses `is_active` as a soft-delete flag, but the API simply removes the record. Inconsistency: the DDL shows `is_active BOOLEAN DEFAULT TRUE`, implying soft-delete is the intended mechanism, yet `DELETE` implies hard delete. Audit log entry would still be written, but the grant record itself disappears, making audit reconstruction harder. | Decide definitively: soft-delete (`PATCH /admin/grants/{grantId}` with `{"is_active": false}`) or hard-delete. If soft-delete is chosen, update the DDL unique constraint to account for reactivation (currently `UNIQUE (user_id, app_name)` would block re-granting a revoked soft-deleted record). Document the choice. |
| 6 | Major | `specs/.../data-model.md` | `REFRESH_TOKEN` table comments state "Redis is primary; Postgres copy is optional for audit". However the DDL creates the table unconditionally with no indication that it is optional. If the service writes to both Redis and Postgres on every refresh, this doubles latency and introduces a consistency hazard (Redis write succeeds, Postgres write fails → token exists in Redis but not in audit table, or vice versa). | Explicitly specify whether Postgres is written for refresh tokens: if audit only, make the write async/best-effort and document that it is non-authoritative. If omitted entirely, remove the DDL. Add a comment in data-model.md clarifying the decision. |
| 7 | Minor | `backend/pyproject.toml` | `python-jose[cryptography]>=3.3` is listed. `python-jose` is effectively unmaintained (last release 2022, open CVEs related to algorithm confusion attacks in certain configurations). The `authlib` library already selected in ADR-003 provides RS256 JWT signing/verification (`authlib.jose`). Using two JWT libraries increases attack surface and creates divergence risk if one is patched and the other is not. | Migrate JWT issuance and verification from `python-jose` to `authlib.jose` (which is already a dependency). Remove `python-jose` from `pyproject.toml`. |
| 8 | Minor | `backend/src/config.py` | `seed_admin_email` and `seed_admin_password` have `default=""` which means the application starts without raising an error if these are not set. An empty `seed_admin_password` could result in a seed admin account with no password being created silently. | Use `default=None` (or `Field(default=None)`) and validate at startup: if `seed_admin_email` is non-empty then `seed_admin_password` must also be non-empty (and meet bcrypt minimum length). Raise `ValueError` at settings load time if the constraint is violated. |
| 9 | Minor | `docker-compose.yml` | `auth-backend` `depends_on` lists `postgres` and `redis` but Docker's `depends_on` only waits for the container to start, not for the service to be ready. On first boot, Postgres takes several seconds to initialise, and the backend will likely fail with a connection error. | Use `depends_on` with `condition: service_healthy` and add `healthcheck` stanzas to both `postgres` and `redis` services. |
| 10 | Minor | `docs/architecture.md` | The deployment topology diagram shows both the Login Portal and Admin Panel served on `:3000` behind Nginx. There is no mention of path-based routing rules (e.g., `/admin/*` → admin SPA, `/*` → login SPA) or how Nginx is configured. The `frontend/` directory in the plan contains one `Dockerfile` but the plan shows two separate React apps. | Clarify in architecture.md whether the login portal and admin panel are (a) two separate SPAs with separate Nginx configs, or (b) one SPA with conditional rendering based on route. Add at minimum a one-line nginx location block example. |
| 11 | Minor | `specs/.../contracts/auth-api.yaml` | `GET /auth/callback/{provider}` does not define an error redirect response for the case where the OAuth provider returns an error (user denies consent, provider error). The spec's edge cases section in `spec.md` states "auth service redirects back to the originating app with a structured error query parameter" but the OpenAPI spec only shows `400` and `401` JSON responses for this path — not a redirect. | Add a `302` error redirect response variant to the callback path, or add a `400` response with a redirect body description. Align with the `spec.md` edge case. |
| 12 | Nit | `sdk/python/auth_client/exceptions.py` | `AuthError.__init__` stores `self.message = message` but `Exception` already makes the message available via `str(e)` or `e.args[0]`. The extra attribute is harmless but redundant. | Remove `self.message` attribute or use `self.message` consistently and drop `super().__init__(message)` duplication. Align with JS SDK style (which uses `code` as a structured attribute, a slightly better pattern). |
| 13 | Nit | `backend/pyproject.toml` | `[tool.ruff]` uses `select = ["E", "F", "I", "UP"]` without `extend-select` or `ignore`. The `S` (bandit security) and `B` (bugbear) rule sets would catch common security and logic errors in an auth service. | Add `"S", "B"` to the ruff select list. |
| 14 | Nit | `docs/adr/003-oauth-library.md` | ADR-003 states `python-jose[cryptography]` is used "for our own JWT issuance" — cross-referencing Finding #7. If `python-jose` is removed, this ADR should be updated to record that `authlib.jose` is used for issuance as well as provider ID token verification. | Update ADR-003 consequences section if python-jose is removed (see Finding #7). |

---

### Security Checklist

- **JWT secret not hardcoded (config.py)**: PASS — `jwt_private_key` and `jwt_public_key` use `Field(...)` (required, no default), loaded exclusively via `pydantic-settings` from environment variables or `.env` file. No secrets are hardcoded.

- **OAuth2 state parameter specified in flows**: PASS — Architecture sequence diagram shows state generated and stored in Redis before the provider redirect; `GET /auth/callback/{provider}` OpenAPI spec marks `state` as `required: true`; ADR-003 explicitly lists state parameter as a requirement; constitution mandates it.

- **Refresh token rotation documented**: PASS — The Token Refresh Flow sequence diagram in `architecture.md` shows explicit rotation: `DEL old_hash` → generate new token → `STORE new_hash`. Theft detection (reuse of rotated token → revoke all user sessions) is fully specified. The token strategy table marks rotation as "Rotated on every use".

- **Admin endpoints require admin role**: PASS — `admin-api.yaml` has `security: [bearerAuth: []]` at the document level applied to all paths, and the info description states "All endpoints require a valid JWT with `admin` in the `grants` claim". `role-model.md` access matrix confirms admin-only for all `/admin/*` paths. Constitution mandates middleware-layer enforcement.

- **Per-app access check enforced**: PASS — Architecture documents the deny-by-default grant check; `grants[]` claim is embedded in JWT; SDK middleware checks `grants.includes(app_name)`; the flowchart in architecture.md makes the 403 path explicit. Role model confirms a user without a grant is refused even with a valid token.

- **No plaintext passwords in spec**: PASS — `data-model.md` stores `password_hash VARCHAR(72)` (bcrypt output); `spec.md` FR-003 specifies "bcrypt-hashed password"; `architecture.md` security summary specifies "bcrypt, cost ≥ 12"; `config.py` has no password field with a default value that could be stored in plaintext.

---

### Conclusion

**Changes requested** — 2 Blockers must be resolved before Phase 2 code merges.

**Blocker 1 (Finding #1)**: The OAuth post-login redirect places the access token in a URL
query parameter. This must be changed to a URL fragment (`#access_token=...`) or a
one-time-code exchange pattern before any OAuth flow is implemented. This is a
security-critical design flaw that will be expensive to retrofit after client apps are
integrated.

**Blocker 2 (Finding #2)**: Redis must be configured with a persistent volume in
docker-compose before any testing that relies on session state. Without it, every
restart during development will invalidate all tokens, making integration testing
unreliable and masking data-loss bugs.

All Major findings (3–6) should be resolved before the first Phase 2 milestone. Minor
findings are recommended but non-blocking. The architecture is otherwise solid, the ADRs
are thorough, and the security checklist passes completely.

---

## Phase 7 — Security Hardening & Final Sign-off

**Reviewer**: Architect (automated audit)
**Date**: 2026-05-10
**Status**: ✅ APPROVED

### Changes in Phase 7

- Added `SecurityHeadersMiddleware` (`backend/src/middleware/security_headers.py`) wired into `main.py`:
  - `Strict-Transport-Security: max-age=31536000; includeSubDomains`
  - `Content-Security-Policy`: strict `default-src 'none'` for API endpoints; relaxed only for `/docs`, `/redoc`, `/openapi.json`
  - `X-Frame-Options: DENY`
  - `X-Content-Type-Options: nosniff`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Permissions-Policy`: geolocation, microphone, camera, payment disabled
- Added `DISABLE_SWAGGER` env flag to strip Swagger UI in production (enforces strictest CSP)
- Updated `.env.example` with `DISABLE_SWAGGER=false` and clear token generation instructions
- Updated `docs/migration-guide.md`: all 6 client apps marked ✅ Complete

### Security Checklist — Phase 7 Audit Results

| # | Check | Result |
|---|-------|--------|
| 1 | JWT secret not hardcoded | ✅ PASS |
| 2 | OAuth2 state parameter validated (CSRF) | ✅ PASS |
| 3 | Refresh token rotation with theft detection | ✅ PASS |
| 4 | Admin endpoints require `admin` grant | ✅ PASS |
| 5 | Per-app access check enforced server-side | ✅ PASS |
| 6 | No plaintext password storage | ✅ PASS |
| 7 | Rate limiting on login + refresh | ✅ PASS |
| 8 | Open redirect protection | ✅ PASS |
| 9 | Security headers middleware wired | ✅ PASS |
| 10 | CORS uses allowlist, not wildcard | ✅ PASS |
| 11 | `api/admin.py` uses `Header(default=None)` | ✅ PASS |
| 12 | Theft detection calls `revoke_all_sessions()` | ✅ PASS |
| 13 | `token_service.py` uses authlib `jose_jwt` | ✅ PASS |

**All phases complete. No open blockers or majors.**
