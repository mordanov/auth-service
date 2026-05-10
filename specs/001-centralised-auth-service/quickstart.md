# Quickstart: Centralised Auth Service

## Prerequisites

- Docker & Docker Compose
- Python 3.12 (for local dev without Docker)
- An RSA-2048 key pair (instructions below)
- Google OAuth 2.0 credentials (optional for local dev)

---

## 1. Generate RSA Key Pair

```bash
# Generate private key
openssl genrsa -out private.pem 2048

# Extract public key
openssl rsa -in private.pem -pubout -out public.pem

# Base64-encode for .env (single line, no newlines)
JWT_PRIVATE_KEY=$(cat private.pem | base64 | tr -d '\n')
JWT_PUBLIC_KEY=$(cat public.pem | base64 | tr -d '\n')
```

---

## 2. Configure `.env`

Copy `.env.example` to `.env` and fill in values:

```bash
cp .env.example .env
```

Minimum required for local dev:

```dotenv
POSTGRES_DB=authdb
POSTGRES_USER=authuser
POSTGRES_PASSWORD=changeme

DATABASE_URL=postgresql+asyncpg://authuser:changeme@postgres:5432/authdb
REDIS_URL=redis://redis:6379/0

JWT_PRIVATE_KEY=<base64 of private.pem>
JWT_PUBLIC_KEY=<base64 of public.pem>
JWT_KEY_ID=auth-key-1

SEED_ADMIN_EMAIL=admin@example.com
SEED_ADMIN_PASSWORD=supersecret123
```

---

## 3. Start All Services

```bash
docker-compose up --build
```

Services:
- `http://localhost:8000` — Auth API
- `http://localhost:3000` — Admin panel
- `http://localhost:8000/docs` — Swagger UI

---

## 4. Run Database Migration

```bash
docker-compose exec auth-backend alembic upgrade head
```

The seed admin account (`SEED_ADMIN_EMAIL`) is created automatically on first startup.

---

## 5. Verify JWKS Endpoint

```bash
curl http://localhost:8000/.well-known/jwks.json | python3 -m json.tool
```

---

## 6. Test Local Login

```bash
curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"supersecret123"}' | python3 -m json.tool
```

Expected: `{"access_token": "eyJ...", "token_type": "Bearer", "expires_in": 900}`

---

## 7. Decode the JWT (verify grants)

```bash
ACCESS_TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"supersecret123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Decode payload (no signature verification — for debugging only)
echo $ACCESS_TOKEN | cut -d. -f2 | base64 -d 2>/dev/null | python3 -m json.tool
```

Expected payload:
```json
{
  "sub": "<user-uuid>",
  "grants": ["admin"],
  "iat": 1715000000,
  "exp": 1715000900
}
```

---

## 8. Access the Admin Panel

Open `http://localhost:3000/admin` in your browser.
Log in with `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD`.

---

## 9. Integrate a Client App (Python / FastAPI)

### Install the SDK

```bash
# From the auth-service repo root (local dev)
pip install -e ./sdk/python

# Or from published package (production)
pip install auth-client==0.1.0
```

### Wire the middleware

```python
# In your FastAPI app's main.py
from fastapi import FastAPI
from auth_client import AuthMiddleware

app = FastAPI()
app.add_middleware(
    AuthMiddleware,
    app_name="budget-site",                          # must match the grant app_name
    jwks_url="http://localhost:8000/.well-known/jwks.json",
)
```

### Grant the app to a user

Log in to the admin panel (`http://localhost:3000/admin`), find the user, and grant
`budget-site` access. The user's next token refresh will include `"budget-site"` in
the `grants` claim.

### Test end-to-end

```bash
# 1. User logs in to the auth service
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"userpass"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2. User calls your app with the token
curl -H "Authorization: Bearer $TOKEN" http://localhost:8001/api/budgets
# → 200 if user has budget-site grant
# → 403 if no grant
```

---

## Validation Checklist

- [ ] JWKS endpoint returns RSA public key
- [ ] Local login returns a valid RS256 JWT
- [ ] JWT contains correct `sub` and `grants` claims
- [ ] Admin panel accessible with seed admin credentials
- [ ] Non-admin user gets 403 on `/admin/*` endpoints
- [ ] Refresh endpoint rotates the refresh token cookie
- [ ] Reusing a rotated refresh token returns 401
- [ ] Client app middleware returns 403 when user has no grant for that app
