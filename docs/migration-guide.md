# Migration Guide: Integrating Client Apps with the Auth Service

This guide explains how to migrate each existing client application from its own
auth implementation to the centralised auth service. Follow this guide for each app.

---

## Overview

The migration has three steps for each app:
1. **Install** the `auth-client` SDK (Python) or `@auth-service/client` (JS)
2. **Configure** the middleware (app name + JWKS URL)
3. **Remove** all existing auth code (login views, password storage, session middleware)

No existing user accounts need to be migrated — users re-authenticate on first
login via the new flow. The auth service creates a new User record on first successful
OAuth or local login.

---

## Pre-Migration Checklist

- [ ] Auth service is deployed and reachable (`AUTH_SERVICE_URL`)
- [ ] JWKS endpoint responds: `GET $AUTH_SERVICE_URL/.well-known/jwks.json`
- [ ] Admin has created an AppGrant for this app for all relevant users
- [ ] `.env` on the client app includes `AUTH_SERVICE_URL` and `AUTH_APP_NAME`

---

## Python Apps (FastAPI / Django)

### 1. Install SDK

```bash
pip install auth-client==0.1.0
# or in pyproject.toml:
# auth-client = "==0.1.0"
```

### 2. FastAPI Integration

```python
# main.py
from fastapi import FastAPI
from auth_client import AuthMiddleware

app = FastAPI()

app.add_middleware(
    AuthMiddleware,
    app_name=os.environ["AUTH_APP_NAME"],     # e.g. "budget-site"
    jwks_url=os.environ["AUTH_SERVICE_URL"] + "/.well-known/jwks.json",
)
```

Access user info in route handlers:
```python
from fastapi import Request

@app.get("/api/budgets")
async def get_budgets(request: Request):
    user_id = request.user.sub          # UUID string
    user_grants = request.user.grants   # list of app names
    ...
```

Handle 401/403 redirects in frontend (or add a redirect middleware):
```python
from fastapi.responses import RedirectResponse
from auth_client import AuthError

@app.exception_handler(AuthError)
async def auth_error_handler(request, exc):
    login_url = os.environ["AUTH_SERVICE_URL"] + "/auth/login"
    return RedirectResponse(url=f"{login_url}?redirect_uri={request.url}")
```

### 3. Django Integration

```python
# settings.py
MIDDLEWARE = [
    ...
    "auth_client.DjangoAuthMiddleware",
]

AUTH_CLIENT_APP_NAME = "news-site"
AUTH_CLIENT_JWKS_URL = os.environ["AUTH_SERVICE_URL"] + "/.well-known/jwks.json"
```

Access in views:
```python
def my_view(request):
    user_id = request.auth_user.sub
```

### 4. Remove Old Auth Code

Delete or comment out:
- Login views (`/login`, `/register`, `/logout`)
- Password hashing utilities
- Session middleware (if replaced by JWT middleware)
- `AUTH_*` env vars that pointed to old auth DB
- User model fields: `password`, `password_hash`, `session_token`, etc.

Keep:
- Your app's own user profile fields (name, preferences, etc.)
- Foreign key references to `user_id` (now the UUID from the auth service JWT `sub` claim)

---

## JavaScript / TypeScript Apps (Express / Next.js)

### 1. Install SDK

```bash
npm install @auth-service/client@0.1.0
```

### 2. Express Integration

```typescript
import express from 'express'
import { createMiddleware } from '@auth-service/client'

const app = express()

app.use(createMiddleware({
  appName: process.env.AUTH_APP_NAME!,
  jwksUrl: process.env.AUTH_SERVICE_URL + '/.well-known/jwks.json',
}))
```

### 3. Next.js Middleware

```typescript
// middleware.ts
import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'
import { validateToken } from '@auth-service/client'

export async function middleware(request: NextRequest) {
  const token = request.headers.get('authorization')?.replace('Bearer ', '')
  if (!token) {
    return NextResponse.redirect(new URL('/auth/login', process.env.AUTH_SERVICE_URL))
  }
  try {
    await validateToken(token, process.env.AUTH_APP_NAME!, 
      process.env.AUTH_SERVICE_URL + '/.well-known/jwks.json')
    return NextResponse.next()
  } catch {
    return NextResponse.redirect(new URL('/auth/login', process.env.AUTH_SERVICE_URL))
  }
}

export const config = { matcher: ['/app/:path*', '/api/:path*'] }
```

---

## Environment Variables (add to each client app)

```dotenv
# Required
AUTH_SERVICE_URL=https://auth.example.com
AUTH_APP_NAME=budget-site   # Must match the AppGrant app_name in the auth service

# Remove after migration
# OLD_DB_URL=...
# SESSION_SECRET=...
```

---

## Per-App Migration Status

| App | Type | Status | Notes |
|-----|------|--------|-------|
| `budget-site` | Python/FastAPI | ✅ Complete | AuthMiddleware + auth.py stubbed; TODO(data-migration) for UUID↔int user_id |
| `news-site` | Python/FastAPI | ✅ Complete | AuthMiddleware; admin grant check via `current_user.grants` |
| `poetry-site` | Python/FastAPI | ✅ Complete | Per-route `validate_token()` (public routes must not block anonymous visitors) |
| `family-archive` | Python/FastAPI | ✅ Complete | AuthMiddleware; session/cookie auth removed; TODO(data-migration) for user_id |
| `family-admin-routine` | Python/FastAPI | ✅ Complete | AuthMiddleware; login/register removed |
| `reminders-app` | Python/FastAPI | ✅ Complete | AuthMiddleware; timezone hardcoded to UTC (TODO: fetch per-user setting) |

---

## Rollback Plan

If migration causes issues for a specific app, temporarily disable the auth
middleware and fall back to the old auth system. Keep the old auth code in a
feature branch until all apps have been validated in production.

The auth service and client apps are deployed independently; rolling back one app
does not affect others.

---

## Post-Migration Validation

For each migrated app:

1. Log in as an existing user — verify access works
2. Log in as a user with no AppGrant — verify 403 / redirect
3. Revoke an AppGrant from admin panel — wait 15 min — verify access is blocked
4. Confirm no auth-related code remains: `grep -r "password_hash\|login_required\|session" app/`
5. Confirm no auth endpoints remain: `grep -r "@app.route.*login\|@app.route.*logout" app/`
