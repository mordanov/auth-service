# Role Model & Access Matrix

**Version**: 1.0.0 | **Date**: 2026-05-09

---

## Role Definitions

### `user`
Standard access role. A user with this role on a given application can read and
write within that application according to the application's own business logic.
The auth service does not enforce application-level permissions beyond granting
entry — per-feature authorisation is the application's responsibility.

### `admin`
Platform-wide management role. An admin can:
- Access the auth service admin panel at `/admin/*`
- List, search, and view all registered users
- Assign or revoke per-application grants for any user
- View the full audit log

An admin's JWT `grants` array always contains `"admin"` in addition to any
application-level grants they hold.

> **Important**: The `admin` role is a platform concept, not an application concept.
> An admin does not automatically have elevated privileges *inside* a client app
> (e.g., budget-site). Application-level admin roles remain the app's responsibility.

---

## Access Matrix

| Resource | Anonymous | `user` (no grant) | `user` (with app grant) | `admin` |
|----------|:---------:|:-----------------:|:-----------------------:|:-------:|
| `GET /auth/login` | ✅ | ✅ | ✅ | ✅ |
| `POST /auth/login` | ✅ | ✅ | ✅ | ✅ |
| `GET /auth/callback/:provider` | ✅ | ✅ | ✅ | ✅ |
| `POST /auth/refresh` | ✅ (refresh cookie required) | ✅ | ✅ | ✅ |
| `POST /auth/logout` | ✅ (refresh cookie required) | ✅ | ✅ | ✅ |
| `GET /.well-known/jwks.json` | ✅ | ✅ | ✅ | ✅ |
| **Client app access** | ❌ | ❌ | ✅ | ✅ |
| `GET /admin/users` | ❌ | ❌ | ❌ | ✅ |
| `GET /admin/users/:id` | ❌ | ❌ | ❌ | ✅ |
| `POST /admin/grants` | ❌ | ❌ | ❌ | ✅ |
| `DELETE /admin/grants/:id` | ❌ | ❌ | ❌ | ✅ |
| `GET /admin/audit` | ❌ | ❌ | ❌ | ✅ |

---

## Per-Application Grant Matrix

The table below shows the initial access configuration after deployment.
All access is deny-by-default; grants must be explicitly created by an admin.

| Application | Grant required | Roles supported | Notes |
|-------------|:--------------:|:---------------:|-------|
| `budget-site` | Yes | `user` | Family budget tracker |
| `family-admin-routine` | Yes | `user`, `admin` | Family admin tool — platform admin needed |
| `family-archive` | Yes | `user` | Private family archive |
| `news-site` | Yes | `user` | News aggregator |
| `poetry-site` | Yes | `user` | Poetry collection viewer |
| `reminders-app` | Yes | `user` | Reminders / task tracker |
| `admin` (auth panel) | Yes | `admin` | Special sentinel name for the auth admin panel |

---

## JWT `grants` Claim Examples

**Regular user with access to budget-site and news-site**:
```json
{
  "sub": "a1b2c3d4-...",
  "grants": ["budget-site", "news-site"],
  "exp": 1715000000
}
```

**Admin user**:
```json
{
  "sub": "e5f6g7h8-...",
  "grants": ["admin", "budget-site", "family-admin-routine", "family-archive"],
  "exp": 1715000000
}
```

**User with no grants yet (just registered)**:
```json
{
  "sub": "i9j0k1l2-...",
  "grants": [],
  "exp": 1715000000
}
```

---

## Grant Lifecycle

```
[User registered] → grants = []
       │
       ▼
[Admin grants budget-site/user]
       │
       ▼
[User logs in → JWT includes "budget-site"]
       │
       ▼
[Admin revokes budget-site grant]
       │
       ▼
[Next token refresh → JWT no longer includes "budget-site"]
[Existing access token valid until expiry (≤15 min)]
```

---

## Future Extensibility

The role model is intentionally minimal for v1. Future extensions:

1. **Per-application admin role**: An app-specific `budget-site:admin` grant could
   be added to the AppGrant `role` enum without changing the JWT structure — the
   `grants` claim would simply include `"budget-site:admin"` instead of `"budget-site"`.

2. **Read-only role**: A `viewer` role can be added to the AppGrant role enum and
   included as a claim variant (e.g., `"news-site:viewer"`).

3. **Group memberships**: A future `Group` entity could aggregate grants — assigning
   a user to a group would inherit all of the group's grants at token refresh time.
