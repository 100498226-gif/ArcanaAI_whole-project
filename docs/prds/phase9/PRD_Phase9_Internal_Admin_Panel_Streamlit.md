# PRD — Phase 9: Internal Admin Panel (Streamlit)

**Product:** Arcana — AI-Powered Developer Onboarding Platform
**Phase:** 9 of Tier 2 (stretch goal)
**Version:** 1.0
**Date:** April 2026
**LLM Provider:** Gemini APIs
**Depends on:** Phases 1–8 (complete)
**Related:** [Arcana Limitations & Design Decisions Log](./Arcana_Limitations_and_Design_Decisions.md) — entries L9.1 through L9.5

---

## 1. Overview

Phases 4–8 built a comprehensive admin API surface: user management, permissions, data source configuration, audit logging, auto-updates with weekly review, and analytics dashboards. The CLI and Cursor extension expose this functionality, but they're developer tools — optimized for command-line users and code editors, not for someone who wants a visual overview of the entire system at a glance.

Phase 9 adds a lightweight internal admin panel built with Streamlit. This is not a customer-facing product UI — it is a god-mode tool for the system administrator (you) to monitor, manage, and debug Arcana during development, thesis demos, and early deployment. It consumes the existing backend API endpoints; it does not introduce new business logic.

Streamlit is chosen deliberately: it's Python-only (no HTML/CSS/JS to write), it renders a functional UI in hours (not weeks), and it's the standard tool for data-centric admin interfaces in the Python ecosystem. The panel will not be pretty — it will be functional.

---

## 2. Objectives

- Provide a single-page visual overview of the entire Arcana system (health, stats, alerts)
- Surface user management with create, edit, role assignment, and permission management
- Display data source status, sync history, and re-index controls
- Render the Phase 8 analytics dashboard natively (charts, tables, metrics)
- Provide a searchable, filterable audit log viewer
- Surface the Phase 7 weekly review with revert capability
- Expose cache metrics and management controls
- Serve as the primary demo tool for thesis presentations

---

## 3. Scope

### 3.1 In scope

- Streamlit app with sidebar navigation and multi-page layout
- System overview page (health, key metrics, alerts)
- User management page (CRUD, role assignment, permission management)
- Data sources page (status, sync progress, re-index trigger, sensitive toggle)
- Analytics page (Phase 8 dashboard rendered as native Streamlit charts)
- Audit log page (searchable, filterable event history)
- Weekly review page (Phase 7 summaries, update history, revert with correction)
- Cache management page (metrics, flush, invalidation)
- Authentication via admin API key
- Deployment as a separate process alongside the FastAPI backend

### 3.2 Out of scope

- Customer-facing UI (this is internal tooling only — see limitation LX.3)
- User self-service (developers don't access this panel — they use Cursor/CLI)
- Custom styling or branding (Streamlit's default theme is sufficient)
- Real-time WebSocket updates (Streamlit uses a poll-and-refresh model)
- Mobile-responsive layout (desktop-only, admin context)
- Embedding Streamlit inside Cursor or the CLI

---

## 4. Architecture

### 4.1 Deployment model

The Streamlit app runs as a separate process alongside the FastAPI backend. Both connect to the same Arcana backend API.

**Endpoint dependency note:** Phase 9 requires a GET /admin/sources endpoint that lists all registered data sources with their status, last_synced_at, chunk counts, and access scopes. Phase 4's PRD defines POST /admin/sources (register) and GET /admin/sources/{id}/status (single source status), and Phase 2 defines source-specific endpoints. However, a general GET /admin/sources listing endpoint is assumed to exist but was not explicitly specified in any prior PRD. If not already implemented, this endpoint must be added — it's a simple SQLAlchemy query against the data_sources table returning all records. This follows the same pattern as GET /admin/users (Phase 4).

```
┌─────────────────┐     ┌─────────────────┐
│  Streamlit App  │────▶│  FastAPI Backend │
│  (port 8501)    │     │  (port 8000)     │
└─────────────────┘     └─────────────────┘
        │                       │
        │                 ┌─────┴──────┐
        │                 │  SQLite    │
        │                 │  ChromaDB  │
        │                 └────────────┘
        │
   Admin browser
   (localhost:8501)
```

The Streamlit app is a pure API consumer — it makes HTTP requests to the FastAPI backend using the admin's API key. It does not access the database or ChromaDB directly. This preserves the single-source-of-truth principle: all business logic, RBAC, and validation live in the backend.

### 4.2 Technology stack

| Component | Technology |
|---|---|
| Framework | Streamlit >=1.38 |
| HTTP client | httpx (async, same as CLI) |
| Charts | Streamlit native charts (st.line_chart, st.bar_chart) + plotly for interactive charts |
| Tables | st.dataframe with pandas for sortable, filterable display |
| Config | Reads STREAMLIT_API_KEY and BACKEND_URL from environment |

### 4.3 Project structure

The admin panel lives in the `admin/` directory of the monorepo, alongside `backend/`, `cli/`, `cursor/`, and `docs/`.

```
admin/
├── app.py                    # Main Streamlit entry point, sidebar navigation
├── pages/
│   ├── 1_Overview.py         # System health, key metrics, alerts
│   ├── 2_Users.py            # User management + permissions
│   ├── 3_Sources.py          # Data source management
│   ├── 4_Analytics.py        # Phase 8 dashboard
│   ├── 5_Audit_Log.py        # Event history viewer
│   ├── 6_Weekly_Review.py    # Phase 7 review + revert
│   └── 7_Cache.py            # Cache metrics + management
├── api_client.py             # Shared HTTP client for backend API calls
├── auth.py                   # API key authentication handling
├── config.py                 # Environment variable loading
├── requirements.txt          # streamlit, httpx, pandas, plotly
└── README.md                 # Setup and usage instructions
```

Streamlit's multi-page app convention: files in `pages/` with numeric prefixes define the sidebar navigation order automatically.

---

## 5. Authentication

### 5.1 Login flow

When the admin opens the Streamlit app:

1. The app checks for `STREAMLIT_API_KEY` in environment variables
2. If set: uses it automatically (no login screen — suitable for local development)
3. If not set: displays a login page with an API key input field
4. The entered key is validated against the backend (GET /health/db with X-API-Key header)
5. The backend confirms the key belongs to an admin user (non-admin keys return 403)
6. On success: the key is stored in `st.session_state` for the duration of the session
7. On failure: error message "Invalid API key or insufficient permissions. Admin access required."

### 5.2 Session management

- The API key persists in `st.session_state` — it survives page navigation but not browser tab close
- A "Logout" button in the sidebar clears `st.session_state` and returns to the login page
- Every API call includes the key in the `X-API-Key` header
- If any API call returns 401 (key invalidated/rotated), the session is cleared and the user is redirected to login

### 5.3 Security note

The Streamlit app is designed for local access (localhost:8501). It should not be exposed to the public internet without additional authentication (reverse proxy with HTTP basic auth, VPN, etc.). For the thesis, running on localhost is sufficient.

---

## 6. Page: System Overview

### 6.1 Purpose

The landing page. Shows the admin everything they need to know at a glance — is the system healthy, how active is it, are there any issues that need attention?

### 6.2 Layout

**Row 1 — Health status indicators:**

Three colored status cards side-by-side using `st.columns(3)`:

| Card | Source endpoint | Green | Yellow | Red |
|---|---|---|---|---|
| Backend API | GET /health | Responding < 500ms | Responding > 2s | Unreachable |
| Database | GET /health/db | Both SQLite + ChromaDB connected | One degraded | Either unreachable |
| LLM Service | GET /health/ready | Gemini API responding | Slow response | Key invalid or unreachable |

**Row 2 — Key metrics (4 columns):**

Rendered using `st.metric()` which natively supports values with delta indicators:

| Metric | Source | Delta comparison |
|---|---|---|
| Total queries (30d) | GET /admin/analytics/query-frequency?format=raw | vs. previous 30d |
| Active users (7d) | GET /admin/analytics/user-activity?format=raw | vs. previous 7d |
| Cache hit rate | GET /admin/cache/stats | vs. previous 7d |
| Knowledge base chunks | GET /admin/analytics/coverage-gaps?format=raw | vs. previous 7d |

**Row 3 — Alerts:**

A list of actionable items requiring admin attention:

| Alert condition | Source | Display |
|---|---|---|
| Pending weekly review | GET /admin/updater/review/pending | "Weekly review available — {N} updates this week" |
| Data source in error state | GET /admin/sources (filter status=error) | "Source {name} sync failed — last error: {message}" |
| Stale source (not synced in 7+ days) | GET /admin/sources (filter last_synced_at) | "Source {name} hasn't been synced in {N} days" |
| Users with zero queries (30d) | GET /admin/analytics/user-activity?format=raw | "User {name} hasn't used Arcana in 30 days" |

Alerts are displayed using `st.warning()` and `st.error()` Streamlit components with appropriate severity colors.

**Row 4 — Quick actions:**

A row of buttons for common admin tasks:

| Button | Action |
|---|---|
| Trigger auto-update | POST /admin/updater/run |
| Flush cache | POST /admin/cache/flush (with confirmation dialog) |
| View weekly review | Navigate to Weekly Review page |

### 6.3 Auto-refresh

The overview page auto-refreshes every 60 seconds using `st.rerun()` with a timer. A "Pause auto-refresh" toggle disables this for debugging.

---

## 7. Page: User Management

### 7.1 Purpose

Manage all Arcana users — create, edit roles, assign permissions to data sources, rotate keys, deactivate.

### 7.2 Layout

**Section 1 — User table:**

A `st.dataframe` displaying all users from GET /admin/users:

| Column | Content |
|---|---|
| Name | User display name |
| Email | User email |
| Role | Colored badge (viewer=gray, dev=blue, senior_dev=purple, admin=red) |
| Team | Team assignment |
| Status | Active/Inactive indicator |
| Queries (30d) | Query count from analytics |
| Last active | Relative timestamp ("2h ago", "3d ago") |
| Actions | Edit / Permissions / Rotate key / Deactivate buttons |

The table is sortable by clicking column headers (native `st.dataframe` behavior with pandas).

**Section 2 — Create user form:**

Expandable section (`st.expander("Create new user")`) with fields:

| Field | Widget | Validation |
|---|---|---|
| Email | st.text_input | Required, email format |
| Name | st.text_input | Required |
| Role | st.selectbox | viewer, dev, senior_dev, admin |
| Team | st.text_input | Optional |

On submit (POST /admin/users), the returned API key is displayed in a `st.code` block with a "Copy" button and a warning: "This key will only be shown once. Save it now."

**Section 3 — Edit user dialog:**

Clicking "Edit" on a user row opens a form pre-filled with current values:

| Field | Widget | Notes |
|---|---|---|
| Name | st.text_input | Editable |
| Role | st.selectbox | Editable, with last-admin protection warning |
| Team | st.text_input | Editable |
| Active | st.toggle | Deactivation with confirmation |

Save button calls PATCH /admin/users/{id}.

**Section 4 — Permission management:**

Clicking "Permissions" on a user row shows:

- A table of the user's current permissions (source name, access level, granted by, date)
- A "Grant access" form: select data source (from GET /admin/sources), select access level (read, read_write, admin), submit
- A "Revoke" button next to each existing permission

---

## 8. Page: Data Sources

### 8.1 Purpose

Monitor all connected data sources — their sync status, health, and configuration. Trigger re-syncs and manage sensitive flags.

### 8.2 Layout

**Section 1 — Source cards:**

Each data source is displayed as a card using `st.container()`:

```
┌─ org/backend-api ─────────────────── GitHub ──┐
│ Status: ● Active                               │
│ Last synced: 2026-04-15 02:00 UTC (6h ago)     │
│ Chunks: 3,420 code + 180 docs = 3,600 total    │
│ Access scope: backend-team                      │
│ Sensitive: No                                   │
│                                                 │
│ [Re-sync] [Toggle sensitive] [View details]     │
└─────────────────────────────────────────────────┘
```

Status indicators:
- ● Green (Active) — last sync completed successfully
- ● Yellow (Syncing) — sync in progress (show progress bar from sync_progress)
- ● Red (Error) — last sync failed (show error message)
- ● Gray (Pending) — registered but never synced

**Section 2 — Sync progress (visible when a source is syncing):**

When a source has status=syncing, the card expands to show:
- A progress bar (`st.progress()`) based on `sync_progress.processed_files / sync_progress.total_files`
- Current file/page being processed
- Chunks generated so far
- Elapsed time

This auto-refreshes every 5 seconds while syncing.

**Section 3 — Source details (expandable):**

Clicking "View details" on a card shows:
- Full configuration (repos selected, Notion pages selected)
- Sync history (last 10 syncs with timestamps and chunk counts)
- Coverage breakdown (files indexed vs. total, from Phase 8 analytics)
- Recent update records from Phase 7 (changes detected and applied)

---

## 9. Page: Analytics

### 9.1 Purpose

Render the Phase 8 analytics dashboard natively in Streamlit with interactive charts.

### 9.2 Layout

**Date range selector:**

A row at the top with `st.date_input` for start and end dates, plus quick-select buttons: "Last 7 days", "Last 30 days", "Last 90 days".

**Section 1 — Overview metrics:**

Four `st.metric` cards from the Phase 8 dashboard overview metric_card:
- Total queries
- Active users
- Cache hit rate
- Knowledge base chunks

Each with delta indicators showing change vs. previous period.

**Section 2 — Query frequency chart:**

Rendered using `st.line_chart` (simple) or `plotly.graph_objects.Figure` (interactive with hover tooltips):
- X-axis: dates
- Y-axis: query count
- Optional toggle between daily and weekly grouping

Data source: GET /admin/analytics/query-frequency?format=raw

**Section 3 — Coverage gaps:**

Rendered using `st.progress` bars per source:
- Source name, indexed file count / total file count, percentage
- Sorted by lowest coverage first (biggest gaps at top)

Data source: GET /admin/analytics/coverage-gaps?format=raw

**Section 4 — Popular topics:**

Rendered using `st.bar_chart`:
- X-axis: source names
- Y-axis: query count

Data source: GET /admin/analytics/popular-topics?format=raw

**Section 5 — User activity:**

Rendered using `st.dataframe` with pandas:
- Sortable table with user name, role, team, query count, last active, cache hit %
- Color-coded rows: inactive users (0 queries) highlighted in yellow

Data source: GET /admin/analytics/user-activity?format=raw

**Section 6 — Cache performance:**

Rendered using `st.line_chart` for daily hit rate trend + `st.metric` cards for current totals.

Data source: GET /admin/analytics/cache-performance?format=raw

### 9.3 Data fetching

All analytics data is fetched using the `?format=raw` parameter so Streamlit can render charts natively (rather than trying to interpret the Phase 8 component JSON). The raw format returns plain data objects that map directly to pandas DataFrames.

---

## 10. Page: Audit Log

### 10.1 Purpose

A searchable, filterable view of all system events — queries, user changes, permission changes, updates, reverts, and analytics views.

### 10.2 Layout

**Filter bar (top):**

| Filter | Widget | Options |
|---|---|---|
| Event type | st.multiselect | query, user_created, user_modified, permission_granted, permission_revoked, key_rotated, source_marked_sensitive, reindex_triggered, feedback, auto_update_run, update_applied, update_reverted, correction_applied, weekly_review_generated, weekly_review_acknowledged, analytics_viewed |
| User | st.selectbox | All users (from GET /admin/users) + "All" option |
| Source | st.selectbox | All sources (from GET /admin/sources) + "All" option |
| Date range | st.date_input | Start and end date |
| Search | st.text_input | Free-text search within event details |

**Event table:**

A `st.dataframe` displaying paginated results from GET /admin/audit-logs with applied filters:

| Column | Content |
|---|---|
| Timestamp | Formatted datetime |
| Event type | Colored badge by category |
| User | User name who performed the action |
| Details | Truncated summary (click to expand) |

**Event detail expansion:**

Clicking a row expands it to show the full `details` JSON, formatted and syntax-highlighted using `st.json()`.

**Pagination:**

"Previous" and "Next" buttons below the table. 50 events per page (configurable). Total event count displayed.

---

## 11. Page: Weekly Review

### 11.1 Purpose

Surface Phase 7's weekly review summaries and provide the revert-with-correction workflow in a visual format.

### 11.2 Layout

**Week selector:**

A `st.selectbox` with available weeks (populated from GET /admin/updater/review?week=&year= for the last 12 weeks), defaulting to the current week.

**Section 1 — Weekly narrative:**

The Gemini-generated narrative summary from Phase 7, rendered as formatted markdown using `st.markdown`:

- Overall summary paragraph
- Highlighted high-risk updates (using `st.warning`)
- Patterns detected (using `st.info`)
- Recommended reviews (using `st.error` for high priority)

**Section 2 — Update list:**

A table of all update records for the selected week from GET /admin/updater/history?week={N}&year={Y}:

| Column | Content |
|---|---|
| Source | Source name and type icon |
| File/Page | File path or page title |
| Change type | Added / Modified / Deleted / Renamed with icon |
| Significance | Significant (red badge) / Minor (gray badge) |
| Summary | LLM-generated description |
| Status | Applied / Reverted / Correction applied |
| Actions | "Revert" button (only for status=applied) |

**Section 3 — Revert flow:**

Clicking "Revert" on an update record:

1. A `st.expander` opens below the row showing the full update details
2. The before-state snapshot is displayed in a `st.code` block (the old code/content)
3. The after-state snapshot is displayed in a second `st.code` block (the new code/content)
4. A side-by-side diff view if the change is a modification (using Streamlit's native diff display or a simple two-column layout)
5. A `st.text_area` for the mandatory correction: "What should the knowledge base say instead?"
6. Character counter showing current length (minimum 20 required)
7. "Apply correction" button — calls POST /admin/updater/revert/{update_id} with the correction text
8. On success: the update row status changes to "Correction applied" and the correction text is shown inline
9. On validation failure (correction too short): `st.error("Correction must be at least 20 characters.")`

**Section 4 — Review acknowledgment:**

A "Mark as reviewed" button at the bottom. Calls POST /admin/updater/review/{id}/acknowledge. Changes the page header to show "✓ Reviewed by {admin_name} on {date}".

---

## 12. Page: Cache Management

### 12.1 Purpose

Monitor semantic cache performance and manage cache entries.

### 12.2 Layout

**Section 1 — Cache metrics:**

Four `st.metric` cards from GET /admin/cache/stats:

| Metric | Value | Delta |
|---|---|---|
| Cache entries | Total count | Change vs. yesterday |
| Hit rate | Percentage | Change vs. last week |
| Estimated API savings | Dollar amount | Cumulative total |
| Avg hit latency | Milliseconds | vs. avg full pipeline latency |

**Section 2 — Hit rate trend:**

Line chart showing daily cache hit rate over the selected period (data from Phase 8 cache performance analytics).

**Section 3 — Cache actions:**

| Button | Action | Confirmation |
|---|---|---|
| Flush all entries | POST /admin/cache/flush | "Are you sure? This will clear {N} cached entries. All subsequent queries will run the full pipeline." |
| Invalidate by scope | POST /admin/cache/invalidate with selected scope | Dropdown to select scope, then confirm |

**Cache enabled status:** The page displays the current `CACHE_ENABLED` state as a read-only indicator. This is an environment variable, not an API-toggleable setting. To enable/disable the cache, the admin must change the env var and restart the backend. The panel shows: "Cache is currently **enabled**" (or disabled) with a note: "Change CACHE_ENABLED in .env and restart the backend to toggle."

Flush and invalidate actions display a success message with the number of entries affected.

---

## 13. Shared API Client

### 13.1 Implementation

A shared `api_client.py` module used by all pages:

```python
import httpx
import streamlit as st

class ArcanaClient:
    def __init__(self):
        self.base_url = st.session_state.get("backend_url", "http://localhost:8000")
        self.api_key = st.session_state.get("api_key", "")

    def _headers(self) -> dict:
        return {"X-API-Key": self.api_key}

    def get(self, path: str, params: dict | None = None) -> dict:
        response = httpx.get(
            f"{self.base_url}{path}",
            headers=self._headers(),
            params=params,
            timeout=30,
        )
        if response.status_code == 401:
            st.session_state.clear()
            st.rerun()
        response.raise_for_status()
        return response.json()

    def post(self, path: str, json: dict | None = None) -> dict:
        response = httpx.post(
            f"{self.base_url}{path}",
            headers=self._headers(),
            json=json,
            timeout=30,
        )
        if response.status_code == 401:
            st.session_state.clear()
            st.rerun()
        response.raise_for_status()
        return response.json()

    # patch, delete follow same pattern
```

### 13.2 Error handling

All API call errors are caught and displayed using `st.error()`:

| HTTP status | Display |
|---|---|
| 401 | Clear session, redirect to login |
| 403 | "Insufficient permissions for this action." |
| 404 | "Resource not found." |
| 422 | Validation error details from the response body |
| 500 | "Backend error. Check server logs." |
| Connection refused | "Cannot reach Arcana backend at {url}. Is the server running?" |
| Timeout | "Request timed out. The operation may still be in progress." |

---

## 14. Environment Variables

| Variable | Type | Default | Description |
|---|---|---|---|
| STREAMLIT_API_KEY | String | — (optional) | Admin API key for auto-login. If unset, shows login page. |
| BACKEND_URL | String | http://localhost:8000 | FastAPI backend URL |
| STREAMLIT_PORT | Integer | 8501 | Port for the Streamlit app |
| STREAMLIT_REFRESH_INTERVAL | Integer | 60 | Auto-refresh interval in seconds for the overview page |

---

## 15. Deployment

### 15.1 Local development

```bash
cd admin
pip install -r requirements.txt
streamlit run app.py
```

Opens at http://localhost:8501.

### 15.2 Docker Compose integration

The admin panel is added to the existing `docker-compose.yml`:

```yaml
admin:
  build: ./admin
  ports:
    - "8501:8501"
  environment:
    - BACKEND_URL=http://backend:8000
    - STREAMLIT_API_KEY=${ADMIN_API_KEY}
  depends_on:
    - backend
```

### 15.3 Makefile integration

Added to the root Makefile:

```makefile
run-admin:
    cd admin && streamlit run app.py

docker-up:  # updated to include admin panel
    docker-compose up -d backend admin
```

---

## 16. Acceptance Criteria

### Authentication

1. **Auto-login:** With `STREAMLIT_API_KEY` set in environment, the app skips the login page and navigates directly to the overview.

2. **Manual login:** Without the env var, the app shows a login page. A valid admin key grants access. A valid non-admin key shows "Admin access required." An invalid key shows "Invalid API key."

3. **Session expiry:** If the backend invalidates the API key (key rotation), the next API call redirects to the login page with a clear message.

### Overview page

4. **Health indicators:** Three status cards show green when all services are healthy. Simulating a backend shutdown changes the API card to red within 60 seconds.

5. **Key metrics:** Four metric cards show real numbers matching the backend analytics data. Delta indicators show change vs. previous period.

6. **Alerts:** A source in error state produces a red alert. A pending weekly review produces a yellow alert. An inactive user produces an info alert.

7. **Quick actions:** "Trigger auto-update" calls POST /admin/updater/run and shows a spinner during execution. "Flush cache" shows a confirmation dialog before calling POST /admin/cache/flush.

### User management

8. **User table:** Displays all users with correct role badges, teams, query counts, and last active timestamps. Table is sortable by column.

9. **Create user:** Filling the form and submitting creates a user. The returned API key is displayed in a code block. Creating with an existing email shows a validation error.

10. **Edit user:** Changing a user's role from dev to senior_dev and saving is reflected in the table immediately. Attempting to deactivate the last admin shows a warning.

11. **Permissions:** Granting a user access to a source creates a permission record. The user's permission table updates to show the new entry. Revoking removes it.

### Data sources

12. **Source cards:** Each registered source shows with correct status indicator, last sync time, chunk count, and access scope.

13. **Re-sync trigger:** Clicking "Re-sync" on a source calls the backend sync endpoint. While syncing, the card shows a progress bar that updates every 5 seconds.

14. **Sensitive toggle:** Toggling sensitive on a source calls PATCH /admin/sources/{id}/sensitive. The card updates to show the new state.

### Analytics

15. **All 5 metrics render:** The analytics page shows query frequency (line chart), coverage gaps (progress bars), popular topics (bar chart), user activity (table), and cache performance (line chart + metrics). All with real data.

16. **Date range filtering:** Changing the date range re-fetches all analytics with the new range. Charts and tables update accordingly.

17. **Interactive charts:** Plotly charts support hover tooltips showing exact values.

### Audit log

18. **Full event list:** The audit log page shows events with correct types, users, timestamps, and details.

19. **Filtering:** Selecting event_type=query filters to only query events. Selecting a specific user filters to their events. Both filters combine correctly.

20. **Detail expansion:** Clicking an event row expands to show the full details JSON, syntax-highlighted.

21. **Pagination:** With more than 50 events, "Next" and "Previous" buttons navigate between pages. Total count is displayed.

### Weekly review

22. **Week selection:** The week selector shows available weeks. Selecting a past week loads that week's review.

23. **Narrative display:** The weekly narrative renders as formatted markdown with high-risk warnings and pattern alerts.

24. **Update list:** All update records for the week are displayed with correct change types, significance badges, and statuses.

25. **Revert flow:** Clicking "Revert" shows the before/after snapshots and a correction text area. Submitting a correction ≥20 characters triggers the revert. The row status updates to "Correction applied."

26. **Mandatory correction validation:** Attempting to submit a correction shorter than 20 characters shows an error. An empty correction is blocked.

27. **Review acknowledgment:** "Mark as reviewed" changes the page header to show reviewed status with admin name and timestamp.

### Cache management

28. **Cache metrics:** Four metric cards show real values from GET /admin/cache/stats.

29. **Flush with confirmation:** "Flush all" shows a confirmation dialog. Confirming clears the cache and displays the number of entries removed.

30. **Invalidate by scope:** Selecting a scope from the dropdown and confirming clears entries for that scope.

### Cross-cutting

31. **Error handling:** When the backend is unreachable, every page shows "Cannot reach Arcana backend" instead of crashing. When an API call fails, the specific error is shown using st.error.

32. **Navigation:** All 7 pages are accessible via the sidebar. The current page is highlighted. Navigation preserves the session.

33. **Tests:** At least 15 tests covering: API client error handling (401 redirect, 403 message, 500 message, connection refused), authentication flow (auto-login, manual login, invalid key), overview metric rendering (with mock API responses), user CRUD flow (create + verify + edit + deactivate), audit log filtering (by type, user, date), revert flow validation (correction length check), and cache flush confirmation.

---

## 17. Technical Dependencies

| Package | Version | Purpose |
|---|---|---|
| streamlit | >=1.38 | Admin panel framework |
| httpx | >=0.28 | HTTP client (already used by CLI) |
| pandas | >=2.2 | DataFrames for table display and chart data |
| plotly | >=5.24 | Interactive charts (hover, zoom, tooltips) |

---

## 18. Estimated Effort

| Task | Estimate | Notes |
|---|---|---|
| App scaffold + auth + shared API client | 3–4 hours | Multi-page setup, login flow, session management, error handling |
| Overview page | 3–4 hours | Health checks, metrics, alerts, quick actions, auto-refresh |
| User management page | 4–5 hours | User table, create form, edit form, permission management |
| Data sources page | 3–4 hours | Source cards, sync progress, re-sync trigger, sensitive toggle |
| Analytics page | 3–4 hours | 5 chart/table sections, date range selector, plotly integration |
| Audit log page | 3–4 hours | Filters, paginated table, detail expansion, search |
| Weekly review page | 4–5 hours | Narrative display, update list, revert flow with correction, acknowledgment |
| Cache management page | 2–3 hours | Metrics, flush/invalidate with confirmation |
| Docker Compose + Makefile integration | 1–2 hours | Dockerfile, compose entry, Makefile commands |
| Test suite | 4–5 hours | 15+ tests (mock API responses, flow validation) |

**Total estimated effort: 30–40 hours (approximately 1–1.5 weeks at thesis pace)**

This is the lightest phase — Streamlit eliminates all frontend engineering. The work is primarily wiring API calls to Streamlit widgets.

---

## 19. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Streamlit's polling model causes stale data on long-running pages | Low | Auto-refresh on overview page. Manual "Refresh" button on other pages. Users understand they need to reload for fresh data. |
| Streamlit's layout constraints make complex views (like the revert diff) awkward | Low | Keep layouts simple — vertical stacking, expandable sections. Don't fight the framework. The panel is functional, not beautiful. |
| plotly charts add significant page load time | Low | Use Streamlit native charts (st.line_chart, st.bar_chart) for simple views. Reserve plotly for the analytics page where interactivity matters. |
| Admin panel exposes all system data — if accidentally left running on a shared network, anyone with access can manage the system | Medium | Run on localhost only by default. Docker Compose binds to 127.0.0.1. Add a warning banner: "This is an admin panel. Do not expose to public networks." |
| Streamlit version changes break widget behavior | Low | Pin streamlit version in requirements.txt. Test after any upgrade. |

---

## 20. Known Limitations

| ID | Limitation | Production path |
|---|---|---|
| L9.1 | The admin panel is Streamlit — functional but not visually polished. It looks like a data tool, not a product UI. | Migrate to a React-based admin framework (e.g., Retool, AdminJS, or custom React). The backend API is already complete — only the frontend changes. |
| L9.2 | No role-based page visibility. All pages are visible to anyone with admin access. There's no way to give a senior_dev access to analytics but not user management. | Add page-level role gating: check the logged-in user's role and hide pages that require higher privileges. Requires the login flow to store the user's role in session_state. |
| L9.3 | No concurrent user support. Streamlit sessions are per-browser-tab. Two admins using the panel simultaneously don't see each other's actions in real-time. | This is inherent to Streamlit's architecture. For production: migrate to a React frontend with WebSocket-based real-time updates. |
| L9.4 | The panel cannot be embedded in Cursor or accessed as a plugin. It's a standalone web app in a separate browser tab. | Post-thesis: build a lightweight web view that can be loaded in Cursor's webview panel via an iframe. Requires the admin panel to be served over HTTP with proper CORS. |
| L9.5 | No audit logging of admin panel actions. Actions taken through the panel (creating users, flushing cache) are logged by the backend API, but the panel itself doesn't log which pages were viewed or how long the admin spent reviewing. | Add client-side analytics to the Streamlit app (page view events sent to the backend). Low priority — the backend audit log already captures all state-changing actions. |

These limitations are documented in the [Arcana Limitations & Design Decisions Log](./Arcana_Limitations_and_Design_Decisions.md).

---

*End of document*