# ADR-002: JWT Token Strategy

**Status**: Accepted
**Date**: 2026-05-09
**Deciders**: Architect Agent

---

## Context

We need a session mechanism that allows client applications to verify a user's
identity and app-access grants **without a network call to the auth service**.
The strategy must also support immediate revocation (e.g., admin revokes access)
within an acceptable time window.

## Options Considered

### Option A — Opaque session tokens (server-side sessions)
Tokens are random strings; client apps look them up against the auth service on
every request.

**Pros**: Instant revocation; no claims drift.
**Cons**: Every request incurs a network round-trip to the auth service; auth service
becomes a synchronous dependency for every client app request — a single outage takes
all apps offline.

### Option B — HS256 JWT (symmetric signing)
Access tokens are JWTs signed with a shared secret. Client apps verify the
signature using the same secret.

**Pros**: Stateless client verification.
**Cons**: Shared secret must be distributed to every client app and rotated
coordinatedly — one compromised app leaks the signing key for all tokens.

### Option C — RS256 JWT (asymmetric signing) + JWKS endpoint
Access tokens are JWTs signed with the auth service's **private** RSA key.
Client apps download the **public** key once from `/.well-known/jwks.json` and
cache it. No secret distribution needed.

**Pros**: Stateless verification (no network on hot path); public key can be
safely embedded in any client app; standard OIDC-compatible pattern; key rotation
via `kid` without client coordination.
**Cons**: Not instantly revocable — revoked access persists until token expiry.

### Option D — RS256 JWT (access) + opaque refresh token (server-side)
Short-lived RS256 JWT for client verification; long-lived opaque token stored only
in Redis for renewal. Refresh rotation with theft detection.

**Pros**: Combines stateless verification with refresh revocability; compromise
surface limited (short TTL); refresh token theft detected via reuse detection.
**Cons**: Slightly more complex implementation; access revocation still has a TTL
window (≤ 15 min).

## Decision

**Option D — RS256 JWT (access token) + opaque refresh token (Redis)**.

- Access token TTL: **15 minutes** (acceptable revocation latency for family apps)
- Refresh token TTL: **30 days** with rotation on every use
- Signing algorithm: **RS256** (PKCS#8 RSA-2048 key pair)
- Public key served at `/.well-known/jwks.json` in JWK Set format
- `kid` (key ID) in every JWT header for zero-downtime key rotation
- Refresh token reuse → revoke all sessions for that user (token theft detection)

## Consequences

- Client apps cache the JWKS public key (5-min TTL + re-fetch on `kid` mismatch)
- Access revocation window: up to 15 minutes (acceptable per SC-005)
- Key rotation: generate new key pair, add new entry to JWKS with new `kid`,
  start signing new tokens with new `kid`; old `kid` accepted for one TTL window
- Refresh tokens stored as `sha256(opaque_token)` in Redis under key
  `rt:{user_id}:{token_id}` for efficient wildcard deletion on user session revocation
