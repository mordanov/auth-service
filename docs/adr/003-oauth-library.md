# ADR-003: OAuth 2.0 Library Selection

**Status**: Accepted
**Date**: 2026-05-09
**Deciders**: Architect Agent

---

## Context

We need a Python library to handle the OAuth 2.0 / OIDC authorisation code flow
for Google and Microsoft providers. The library must support PKCE, state parameter,
OIDC discovery (`.well-known/openid-configuration`), and async operation within FastAPI.

## Options Considered

### Option A — `python-social-auth` (social-core + social-app-fastapi)
Mature library with 30+ provider integrations.

**Pros**: Wide provider support, battle-tested.
**Cons**: Django-centric architecture; FastAPI adapter is community-maintained and
lags behind; opinionated about user model and session storage; adds heavy dependencies
(social-core pulls in six, requests-oauthlib); does not natively support asyncio.

### Option B — `authlib`
RFC-compliant OAuth 2.0 / OIDC implementation; explicit async support via
`httpx`-backed `AsyncOAuth2Client`; built-in PKCE, state, nonce, JWKS verification.

**Pros**: RFC 6749/7636/7517/8414 compliant; async-native; zero framework assumptions;
supports OIDC discovery; actively maintained; used in production FastAPI applications.
**Cons**: Lower-level than python-social-auth; requires more explicit wiring of
state storage, callback handling, etc. (which we control via Redis anyway).

### Option C — Roll our own with `httpx` + `python-jose`
Implement the OAuth 2.0 authorisation code flow directly using `httpx` for HTTP
and `python-jose` for token verification.

**Pros**: Minimum dependencies; full control.
**Cons**: High implementation risk (CSRF, PKCE, nonce, ID token verification,
provider discovery all require careful implementation); not worth the risk for
a security-critical component.

## Decision

**Option B — `authlib 1.3`**.

`authlib` provides exactly what we need:
- `AsyncOAuth2Client` for async PKCE + state flows
- OIDC discovery via `OpenIDConnect` integration
- Built-in ID token verification (nonce, audience, issuer checks)
- No framework coupling — wires directly into FastAPI dependency injection

Google and Microsoft provider configs:
- Google: `https://accounts.google.com/.well-known/openid-configuration`
- Microsoft: `https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration`

## Consequences

- `authlib>=1.3` added to `backend/pyproject.toml`
- OAuth state stored in Redis with 10-minute TTL (key: `oauth_state:{state_value}`)
- PKCE code verifier stored alongside state in Redis
- ID token nonce stored in Redis, verified on callback
- **JWT issuance also uses `authlib.jose`** (`JsonWebSignature`, `JsonWebKey`) rather
  than a separate `python-jose` dependency. This keeps a single JWT library in the
  dependency tree, reduces attack surface, and avoids the algorithm-confusion CVEs
  present in `python-jose` (effectively unmaintained since 2022). `python-jose` is
  **not** included in `pyproject.toml`.
