# Code Review: Phases 2–5
Date: 2026-05-10
Reviewer: reviewer-agent
Overall verdict: CHANGES REQUESTED → **RESOLVED 2026-05-10 by architect**

## Security Checklist

- [x] Refresh token rotation with theft detection: PASS *(fixed: revoke_all_sessions called on reuse)*
- [x] HttpOnly cookie for refresh token: PASS
- [x] OAuth state stored in Redis (not memory): PASS
- [x] Fragment delivery of access token in OAuth callback: PASS
- [x] Admin routes check "admin" in grants[]: PASS *(fixed: Header annotation added)*
- [x] Rate limiting on /auth/login and /auth/refresh: PASS *(fixed: check_rate_limit added to /refresh)*

---

## Findings

### [BLOCKER] /auth/refresh has no rate limiting

**File**: `backend/src/api/auth.py:181-207`
**Problem**: The `POST /auth/refresh` endpoint calls `auth_service.refresh_tokens()` but never
calls `check_rate_limit()`. The OpenAPI spec (`docs/api-spec.yaml:166`) explicitly lists a `429`
response for `/auth/refresh`, and `config.py:47` defines `rate_limit_refresh_per_minute` (default
30), but neither is wired up. An attacker can pound the refresh endpoint to enumerate session
tokens or amplify DB load without any throttling.
**Fix**: Add a `check_rate_limit` call at the top of the `refresh` handler, keyed on
`f"rl:refresh:{client_ip}"` with `max_requests=settings.rate_limit_refresh_per_minute`, mirroring
the pattern already used on `local_login`.

---

### [BLOCKER] `require_admin` dependency always raises 401 — admin router is broken

**File**: `backend/src/api/admin.py:23-30`
**Problem**: The `require_admin` FastAPI dependency defined on lines 23–30 unconditionally raises
`HTTPException(status_code=401, ...)`. Every admin endpoint bypasses this dependency and instead
calls the module-level helper `_get_admin_user_id()` directly, passing
`authorization or ""`. The problem is that `authorization` is declared as a plain query/body
parameter (`authorization: str | None = None`), **not** read from the `Authorization` request
header. FastAPI will bind it from the query string, not the header. A request with
`Authorization: Bearer <jwt>` in the HTTP header will produce `authorization = None`, causing
`_get_admin_user_id("")` to always raise 401. All admin endpoints are therefore unreachable with
a correctly formed bearer token.
**Fix**: Replace the `authorization: str | None = None` parameter in every admin route handler
with `request: Request` and read `request.headers.get("authorization", "")`, or use a proper
FastAPI `Header` dependency: `authorization: str | None = Header(default=None)`.

---

### [BLOCKER] Token theft detection is incomplete — revoked-token reuse cannot be traced to a user

**File**: `backend/src/services/auth_service.py:154-158`
**Problem**: The Phase 1 review specified that reuse of an already-rotated token must revoke **all
sessions for the identified user**. The current implementation in `refresh_tokens()` covers the
case where `rt.revoked == True`, but when the token is not found at all (`rt is None`) — which is
the scenario for an opaque token that was already rotated and whose old hash no longer maps to any
record — the function raises `ValueError("Refresh token invalid or already used")` without
revoking anything. The old token hash is never stored after rotation (the `RefreshToken` row is
marked `revoked=True` but not deleted), so a genuinely absent hash means the token never existed,
but the revoked path (reuse of a known-rotated token) is handled correctly. However, the code
comment on line 156 says "Possible reuse attack — if we can identify the user, revoke all" and
then does not revoke all. For the `revoked=True` case the user **is** identifiable via `rt.user_id`
but `revoke_all_sessions` is never called.
**Fix**: When `rt` exists and `rt.revoked == True`, call
`await revoke_all_sessions(session, rt.user_id)` before raising, so the theft detection fires. Add
the user_id to the raised exception or log it for alerting.

---

### [BLOCKER] Admin Authorization header not read from HTTP header — `Header()` annotation missing

**File**: `backend/src/api/admin.py:63-73, 76-85, 89-97, 102-119, 122-135, 141-161`
**Problem**: This is the implementation detail of the BLOCKER above. Every route has `authorization: str | None = None` without `= Header(default=None)`. Without the `Header` annotation, FastAPI treats it as a query parameter. No standard HTTP client sends the Authorization token as a query parameter; they use the `Authorization` header. This means every admin endpoint silently fails authentication even when a valid JWT is supplied.
**Fix**: Change every `authorization: str | None = None` to `authorization: str | None = Header(default=None)` and add `from fastapi import Header` to the imports.

---

### [MAJOR] `redirect_uri` passed to OAuth callback is not validated — open redirect

**File**: `backend/src/api/auth.py:169-171`
**Problem**: `redirect_after` is read from Redis state (stored at OAuth initiation) without any
allowlist or origin validation. The OAuth initiation endpoint (`oauth_login`, line 129) passes
`redirect_uri` from the query string directly into `get_authorization_url()`, which stores it in
Redis. The callback at line 169 then uses it as-is in a `302 Location`. Any value the initiating
request supplies — including `javascript:` URIs, `data:` URIs, or external attacker-controlled
domains — will be followed by the browser after authentication.
**Fix**: Validate `redirect_after` against an allowlist of known origins (e.g.
`settings.allowed_origins`). Reject or fall back to `settings.app_base_url` if the value is not
on the list.

---

### [MAJOR] `login_failed` audit event leaks the attempted email address

**File**: `backend/src/api/auth.py:106`
**Problem**: `_log_event(session, "login_failed", metadata={"email": body.email})` writes the
attempted email into the `audit_events.metadata` JSONB column. For a brute-force attack targeting
a user account, this creates a high-volume audit trail containing the target's email address. The
audit log is queryable by admins via `/admin/audit` and, if the DB is ever breached, maps failed
login attempts directly to user email addresses.
**Fix**: Hash or omit the email from the metadata, or store only a non-reversible identifier
(e.g., SHA-256 of the email). Alternatively, store only a flag indicating the login type (local
vs OAuth) without the address.

---

### [MAJOR] JWKS cache is not thread-safe — module-level mutable globals in sync context

**File**: `sdk/python/auth_client/jwks_cache.py:9-10, 22-43`
**Problem**: `_cache` and `_cache_fetched_at` are module-level mutable globals. `get_key()` uses
them with a check-then-act pattern (lines 33–37) that is not atomic. In a multi-threaded WSGI
server (e.g. gunicorn with sync workers), two threads can simultaneously find the cache stale,
both issue HTTP fetches to the JWKS endpoint, and both overwrite `_cache`. This is a TOCTOU race.
While it does not cause incorrect validation (both fetches return the same keys), it causes
unnecessary external requests and could be a denial-of-service amplifier under key rotation.
**Fix**: Wrap the cache refresh block in a `threading.Lock`. Alternatively, refactor to use a
class-based cache that the caller instantiates per-process, which eliminates the global state
issue.

---

### [MAJOR] JS middleware error code comparison uses wrong case — `NO_GRANT` vs `no_grant`

**File**: `sdk/js/src/middleware.ts:47`, `sdk/js/src/errors.ts:14`
**Problem**: The `createMiddleware` function checks `err.code === 'NO_GRANT'` to decide whether
to return 403 vs 401. But `NoGrantError` is constructed with `code: 'NO_GRANT'` in `errors.ts`
(line 14, uppercase). Meanwhile the Python SDK uses lowercase `code="no_grant"`. The JS SDK is
internally consistent — `NO_GRANT` is set and checked correctly — but the codes are inconsistent
between JS and Python SDKs, making cross-SDK error handling harder. More critically: if the code
string ever changes in `errors.ts` (e.g. to match the Python SDK), the middleware check silently
breaks and all grant rejections fall through to 401 instead of 403.
**Fix**: Define error codes as exported constants (e.g. `export const ERR_NO_GRANT = 'NO_GRANT'`)
and reference the constant everywhere instead of inline strings, eliminating the fragile string
comparison. Also decide on a canonical casing convention across both SDKs.

---

### [MAJOR] `grant_service.list_users` only returns active users — inactive users invisible to admin

**File**: `backend/src/services/grant_service.py:31`
**Problem**: `list_users()` filters on `User.is_active == True`. This means deactivated users
never appear in the admin user list. An admin cannot see, investigate, or reactivate a deactivated
user through the UI. The OpenAPI spec (`docs/api-spec.yaml`) does not specify this filter — the
`GET /admin/users` description says "List all users (paginated)" without any mention of filtering
inactive users. The schema includes `is_active: boolean` in `UserSummary`, implying both states
should be returnable.
**Fix**: Remove the `is_active` filter from the base query, or add an optional `?is_active=true`
query parameter so admins can choose. The OpenAPI spec should be updated to document this
behaviour.

---

### [MAJOR] `revoke_all_user_sessions` scans Redis with `SCAN` on pattern `rt:{user_id}:*` — but tokens are not stored under this key pattern

**File**: `backend/src/services/grant_service.py:189-191`
**Problem**: The function scans Redis for keys matching `rt:{user_id}:*` and deletes them.
However, nothing in the codebase ever writes a Redis key with this pattern. Refresh tokens are
stored only in the `refresh_tokens` PostgreSQL table (see `auth_service.py:134`). The OAuth state
keys use the prefix `oauth_state:` (see `oauth_service.py:36`). The Redis scan therefore always
matches zero keys and silently does nothing to Redis. The function revokes DB rows correctly but
the Redis no-op means this is dead code that gives a false sense of completeness.
**Fix**: Either (a) store refresh token hashes in Redis on issuance (with the `rt:{user_id}:{hash}`
key pattern) in addition to Postgres, and then this scan becomes meaningful, or (b) remove the
Redis scan and document that Redis cleanup for refresh tokens is not required because Redis is not
used for refresh token storage (tokens are authoritative in Postgres only).

---

### [MINOR] `decode_access_token` in `token_service.py` imports `json` inside function

**File**: `backend/src/services/token_service.py:76`
**Problem**: `import json as _json` is placed inside `decode_access_token()` and also inside
`_serialize_payload()` (line 123). Python caches module imports so this is not a correctness
issue, but it is unconventional — imports should be at module top-level. It also makes the
function's dependencies less obvious.
**Fix**: Move both `import json` statements to the top of `token_service.py` alongside the other
imports.

---

### [MINOR] `_refresh_cookie_kwargs` sets `secure=False` on localhost — acceptable but fragile

**File**: `backend/src/api/auth.py:46`
**Problem**: `secure: not settings.app_base_url.startswith("http://localhost")` sets the cookie
`Secure` flag based on the URL prefix. This means running a dev server on `http://127.0.0.1:8000`
(not `localhost`) will set `Secure=True` on a non-TLS connection, causing the browser to discard
the cookie silently. This is a subtle environment-dependent bug.
**Fix**: Add `"http://127.0.0.1"` to the check, or introduce a dedicated `debug: bool` config field
that controls secure-cookie behaviour, or always set `Secure=True` and document that local
development must use a TLS proxy (e.g. `mkcert`).

---

### [MINOR] `get_db()` is a generator but typed as returning `AsyncSession`

**File**: `backend/src/db/base.py:13-15`
**Problem**: `get_db` is an `async def` that yields, making it an async generator. Its return type
annotation is `AsyncSession` (missing `AsyncGenerator` wrapping). This is a minor type annotation
inaccuracy that can confuse type checkers and IDEs.
**Fix**: Annotate as `AsyncGenerator[AsyncSession, None]` and add
`from typing import AsyncGenerator` to the import block.

---

### [MINOR] `password_hash` column length may be insufficient for future algorithm migration

**File**: `backend/alembic/versions/0001_initial_schema.py:36`
**Problem**: `password_hash VARCHAR(72)` exactly fits a bcrypt output (60 chars for `$2b$...` +
some padding). If the hashing algorithm is ever upgraded (e.g., argon2id), the column will be too
short. `72` is also the bcrypt input truncation limit, not the output length — bcrypt output is
60 characters. The column length is technically fine for bcrypt but is documented misleadingly.
**Fix**: Increase to `VARCHAR(255)` to allow future algorithm upgrades without a migration, and
add a comment clarifying the current algorithm.

---

### [MINOR] `_log_event` in `auth.py` is called after `session.commit()` inside `login_local` — double commit risk

**File**: `backend/src/api/auth.py:53-69`, `backend/src/services/auth_service.py:59`
**Problem**: `auth_service.login_local()` calls `issue_tokens()` which calls `session.commit()`.
Then the `local_login` route handler catches a `ValueError` and calls `_log_event()` which also
calls `session.commit()`. These share the same `AsyncSession`. Calling commit twice on a session
that has already committed is generally safe with SQLAlchemy asyncio, but calling `session.add()`
then `session.commit()` after the session has already been flushed and committed can produce
unexpected behaviour in edge cases (e.g., if the session expired objects). This is not a
correctness bug in the happy path but is fragile.
**Fix**: Ensure the audit write happens within the same DB session transaction as the login result,
or use a separate session for audit writes.

---

### [MINOR] `auth.ts` decodes JWT payload client-side without signature verification

**File**: `frontend/src/services/auth.ts:16-17`
**Problem**: `setToken` base64-decodes the JWT payload to read `grants` and set `isAdmin`. This
is used purely for UI rendering (showing/hiding admin nav items) and not for access control, so
the lack of signature verification is not a security issue. However, if a bug causes a tampered
token to reach this code, the UI could render incorrect capabilities. A comment explaining that
this is UI-only and that the server enforces real access control would prevent future confusion.
**Fix**: Add a comment clarifying that this decode is for UI rendering only, and that access
control is enforced server-side and by the SDK middleware.

---

### [MINOR] `_get_admin_user_id` is a private helper called from route handlers — internal coupling

**File**: `backend/src/api/admin.py:33-44`
**Problem**: The broken `require_admin` FastAPI dependency (see BLOCKER above) was presumably
intended to replace the manual `_get_admin_user_id()` calls in each handler. Leaving both the
broken dependency and the manual helper in the same file creates confusion about which pattern
is authoritative. The `require_admin` function has a comment "Will be overridden by middleware
approach below" which is stale and misleading — it is never overridden.
**Fix**: Once the `Header` annotation fix is applied, remove the broken `require_admin` function
or complete it. Consolidate to a single auth-checking pattern for the admin router.

---

### [MINOR] `AuditLog.tsx` `ACTION_OPTIONS` list is missing `user_deactivated`

**File**: `frontend/src/pages/AuditLog.tsx:5-12`
**Problem**: `ACTION_OPTIONS` (the filter dropdown) does not include `user_deactivated`, but
`ACTION_LABELS` does include it (line 22). This means `user_deactivated` events will appear in
the unfiltered log with a correct label, but the admin cannot filter the log to show only
deactivation events.
**Fix**: Add `'user_deactivated'` to `ACTION_OPTIONS`.

---

### [MINOR] `token_service.py` uses `JsonWebSignature` for JWT — non-standard for JWT (should use `JsonWebToken`)

**File**: `backend/src/services/token_service.py:63-65, 74-78`
**Problem**: The code uses `authlib.jose.JsonWebSignature` (JWS) for creating and verifying JWTs.
While JWTs are technically JWSes with a JSON payload, authlib provides `authlib.jose.jwt` which
handles the standard JWT encoding/decoding (including registered claims like `exp`, `iat`, `sub`)
natively. Using the raw JWS layer means the code manually serialises the payload to JSON bytes and
manually checks `exp`. Using `authlib.jose.jwt.encode/decode` would handle these concerns
automatically and reduce risk of manual encoding errors.
**Fix**: Replace `JsonWebSignature().serialize_compact(...)` with `jwt.encode(header, payload, key)`
and `JsonWebSignature().deserialize_compact(...)` with `jwt.decode(token, key)`.

---

## Summary

**6 issues require resolution before shipping.** Two are straightforward infrastructure fixes
(rate limiting on refresh, Header annotation) that have a high fix-to-risk ratio. One is a
serious security design gap (open redirect). The theft detection incomplete-revocation and the
Redis dead-code scan are correctness bugs in the session management core. The inactive-user
visibility gap is a functional gap in admin operations.

| Severity | Count | Status |
|----------|-------|--------|
| BLOCKER | 4 | Must fix before merge |
| MAJOR | 5 | Should fix before first external users |
| MINOR | 8 | Fix at earliest convenience |

**Security checklist result**: 5/6 PASS. The one partial is rate limiting on /auth/refresh, which
is a BLOCKER.

**Positives worth noting**:
- Fragment delivery of the OAuth access token (`#access_token=...`) correctly addresses the Phase 1
  blocker from the previous review.
- The refresh token cookie is HttpOnly with correct Path scoping to `/auth/refresh`.
- OAuth state + PKCE verifier is stored in Redis with a 10-minute TTL and deleted on use (one-time).
- The admin JWT check (`"admin" not in payload.get("grants", [])`) is correct once the Authorization
  header is read properly.
- The frontend stores the access token in Zustand in-memory state only (no localStorage), which is
  the correct secure approach for an SPA.
- bcrypt cost factor 12 is used throughout; argon2 upgrade path is easy.
- The Python SDK's `validate_token` correctly checks `exp` and the `grants` claim in the right order.
