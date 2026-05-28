# Arcana — 3-Pass Quality Audit

You are performing a mandatory quality audit on the code you just wrote or modified.
Work through **all three passes sequentially**. For each issue found, fix it immediately
in the same response before moving to the next pass. Do not skip passes even if Pass 1 finds nothing.

Context provided: $ARGUMENTS

---

## PASS 1 — Correctness & Bugs

Read every file you created or modified this session. Check for:

**Unused / dead code**
- Unused imports (causes ruff F401)
- Variables assigned but never read
- Parameters declared in function signature but never used in the body (interface lie)
- Functions defined but never called (unless explicitly a public API surface)

**Logic errors**
- Parameters that are accepted but silently ignored (the `group_by` pattern from Phase 8)
- Errors swallowed silently with bare `except: pass` (should at minimum log)
- Return type mismatches (function says `list[X]` but returns a dict in the raw_data branch)
- Off-by-one in pagination, slice, or date math
- Wrong comparison types: SQLAlchemy enum vs string, boolean vs integer

**Validation gaps**
- User-supplied strings used without validation (dates, UUIDs, enum values)
- Invalid input that silently falls back to a default instead of returning 4xx
- HTTP status code correctness: 404 vs 422 vs 400 vs 403

**Empty / edge states**
- Every public function that can receive zero rows must have an explicit empty-state return
- Endpoints that could return `None` but are typed to return a model

---

## PASS 2 — Production Readiness

**SQL portability (SQLite dev → PostgreSQL prod)**
- `json_extract(col, '$.field')` is SQLite-only → use `_json_extract()` / `_json_bool_eq_1()` helpers
- `is_active = 1` fails on PostgreSQL boolean columns → use `is_active` or `is_active IS TRUE`
- `AUTOINCREMENT` is SQLite-only → use SQLAlchemy `default=uuid4`
- FTS5 queries only run on SQLite → document as L-series limitation if used
- Week grouping: `strftime('%Y-%W', ...)` differs from PostgreSQL `date_trunc('week', ...)`

**Async correctness**
- `asyncio.get_event_loop()` deprecated in Python 3.10+ → use `asyncio.get_running_loop()`
- Synchronous ChromaDB / blocking I/O called directly in `async def` without `run_in_executor` → flag as known limitation if not fixed
- Module-level mutable state shared across requests → thread-safety or document as process-local

**Database session semantics**
- `flush()` writes to buffer but does not commit — only use when the session will commit later
- In SSE streaming endpoints, verify the session lifecycle (the `get_db` dependency commits after the generator exhausts)
- Ensure new audit log entries are created before, not after, the operation they record

**Security**
- Raw SQL via `text()` must use named parameters (`:param`), never f-string interpolation of user input
- HTML in webview must use `escHtml()` for all user-derived content (XSS prevention)
- API keys must never be logged, stored in plain text, or returned in responses

**Missing Alembic migration**
- Any new column, index, or table must have a corresponding migration in `backend/migrations/versions/`

---

## PASS 3 — Homogeneity with Existing Phases

Compare the new code against the established patterns in each layer.

**Backend routers** (compare with `routers/users.py`, `routers/github.py`, `routers/updater.py`):
- Auth: `current_user: User = Depends(require_role(UserRole.X))` — no double Depends
- Audit logging: `await log_event(db, AuditEventType.X, user_id=current_user.id, details={...})` in every state-changing endpoint
- Query params: `Query(default, description="...")` with explicit description strings
- Date params: `_parse_date(date_str, "param_name")` with HTTP 422 on bad input
- Response models: always set `response_model=` on the decorator

**Services** (compare with `services/github_service.py`, `services/auto_updater.py`):
- Logger: `log = structlog.get_logger()` at module level; events use `log.info()`/`log.warning()` with keyword args
- Error propagation: services raise exceptions; routers catch and return HTTP errors
- No bare `except Exception: pass` — at minimum `log.warning(...)` before re-raising or returning fallback

**Tests** (compare with `tests/test_rbac.py`, `tests/test_updater.py`):
- Every new public endpoint needs: one success test, one auth-failure test (403), one validation test (400/422)
- Use existing fixtures: `admin_user`, `dev_user`, `viewer_user`, `client`, `db`, `data_source`
- Async tests use `@pytest.mark.asyncio` consistently
- Mock external dependencies (Gemini, ChromaDB, GitHub) — never hit real services in tests

**CLI** (compare with `commands/users.py`, `commands/audit.py`):
- API key: `key = _require_key()` pattern
- Error handling: `except (ArcanaAPIError, ArcanaConnectionError) as e: _handle(e)`
- `from typing import Optional` import (project-wide CLI convention)
- Rich output: use `console.print()`, not `print()`

**Cursor extension** (compare with `SidebarProvider.ts`, `main.js` existing sections):
- New message commands: add handler in both `onDidReceiveMessage` (TS) and `window.addEventListener('message')` (JS)
- New API functions: add to `arcanaClient.ts` with full TypeScript interfaces
- `escHtml()` for any user-derived content in innerHTML
- New screens: follow the `showX()` / `hideX()` pattern; reset loading state on navigation away

**Schemas** (compare with `schemas/analytics.py`, `schemas/query.py`):
- Pydantic v2 style: `class X(BaseModel)` with type annotations, not `__fields__`
- Use `Literal["value"]` for discriminated string fields
- Validators use `@field_validator` (v2), not `@validator` (v1)

---

## Reporting

After all three passes:

1. List every issue found, grouped by pass, with file:line reference.
2. List every fix applied (or if no issues found, explicitly confirm "Pass N: clean").
3. Run `source .venv/bin/activate && python -m pytest backend/tests/ -q --tb=short` and confirm the count matches the expected count from CONTEXT.md.
4. If any test fails, fix the root cause before declaring the audit complete.

The audit is complete only when all three passes report clean and the test suite passes.
