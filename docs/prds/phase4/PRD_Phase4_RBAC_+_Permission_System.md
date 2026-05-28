# PRD — Phase 4: RBAC + Permission System

**Product:** Arcana — AI-Powered Developer Onboarding Platform
**Phase:** 4 of Tier 1
**Version:** 1.0
**Date:** March 2026
**LLM Provider:** Gemini APIs
**Depends on:** Phases 1–3 (complete)
**Related:** [Arcana Limitations & Design Decisions Log](./Arcana_Limitations_and_Design_Decisions.md) — entries L4.1 through L4.5

---

## 1. Overview

This document defines the requirements for the RBAC (Role-Based Access Control) and permission system — the security layer that governs who can see what within Arcana's knowledge base. This is not a feature bolted on after the fact; it is a foundational constraint that shapes how every query flows through the system.

Arcana ingests proprietary source code and internal documentation. Different developers have different access levels — a junior frontend developer should not receive answers referencing infrastructure secrets, a contractor should not see financial service internals, and a viewer should not be able to modify system configuration. The RBAC system enforces these boundaries at the retrieval level, ensuring the LLM never sees content the user is not authorized to access.

By the end of this phase, every query will pass through a permission gate before reaching the knowledge store, and every admin action will be gated by role verification.

---

## 2. Objectives

- Define a role hierarchy with clear capability boundaries
- Build a permission matrix that maps users to the data sources and content scopes they can access
- Implement pre-retrieval filtering that applies permissions to both vector search (ChromaDB) and keyword search (FTS5, for Phase 5 hybrid search)
- Add permission validation middleware to every API endpoint
- Create admin endpoints for user, role, and scope management
- Log every query and admin action to the audit trail
- Support sensitive content tagging so admins can restrict specific repos or pages beyond the default role-based rules

---

## 3. Scope

### 3.1 In scope

- Role definitions with hierarchical inheritance
- User-to-data-source permission mapping (CRUD)
- Pre-retrieval filter generation for ChromaDB (where clause)
- Pre-retrieval filter generation for SQLite FTS5 (for Phase 5 hybrid search)
- Permission validation middleware (endpoint-level and data-level)
- Admin API endpoints for user and permission management
- Audit logging for queries and admin actions
- Sensitive content tagging
- API key rotation for users
- Seed script updates (create default admin, example users with different roles)

### 3.2 Out of scope

- Multi-tenant isolation (Tier 3 — see limitation LX.2)
- OAuth/SSO integration for user authentication (post-thesis)
- Fine-grained per-file permissions (too granular for MVP — access is at the data source level)
- Permission inheritance from GitHub/Notion (would require syncing their permission models, disproportionate complexity)
- UI for permission management (admin uses API endpoints and CLI)

---

## 4. Role Hierarchy

### 4.1 Role definitions

Arcana defines four roles with hierarchical inheritance. A higher role inherits all capabilities of lower roles.

| Role | Level | Description |
|---|---|---|
| viewer | 1 | Can query the knowledge base within their permitted scopes. Cannot modify anything. Read-only access to answers. |
| dev | 2 | Everything viewer can do, plus: can see their own query history, can provide feedback on answer quality. Default role for new developers. |
| senior_dev | 3 | Everything dev can do, plus: can view team-level query analytics, can review weekly update proposals (Phase 7), can tag content as sensitive within their own scopes. |
| admin | 4 | Full system access. Can manage users, roles, permissions, data sources, and system configuration. Can view all audit logs. Can trigger re-indexing. |

### 4.2 Role capabilities matrix

| Capability | viewer | dev | senior_dev | admin |
|---|---|---|---|---|
| Query knowledge base | Yes | Yes | Yes | Yes |
| View own query history | No | Yes | Yes | Yes |
| Provide answer feedback | No | Yes | Yes | Yes |
| View team query analytics | No | No | Yes | Yes |
| Review update proposals | No | No | Yes | Yes |
| Tag content as sensitive | No | No | Own scopes | All scopes |
| Manage users and roles | No | No | No | Yes |
| Manage permissions | No | No | No | Yes |
| Manage data sources | No | No | No | Yes |
| View all audit logs | No | No | No | Yes |
| Trigger re-indexing | No | No | No | Yes |
| Rotate API keys | Own only | Own only | Own only | Any user |

### 4.3 Role storage

Roles are stored as an enum on the `users` table (defined in Phase 1). The role field accepts one of: `viewer`, `dev`, `senior_dev`, `admin`. There is no separate roles table — the hierarchy is enforced in application logic, not database schema, to keep the MVP simple.

---

## 5. Permission Model

### 5.1 Core concept

Permissions map a user to the data sources they can access. Every data source (GitHub repo, Notion workspace) has an `access_scope` label assigned at ingestion time. Every chunk inherits this label as metadata. Permissions grant a user access to specific access scopes.

The flow: User makes a query → system looks up their permissions → builds a filter of allowed access_scope values → applies filter to ChromaDB and FTS5 queries → LLM only sees permitted chunks.

### 5.2 Permission record structure

Using the `permissions` table defined in Phase 1:

| Field | Description |
|---|---|
| user_id | The user being granted access |
| source_id | The data source being accessed |
| access_level | `read` (can query), `read_write` (can query + provide feedback), `admin` (can modify source config) |
| granted_by | The admin who granted this permission |
| created_at | When the permission was granted |

**Unique constraint:** (user_id, source_id) — one permission record per user per source.

### 5.3 Access scope resolution

When a user makes a query, the system resolves their accessible scopes:

1. Look up all `permissions` records for the user
2. For each permitted source, retrieve the `access_scope` from the `data_sources` table
3. Collect all permitted scope labels into a set (e.g., `{"backend-team", "engineering-docs", "all"}`)
4. Chunks tagged with `access_scope = "all"` (like the architectural overview) are always included regardless of permissions
5. The resulting scope set is used to build the pre-retrieval filter

### 5.4 Default permissions

- New users created with role `dev` receive no permissions by default — an admin must explicitly grant access to each data source
- Users created with role `admin` automatically have access to all data sources (enforced in application logic, not via permission records)
- The architectural overview is accessible to all users regardless of permissions (it uses `access_scope = "all"`)

---

## 6. Pre-Retrieval Filtering

This is the most critical component. It ensures the LLM never receives content the user shouldn't see.

### 6.1 ChromaDB filter

ChromaDB supports metadata filtering via a `where` clause. The filter is constructed from the user's permitted scopes:

```
{
  "access_scope": {
    "$in": ["backend-team", "engineering-docs", "all"]
  }
}
```

This filter is applied to every ChromaDB query. Only chunks whose `access_scope` matches one of the permitted values are returned. The filter is applied server-side by ChromaDB, so unauthorized chunks never leave the database.

### 6.2 FTS5 filter (for Phase 5 hybrid search)

Phase 5 will add BM25 keyword search via SQLite FTS5 alongside vector search. The RBAC filter for FTS5 needs to be built now so it's ready when hybrid search is implemented.

The FTS5 keyword index will store chunks in a table with an `access_scope` column. The filter is a SQL WHERE clause:

```sql
SELECT * FROM chunks_fts
WHERE chunks_fts MATCH ?
AND access_scope IN ('backend-team', 'engineering-docs', 'all')
```

### 6.3 Filter builder service

A dedicated `PermissionFilterService` generates both filters from a user ID:

```
Input:  user_id
Output: {
  "chromadb_where": {"access_scope": {"$in": [...]}},
  "fts5_where": "access_scope IN (...)",
  "permitted_scopes": ["backend-team", "engineering-docs", "all"]
}
```

This service is called once per query. The result can be cached for the duration of the request (permissions don't change mid-query).

### 6.4 Sensitive content overlay

Beyond scope-based filtering, admins can tag specific data sources or individual chunks as "sensitive." Sensitive content is excluded from results for users below `senior_dev` role level, even if they have permission to the source's access scope.

Implementation: a `is_sensitive` boolean on the `data_sources` table (default: false). When true, all chunks from that source additionally require `role >= senior_dev` to be retrieved. The filter builder adds this constraint automatically.

---

## 7. Permission Validation Middleware

### 7.1 Endpoint-level validation

Every API endpoint is protected by a FastAPI dependency that:

1. Extracts the API key from the `X-API-Key` header
2. Hashes it and looks up the user
3. Validates the user is active
4. Checks the user's role meets the minimum required for the endpoint
5. Attaches the user object to the request state for downstream use

```
Endpoint                     | Minimum role
-----------------------------|-------------
GET  /health                 | None (public)
GET  /health/db              | viewer
GET  /health/ready           | viewer
POST /query                  | viewer
GET  /query/history          | dev
POST /query/feedback         | dev
GET  /analytics/team         | senior_dev
POST /admin/users            | admin
PATCH /admin/users/{id}      | admin
POST /admin/sources          | admin
POST /admin/permissions      | admin
GET  /admin/audit-logs       | admin
POST /admin/reindex          | admin
```

### 7.2 Data-level validation

Beyond endpoint access, the middleware ensures data-level isolation:

- `/query` endpoint: the pre-retrieval filter (Section 6) limits results to permitted scopes
- `/query/history`: users can only see their own history (unless admin)
- `/analytics/team`: senior_devs see analytics scoped to their team only (filtered by team field on user record)
- `/admin/audit-logs`: admins see all logs, but the endpoint supports filtering by user_id and source_id

---

## 8. API Endpoints

### 8.1 User management

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | /admin/users | admin | Create a new user. Returns the plaintext API key (shown once). |
| GET | /admin/users | admin | List all users with roles, teams, status, and permission count. |
| GET | /admin/users/{id} | admin | Get detailed user info including all permissions. |
| PATCH | /admin/users/{id} | admin | Update role, team, or active status. |
| DELETE | /admin/users/{id} | admin | Soft-delete (set is_active=false). Preserves audit trail. |
| POST | /admin/users/{id}/rotate-key | admin or self | Generate new API key, invalidate the old one. Returns new plaintext key. |

#### POST /admin/users — request body

```json
{
  "email": "dev@company.com",
  "name": "Jane Smith",
  "role": "dev",
  "team": "backend"
}
```

#### POST /admin/users — response

```json
{
  "id": "uuid",
  "email": "dev@company.com",
  "name": "Jane Smith",
  "role": "dev",
  "team": "backend",
  "api_key": "arc_k1_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "created_at": "2026-03-25T10:00:00Z"
}
```

The `api_key` field is only present in the creation response. It cannot be retrieved again — if lost, the user must rotate their key.

### 8.2 Permission management

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | /admin/permissions | admin | Grant a user access to a data source. |
| GET | /admin/permissions | admin | List all permissions, optionally filtered by user_id or source_id. |
| DELETE | /admin/permissions/{id} | admin | Revoke a specific permission. |
| POST | /admin/permissions/bulk | admin | Grant a user access to multiple sources at once. |

#### POST /admin/permissions — request body

```json
{
  "user_id": "uuid",
  "source_id": "uuid",
  "access_level": "read"
}
```

#### POST /admin/permissions/bulk — request body

```json
{
  "user_id": "uuid",
  "source_ids": ["uuid1", "uuid2", "uuid3"],
  "access_level": "read"
}
```

### 8.3 Sensitive content management

| Method | Path | Auth | Description |
|---|---|---|---|
| PATCH | /admin/sources/{id}/sensitive | admin or senior_dev (own scope) | Toggle sensitive flag on a data source. |
| GET | /admin/sources/sensitive | admin | List all sources marked as sensitive. |

### 8.4 Audit log access

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | /admin/audit-logs | admin | List audit log entries with pagination. |
| GET | /admin/audit-logs?user_id={id} | admin | Filter logs by user. |
| GET | /admin/audit-logs?source_id={id} | admin | Filter logs by data source accessed. |
| GET | /admin/audit-logs?from={date}&to={date} | admin | Filter logs by date range. |

---

## 9. Audit Logging

### 9.1 What gets logged

Every significant action is recorded in the `audit_logs` table:

| Event type | Logged fields |
|---|---|
| query | user_id, query_text, sources_accessed (JSON array of source IDs that the filter permitted), chunks_retrieved (count), response_time_ms, timestamp |
| user_created | admin_user_id, created_user_id, role, team, timestamp |
| user_modified | admin_user_id, target_user_id, changes (JSON diff), timestamp |
| permission_granted | admin_user_id, target_user_id, source_id, access_level, timestamp |
| permission_revoked | admin_user_id, target_user_id, source_id, timestamp |
| key_rotated | user_id (who rotated), target_user_id (whose key), timestamp |
| source_marked_sensitive | user_id, source_id, is_sensitive (new value), timestamp |
| reindex_triggered | admin_user_id, source_id, timestamp |

### 9.2 Schema update

The Phase 1 audit_logs table needs an Alembic migration to support event types beyond queries:

| Column | Type | Constraints | Description |
|---|---|---|---|
| id | UUID | PK | Unique log entry |
| event_type | Enum | Not null | One of: query, user_created, user_modified, permission_granted, permission_revoked, key_rotated, source_marked_sensitive, reindex_triggered |
| user_id | UUID | FK → users.id, not null | Who performed the action |
| target_user_id | UUID | FK → users.id, nullable | Target user (for user/permission events) |
| source_id | UUID | FK → data_sources.id, nullable | Related data source (if applicable) |
| details | JSON | Not null | Event-specific payload (query text, changes diff, etc.) |
| timestamp | DateTime | Auto, UTC | When the event occurred |

This replaces the narrower query-only schema from Phase 1. An Alembic migration will alter the table.

---

## 10. Data Source Schema Update

This phase adds a `is_sensitive` column to the `data_sources` table:

| Column | Type | Constraints | Description |
|---|---|---|---|
| is_sensitive | Boolean | Default: false | When true, chunks from this source require senior_dev+ role level |

Alembic migration adds the column with default=false so existing sources are unaffected.

---

## 11. API Key Format and Security

### 11.1 Key format

API keys follow a structured format for easy identification:
```
arc_k1_<32 bytes URL-safe base64>
```

- `arc` — Arcana prefix
- `k1` — key version (allows future rotation of hashing algorithm)
- 32 bytes of cryptographically random data via Python `secrets.token_urlsafe(32)`

### 11.2 Storage

- Only the SHA-256 hash of the key is stored in `users.api_key_hash`
- The plaintext key is returned exactly once at creation time
- Keys are never logged, never included in error messages, never returned by GET endpoints

### 11.3 Rotation

When a key is rotated:
1. Generate new key
2. Hash and store new hash, overwriting the old one
3. Return new plaintext key in response
4. Old key is immediately invalid (next request with old key returns 401)
5. Audit log records the rotation event

---

## 12. Environment Variables (additions)

| Variable | Type | Default | Description |
|---|---|---|---|
| DEFAULT_ADMIN_EMAIL | String | admin@arcana.local | Email for the seed admin user |
| DEFAULT_ADMIN_NAME | String | Arcana Admin | Display name for the seed admin |

No other new environment variables are needed — the permission system uses the existing database and authentication infrastructure.

---

## 13. Acceptance Criteria

1. **Role enforcement:** A user with role `viewer` can POST /query but receives 403 on POST /admin/users. A user with role `dev` can GET /query/history but receives 403 on GET /admin/audit-logs. A user with role `admin` can access all endpoints.

2. **Permission filtering:** User A has access to source "backend-api" (access_scope: "backend-team"). User B has access to source "frontend-app" (access_scope: "frontend-team"). When User A queries "how does auth work", they only receive chunks from backend-api and the architectural overview. User B querying the same question only receives chunks from frontend-app and the overview. Neither user's results contain chunks from the other's sources.

3. **Scope resolution:** A user with permissions to three sources with scopes "backend-team", "engineering-docs", and "infra" generates a filter with all three values plus "all". The ChromaDB where clause is `{"access_scope": {"$in": ["backend-team", "engineering-docs", "infra", "all"]}}`.

4. **FTS5 filter ready:** The `PermissionFilterService` returns both a `chromadb_where` object and an `fts5_where` SQL clause. The FTS5 filter correctly formats the IN clause with the same scope values. (FTS5 index itself is built in Phase 5, but the filter builder is ready.)

5. **Sensitive content:** A data source marked `is_sensitive=true` is excluded from results for users with role `viewer` or `dev`, even if they have explicit permission to the source's access scope. Users with `senior_dev` or `admin` roles see the content normally.

6. **User CRUD:** POST /admin/users creates a user and returns a valid API key. The key can be used to authenticate subsequent requests. PATCH /admin/users/{id} can change role, team, and active status. DELETE soft-deletes by setting is_active=false. Deleted users receive 401 on all requests.

7. **Permission CRUD:** POST /admin/permissions grants access. GET /admin/permissions lists all or filters by user/source. DELETE /admin/permissions/{id} revokes access. Bulk grant creates multiple permissions in one call.

8. **Key rotation:** POST /admin/users/{id}/rotate-key returns a new API key and invalidates the old one. The old key immediately returns 401. The new key works for all endpoints the user has access to.

9. **Admin auto-access:** Users with role `admin` can query all sources regardless of explicit permission records. The filter builder includes all access scopes for admin users.

10. **Audit logging:** Every query, user creation, permission grant, permission revocation, key rotation, and sensitive tag change produces an audit log entry with the correct event_type, user_id, and details JSON.

11. **Audit log filtering:** GET /admin/audit-logs supports filtering by user_id, source_id, event_type, and date range. Results are paginated (default 50 per page).

12. **Seed script:** Running `make seed` creates a default admin user with the configured email/name and prints the API key. Running seed multiple times is idempotent (doesn't create duplicates).

13. **Tests:** At least 25 tests covering: role hierarchy enforcement (4 roles × multiple endpoints), permission filtering (multi-user with different scopes), scope resolution (including "all" scope), sensitive content exclusion, FTS5 filter generation, user CRUD, permission CRUD, bulk permission grant, key rotation, audit log creation, audit log filtering, admin auto-access, and soft-delete behavior.

---

## 14. Technical Dependencies (additions to Phase 3)

No new packages are required. This phase uses only infrastructure already established:

- **SQLAlchemy** — permission queries, audit log writes
- **FastAPI dependencies** — middleware for role checking
- **Python secrets** — API key generation
- **hashlib** — SHA-256 key hashing

---

## 15. Estimated Effort

| Task | Estimate | Notes |
|---|---|---|
| Role hierarchy + enforcement middleware | 3–4 hours | FastAPI dependency, role level checking |
| Permission CRUD endpoints | 4–5 hours | Create, list, delete, bulk grant |
| Pre-retrieval filter builder (ChromaDB + FTS5) | 4–5 hours | Scope resolution, filter generation, sensitive content overlay |
| User management endpoints | 3–4 hours | Create, update, soft-delete, list with permission counts |
| API key generation + rotation | 2–3 hours | Key format, hashing, rotation flow |
| Audit logging system | 4–5 hours | Event types, JSON details, migration, query/filter endpoints |
| Sensitive content tagging | 2–3 hours | Data source toggle, filter integration |
| Alembic migrations | 1–2 hours | audit_logs schema update, is_sensitive column |
| Seed script update | 1 hour | Default admin, example users with varied roles |
| Test suite | 6–8 hours | 25+ tests across all components |

**Total estimated effort: 30–40 hours (approximately 1.5 weeks at thesis pace)**

---

## 16. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Filter logic bug allows unauthorized chunk access | High | Comprehensive test coverage for multi-user scenarios. Default-deny approach: if filter builder fails, return empty results rather than unfiltered. |
| Permission checks add latency to every query | Low | Permission lookup is a single indexed DB query. Filter builder result is cached per-request. Total overhead < 5ms. |
| Audit log table grows large over time | Low (thesis) | Add index on (timestamp, event_type). For production: partition by month, add retention policy. |
| Admin accidentally revokes their own access | Medium | Prevent last-admin protection: the system rejects role changes or deactivation if it would leave zero active admins. |
| FTS5 filter clause injection | Medium | Use parameterized queries, never string interpolation. The filter builder generates parameterized SQL, not raw strings. |

---

## 17. Known Limitations

| ID | Limitation | Production path |
|---|---|---|
| L4.1 | Permissions are at the data source level, not per-file or per-function. A user with access to a repo can query all files in that repo. | Add optional per-directory or per-file access rules with pattern matching (e.g., "user can access src/auth/* but not src/payments/*"). Requires chunk-level metadata refinement. |
| L4.2 | Permissions are not synced from GitHub/Notion. If a developer loses access to a repo in GitHub, Arcana doesn't know automatically. | Build a periodic permission sync that checks the user's actual access in GitHub/Notion and revokes Arcana permissions if the upstream access is removed. |
| L4.3 | No OAuth/SSO — authentication is API key only. Users can't log in with their GitHub or Google account. | Add OAuth2 flow with GitHub/Google as identity providers. Map OAuth identity to Arcana user record. API keys remain as a fallback for CLI/programmatic access. |
| L4.4 | Role hierarchy is hard-coded in application logic, not configurable. Companies can't define custom roles. | Move role definitions to a database table with configurable capabilities. Add a role management UI in the admin panel. |
| L4.5 | Sensitive content tagging is binary (all-or-nothing per source). Can't mark individual pages or files as sensitive within an otherwise accessible source. | Add chunk-level sensitivity metadata. Allow admins to specify patterns (file paths, page titles) that should be marked sensitive within a source. |

These limitations are documented in the [Arcana Limitations & Design Decisions Log](./Arcana_Limitations_and_Design_Decisions.md).

---

*End of document*