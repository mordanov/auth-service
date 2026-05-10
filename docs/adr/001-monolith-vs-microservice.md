# ADR-001: Monolith vs Microservice Architecture

**Status**: Accepted
**Date**: 2026-05-09
**Deciders**: Architect Agent

---

## Context

The centralised auth service must serve six existing client applications. We need
to decide whether to build it as a single deployable unit or as a set of small,
independently-deployable services (e.g., separate services for OAuth, JWT issuance,
user management, admin API).

## Decision Drivers

- Team size: small (2–3 developers), family-scale deployment
- Client applications: 6 apps, ~10 active users, low traffic (< 100 req/min peak)
- Operational complexity: single host Docker deployment
- Time-to-value: need to replace six auth systems quickly
- Future flexibility: keep options open for splitting later if needed

## Options Considered

### Option A — Single monolithic FastAPI application
All auth logic (OAuth, JWT, user CRUD, admin API) lives in one process, one
codebase, one deployment unit.

**Pros**: Simple deployment, single database connection pool, easy local dev,
minimal infrastructure, fast iteration, low operational overhead.

**Cons**: All features must be deployed together; one bug can affect all flows.

### Option B — Microservices (auth-core, admin-service, token-service)
Split into: token-service (JWT issuance/JWKS), oauth-service (provider flows),
user-service (user CRUD + grants), admin-service (admin UI backend).

**Pros**: Independent deployability, clear team ownership, isolated failure domains.

**Cons**: 3–4x deployment complexity, inter-service latency, distributed tracing
overhead, complex local dev (multiple docker-compose services), overkill for
10-user family deployment.

### Option C — Modular monolith (modules within one process, clear boundaries)
Single FastAPI process with strict internal module boundaries: `auth/`, `admin/`,
`tokens/`, `users/` — each a Python module with its own service layer, models,
and routes, no cross-module direct imports (go through service interfaces).

**Pros**: Preserves all monolith operational advantages while maintaining the
code boundaries needed to extract services later if required.

**Cons**: Requires discipline to maintain boundaries; slightly more upfront structure.

## Decision

**Option C — Modular monolith** (implemented as a structured FastAPI application).

The service is organised as: `api/` (routes), `services/` (business logic),
`models/` (ORM entities), `middleware/` (cross-cutting concerns). Modules do not
import directly from each other's internals; they call service functions.

This gives us monolith simplicity today with a clear migration path to
microservices if traffic or team size demands it.

## Consequences

- Single docker-compose service for the backend
- One PostgreSQL database, one Redis instance
- All tests run in one `pytest` suite
- Deployment is `docker build + docker push + docker run`
- If a future service split is needed, the modular boundaries make extraction straightforward
