# PRD — Phase 8: Analytics Data Layer + Admin Dashboards

**Product:** Arcana — AI-Powered Developer Onboarding Platform
**Phase:** 8 of Tier 2 (stretch goal)
**Version:** 1.0
**Date:** April 2026
**LLM Provider:** Gemini APIs
**Depends on:** Phases 1–7 (complete)
**Related:** [Arcana Limitations & Design Decisions Log](./Arcana_Limitations_and_Design_Decisions.md) — entries L8.1 through L8.5

---

## 1. Overview

Phase 5 built a component renderer that can return charts, tables, and metric cards instead of plain text. Phase 6 built client-side rendering for those components in both Cursor and CLI. But until now, the data behind those components has been LLM-generated — meaning the numbers are hallucinated. When someone asks "show me which repos are most queried," Gemini invents plausible-looking data because there's no code that actually queries the audit logs.

Phase 8 closes this gap. It builds the analytics data layer — real SQL queries against real data — and wires it to real admin dashboards in both Cursor and CLI. It also upgrades the LLM-to-component pipeline from "hope Gemini returns valid JSON" to guaranteed schema-compliant output using Gemini's native `response_schema` configuration.

By the end of this phase, an admin can type `arcana dashboard` or click a "Dashboard" button in Cursor and see real usage statistics, coverage gaps, popular topics, and cache performance — all backed by actual data, not hallucinations.

---

## 2. Objectives

- Build an analytics service with 5 typed query functions backed by real SQL/ChromaDB queries
- Expose analytics endpoints that return component-ready JSON directly (no LLM involved)
- Upgrade the Phase 5 visual query pipeline from keyword heuristics + regex fallback to Gemini's `response_schema` for guaranteed structured output
- Add an admin dashboard command to the CLI that renders a multi-panel analytics view
- Add a Dashboard button to the Cursor sidebar that renders the same multi-component view
- Support both canned dashboards (pre-defined analytics views) and ad-hoc visual queries (LLM-powered with real data)

---

## 3. Scope

### 3.1 In scope

- `analytics_service.py` — 5 typed analytics functions with SQL/ChromaDB queries
- Analytics API endpoints — GET /admin/analytics/{metric} returning component JSON
- Aggregate dashboard endpoint — GET /admin/analytics/dashboard returning a multi-component response
- Gemini `response_schema` upgrade for visual queries — retire regex fallback
- CLI `arcana dashboard` command with multi-panel Rich output
- Cursor sidebar Dashboard button with multi-component Chart.js rendering
- Ad-hoc visual queries backed by real data (LLM selects which analytics to present based on the question)

### 3.2 Out of scope

- New component types beyond the 5 defined in Phase 5 (chart, table, metric_card, timeline, progress)
- Custom dashboard layouts or saved dashboard configurations
- Real-time streaming analytics (dashboards are point-in-time snapshots)
- Per-user analytics dashboards (all analytics are admin-scoped)
- Export to PDF or image

---

## 4. Analytics Service

### 4.1 Architecture

A new `analytics_service.py` in the `backend/arcana/services/` directory. Each function takes optional filter parameters (date range, source_id, user_id) and returns a typed result that maps directly to a Phase 5 component schema.

The service queries two data sources:
- **SQLite (audit_logs, update_records, data_sources, users)** — for usage stats, query frequency, user activity, update history
- **ChromaDB (code_chunks, doc_chunks)** — for coverage metrics, chunk counts, source distribution

### 4.2 Analytics functions

#### 4.2.1 Query frequency

**What it answers:** "How many questions are being asked, by whom, and about what?"

**SQL query (core):**

**Dependency note:** These queries assume that Phase 5's query audit logging stores `response_time_ms` and `cache_hit` in the `audit_logs.details` JSON for every query event. Phase 5's PRD specifies the SSE `done` event includes these fields — the backend must also write them to `audit_logs.details` when logging the query event. If Phase 5 was implemented without these fields in audit_logs, a migration must add them retroactively, or the analytics service must parse them from the SSE metadata (not recommended).

```sql
SELECT
    date(timestamp) as day,
    COUNT(*) as query_count,
    COUNT(DISTINCT user_id) as unique_users,
    AVG(json_extract(details, '$.response_time_ms')) as avg_response_ms
FROM audit_logs
WHERE event_type = 'query'
AND timestamp >= :from_date
AND timestamp <= :to_date
GROUP BY date(timestamp)
ORDER BY day DESC
```

**Additional breakdowns:**
- By user: GROUP BY user_id with JOIN to users table for names
- By source accessed: parse `details.sources_accessed` JSON array, explode, and count
- By cache hit/miss: filter on `details.cache_hit` boolean

**Returns:** Component JSON with type `chart` (line chart of daily query volume) + type `table` (top users by query count).

**Function signature:**
```python
def get_query_frequency(
    from_date: datetime | None = None,  # default: 30 days ago
    to_date: datetime | None = None,    # default: now
    group_by: str = "day",              # day, week, user, source
) -> list[ComponentSchema]:
```

#### 4.2.2 Coverage gaps

**What it answers:** "Which parts of the codebase or documentation aren't well-indexed?"

**Queries:**
1. **Chunk count per repo:** Count chunks in ChromaDB `code_chunks` collection grouped by `repo` metadata
2. **File count per repo:** Count distinct `file_path` values per repo in ChromaDB
3. **Estimated total files per repo:** From `data_sources.config_json` (stored during Phase 2 ingestion — file tree count)
4. **Coverage ratio:** indexed files / total files per repo
5. **Notion coverage:** Count chunks per workspace/page_path in `doc_chunks`

**Returns:** Component JSON with type `progress` (coverage bars per repo) + type `table` (repos sorted by coverage gap, lowest first).

**Function signature:**
```python
def get_coverage_gaps(
    source_id: str | None = None,  # filter to specific source
) -> list[ComponentSchema]:
```

#### 4.2.3 Popular topics

**What it answers:** "What are developers asking about most? Which knowledge areas are heavily used?"

**Method:** This can't be done with pure SQL — it requires semantic analysis of query texts.

**Approach:**
1. Fetch recent query texts from `audit_logs` (last 30 days, event_type=query, from `details.query_text`)
2. Embed all query texts using the same embedding model
3. Cluster embeddings using a simple k-means (k=10, configurable) via scikit-learn
4. For each cluster, find the medoid (most representative query) and extract topic keywords
5. Count queries per cluster

**Alternative lightweight approach (for MVP):** Skip embedding-based clustering. Instead, extract the `sources_accessed` from each query's audit log entry and count which repos/Notion pages appear most frequently. Group by source and show the most-queried sources as a proxy for popular topics.

**Implementation note:** Start with the lightweight approach. Add embedding-based clustering as a stretch goal within Phase 8 if time permits.

**Returns:** Component JSON with type `chart` (bar chart of query count per topic/source) + type `table` (topic list with example questions).

**Function signature:**
```python
def get_popular_topics(
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    method: str = "source_frequency",  # source_frequency or embedding_cluster
    top_k: int = 10,
) -> list[ComponentSchema]:
```

#### 4.2.4 Per-user activity

**What it answers:** "How is each developer using Arcana? Who's active, who isn't, who might need help?"

**SQL query:**
```sql
SELECT
    u.name,
    u.role,
    u.team,
    COUNT(a.id) as total_queries,
    MAX(a.timestamp) as last_active,
    AVG(json_extract(a.details, '$.response_time_ms')) as avg_response_ms,
    SUM(CASE WHEN json_extract(a.details, '$.cache_hit') = 1 THEN 1 ELSE 0 END) as cache_hits
FROM users u
LEFT JOIN audit_logs a ON u.id = a.user_id
    AND a.event_type = 'query'
    AND (:from_date IS NULL OR a.timestamp >= :from_date)
    AND (:to_date IS NULL OR a.timestamp <= :to_date)
WHERE u.is_active = 1
GROUP BY u.id
ORDER BY total_queries DESC
```

**Note:** The date filter is placed in the JOIN condition (not the WHERE clause) so that users with zero queries in the date range still appear with `total_queries = 0`. This is important for identifying inactive users ("who isn't using Arcana?").

**Returns:** Component JSON with type `table` (user activity ranked by query count, with last active date and cache hit ratio).

**Function signature:**
```python
def get_user_activity(
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    team: str | None = None,
) -> list[ComponentSchema]:
```

#### 4.2.5 Cache performance

**What it answers:** "Is the semantic cache saving money and time? What's the hit rate?"

**Data sources:**
- Phase 5's GET /admin/cache/stats already returns cache entry count, hit rate, and cost savings
- Extend with time-series data from audit_logs: for each query, `details.cache_hit` records whether it was a cache hit

**SQL query:**
```sql
SELECT
    date(timestamp) as day,
    COUNT(*) as total_queries,
    SUM(CASE WHEN json_extract(details, '$.cache_hit') = 1 THEN 1 ELSE 0 END) as cache_hits,
    SUM(CASE WHEN json_extract(details, '$.cache_hit') = 0 THEN 1 ELSE 0 END) as cache_misses,
    ROUND(
        SUM(CASE WHEN json_extract(details, '$.cache_hit') = 1 THEN 1.0 ELSE 0 END) / COUNT(*) * 100,
        1
    ) as hit_rate_pct
FROM audit_logs
WHERE event_type = 'query'
AND timestamp >= :from_date
GROUP BY date(timestamp)
ORDER BY day DESC
```

**Returns:** Component JSON with type `chart` (line chart of daily hit rate) + type `metric_card` (current hit rate, total savings estimate, cache entry count).

**Function signature:**
```python
def get_cache_performance(
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> list[ComponentSchema]:
```

### 4.3 Component schema typing

All analytics functions return `list[ComponentSchema]` — a list of one or more component JSON objects matching the Phase 5 component spec (Section 13.3). This is enforced via Pydantic models:

```python
class ChartData(BaseModel):
    labels: list[str]
    datasets: list[DatasetSchema]

class TableData(BaseModel):
    headers: list[str]
    rows: list[list[str | int | float]]

class MetricCardData(BaseModel):
    metrics: list[MetricSchema]

class TimelineData(BaseModel):
    events: list[TimelineEventSchema]  # each: {date, title, description}

class ProgressData(BaseModel):
    items: list[ProgressItemSchema]    # each: {label, current, total}

class ComponentSchema(BaseModel):
    type: Literal["chart", "table", "metric_card", "timeline", "progress"]
    chart_type: str | None = None  # bar, line, pie (only for type=chart)
    title: str
    data: ChartData | TableData | MetricCardData | TimelineData | ProgressData
    narrative: str | None = None
```

These models are shared between the analytics service and the Phase 5 component renderer, ensuring type consistency.

---

## 5. Analytics API Endpoints

### 5.1 Individual metric endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | /admin/analytics/query-frequency | admin, senior_dev | Query volume over time with breakdowns |
| GET | /admin/analytics/coverage-gaps | admin, senior_dev | Knowledge base coverage per source |
| GET | /admin/analytics/popular-topics | admin, senior_dev | Most-queried topics/sources |
| GET | /admin/analytics/user-activity | admin, senior_dev | Per-user query activity |
| GET | /admin/analytics/cache-performance | admin, senior_dev | Cache hit rate and savings over time |

**Common query parameters (all endpoints):**

| Parameter | Type | Default | Description |
|---|---|---|---|
| from_date | ISO date string | 30 days ago | Start of date range |
| to_date | ISO date string | now | End of date range |
| source_id | UUID | null (all sources) | Filter to a specific data source |
| format | string | "component" | Response format: "component" (Phase 5 JSON) or "raw" (plain data) |

**Response format (format=component):**

Each endpoint returns a JSON array of component objects:

```json
[
  {
    "type": "chart",
    "chart_type": "line",
    "title": "Daily query volume (last 30 days)",
    "data": {
      "labels": ["2026-03-16", "2026-03-17", "..."],
      "datasets": [{"label": "Queries", "values": [23, 45, "..."]}]
    },
    "narrative": "Query volume averaged 34 per day this month, peaking on Wednesdays."
  },
  {
    "type": "table",
    "title": "Top users by query count",
    "data": {
      "headers": ["User", "Queries", "Last active"],
      "rows": [["Jane Smith", 142, "2026-04-08"], ["...","...","..."]]
    }
  }
]
```

**Response format (format=raw):**

For programmatic consumers, returns the underlying data without component wrapping:

```json
{
  "metric": "query_frequency",
  "from_date": "2026-03-16",
  "to_date": "2026-04-15",
  "data": {
    "daily": [{"date": "2026-03-16", "count": 23, "unique_users": 5}, "..."],
    "total": 1020,
    "avg_per_day": 34
  }
}
```

### 5.2 Aggregate dashboard endpoint

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | /admin/analytics/dashboard | admin, senior_dev | Returns all 5 metrics as a single multi-component response |

**Response:** A JSON array containing the component outputs from all 5 analytics functions, concatenated. The client renders them as a scrollable multi-panel view.

**Query parameters:** Same `from_date` and `to_date` as individual endpoints (applied to all metrics). No `source_id` filter (dashboard shows all sources).

**Response structure:**
```json
{
  "generated_at": "2026-04-15T14:30:00Z",
  "period": {"from": "2026-03-16", "to": "2026-04-15"},
  "components": [
    {"type": "metric_card", "title": "Overview", "data": {"metrics": [
      {"label": "Total queries (30d)", "value": "1,020", "change": "+12%"},
      {"label": "Active users", "value": "8", "change": "+2"},
      {"label": "Cache hit rate", "value": "37%", "change": "+5%"},
      {"label": "Knowledge base chunks", "value": "12,450", "change": "+340"}
    ]}},
    {"type": "chart", "...": "query frequency chart"},
    {"type": "progress", "...": "coverage gaps"},
    {"type": "chart", "...": "popular topics"},
    {"type": "table", "...": "user activity"},
    {"type": "chart", "...": "cache performance"}
  ]
}
```

The first component is always an overview `metric_card` summarizing the key numbers at a glance.

---

## 6. Gemini response_schema Upgrade

### 6.1 The problem

Phase 5's visual query pipeline (Section 13) uses a keyword heuristic to detect visual queries and injects a text instruction asking Gemini to return JSON. The component renderer then attempts to parse the response, falling back to regex extraction, then to the narrative field, then to a text-only re-query. This chain works but is fragile — Gemini sometimes returns JSON wrapped in markdown fences, or adds preamble text before the JSON, or uses slightly wrong field names.

### 6.2 The fix

Gemini's `GenerateContentConfig` supports a `response_schema` parameter that guarantees the response conforms to a specified JSON schema. When `response_schema` is set, Gemini is constrained to return only valid JSON matching the schema — no preamble, no fences, no invalid fields.

### 6.3 Implementation

**Changes to `gemini_client.py`:**

When the prompt builder detects a visual query (using the existing keyword heuristic from Phase 5 Section 13.2, which is kept as the detection mechanism), the Gemini API call is made with `response_schema` set to the component schema:

```python
from google.genai.types import GenerateContentConfig

config = GenerateContentConfig(
    temperature=0.2,
    max_output_tokens=2000,
    response_mime_type="application/json",
    response_schema=ComponentSchema.model_json_schema(),  # Convert Pydantic model to JSON schema dict
)
```

**Note:** Gemini's `response_schema` expects a JSON Schema dict, not a Pydantic model directly. The `model_json_schema()` method converts the Pydantic model to the correct format. Some versions of the `google-genai` library may accept Pydantic models directly and handle the conversion internally — verify with the installed version.

**Changes to `prompt_builder.py`:**

The `_VISUAL_INSTRUCTION` text block (Phase 5, line 127) is simplified. Instead of including the full JSON schema in the prompt text, it provides a brief instruction:

```
The user is requesting a visual representation. Return a JSON object describing
the visualization. The schema is enforced automatically — focus on choosing the
right component type and providing accurate data.
```

The schema enforcement is handled by `response_schema`, not by the prompt text.

**Changes to `component_renderer.py`:**

The regex fallback chain (Phase 5, line 32) is retired. With `response_schema`, the response is guaranteed valid JSON. The renderer simplifies to:

```python
def render_component(response_text: str) -> ComponentSchema | None:
    try:
        return ComponentSchema.model_validate_json(response_text)
    except ValidationError:
        return None  # Fall back to text display
```

The `narrative` field fallback is kept — if schema validation fails (which should be rare with `response_schema`), the system falls back to displaying the response as plain text.

### 6.4 Scope of change

This upgrade applies only to visual queries (where the keyword heuristic triggers). Normal text queries continue to use the existing streaming pipeline without `response_schema`. This means:

- Normal developer questions: no change (streaming text + citations)
- Visual admin queries via POST /query: upgraded to `response_schema`
- Analytics dashboard endpoints: no LLM involved (direct SQL → component JSON)

### 6.5 Backward compatibility

The Phase 5 keyword heuristic is kept as the detection mechanism. The change is in how the LLM call is configured (adding `response_schema`), not in how visual queries are detected. No changes to the query endpoint interface or SSE event format.

---

## 7. Ad-Hoc Visual Queries with Real Data

### 7.1 The gap

Even with `response_schema`, ad-hoc visual queries (e.g., "show me a chart of queries this week") still have a data problem. The LLM doesn't have access to the audit_logs or ChromaDB metadata — it can only work with the retrieved chunks, which are code and documentation, not analytics data.

### 7.2 Solution: analytics context injection

When a visual query is detected, the prompt builder injects a summary of available analytics data into the prompt before sending to Gemini:

1. Keyword heuristic detects a visual query
2. The analytics service runs a lightweight summary (cached, refreshed hourly):
   - Total queries last 7 days
   - Top 5 most-queried sources
   - Cache hit rate
   - Active user count
   - Chunk count per source
3. This summary is injected into the prompt as a `[ANALYTICS CONTEXT]` block, alongside the normal `[SOURCE N]` blocks from retrieval
4. Gemini uses this real data to populate the component JSON
5. `response_schema` ensures the output is valid

**Prompt addition for visual queries:**
```
[ANALYTICS CONTEXT]
Period: 2026-04-09 to 2026-04-15
Total queries: 234
Active users: 8
Cache hit rate: 37%
Top sources queried: backend-api (89), engineering-docs (67), frontend-app (45), infra (23), overview (10)
Knowledge base: 12,450 chunks across 5 sources
Recent update: 14 auto-updates this week (3 significant, 11 minor)
[END ANALYTICS CONTEXT]
```

### 7.3 Canned vs. ad-hoc

There are now two paths to visual responses:

| Path | Trigger | Data source | LLM involved? |
|---|---|---|---|
| Canned dashboard | GET /admin/analytics/dashboard or `arcana dashboard` | Direct SQL/ChromaDB queries | No |
| Ad-hoc visual query | POST /query with visual keywords (e.g., "show me query trends") | Analytics summary injected into LLM prompt | Yes (with response_schema) |

The canned dashboard is always accurate (real queries, no LLM interpretation). Ad-hoc visual queries are more flexible (the user can ask any question) but depend on the LLM correctly using the injected analytics context.

---

## 8. CLI Dashboard

### 8.1 Command

The dashboard command is added as a top-level Typer subcommand (`arcana dashboard`), consistent with Phase 6's flat command structure (`arcana users`, `arcana sources`, etc.). It is admin-gated at the API level — non-admin users receive a 403 error with a clear message.

```bash
arcana dashboard                             # Full dashboard (all 5 metrics)
arcana dashboard --metric query-frequency    # Single metric
arcana dashboard --metric coverage-gaps
arcana dashboard --from 2026-03-01 --to 2026-03-31  # Custom date range
arcana dashboard --raw                       # Output raw JSON (for piping)
```

### 8.2 Multi-panel rendering

The full dashboard renders as a vertical stack of Rich panels:

```
╭─ Arcana Dashboard ─ 2026-03-16 to 2026-04-15 ──────────╮
│                                                          │
│  ┌─ Overview ──────────────────────────────────────────┐ │
│  │ Total queries (30d)  Active users   Cache hit rate  │ │
│  │      1,020 (+12%)        8 (+2)       37% (+5%)    │ │
│  │ KB chunks: 12,450 (+340)                            │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─ Query volume ──────────────────────────────────────┐ │
│  │ ▇▇▇▇▇▇▇▇▇▇ 45                                     │ │
│  │ ▇▇▇▇▇▇▇ 34                                         │ │
│  │ ▇▇▇▇▇▇▇▇ 38                                        │ │
│  │ ...                                                  │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─ Coverage ──────────────────────────────────────────┐ │
│  │ backend-api    ████████████████████░░░░  82%        │ │
│  │ frontend-app   ██████████████░░░░░░░░░  65%        │ │
│  │ infra          ████████░░░░░░░░░░░░░░░  40%        │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─ Popular topics ────────────────────────────────────┐ │
│  │  1. backend-api        89 queries                   │ │
│  │  2. engineering-docs   67 queries                   │ │
│  │  3. frontend-app       45 queries                   │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─ User activity ─────────────────────────────────────┐ │
│  │ User          Queries  Last active  Cache hit %     │ │
│  │ Jane Smith      142    2h ago         41%           │ │
│  │ John Doe         89    1d ago         33%           │ │
│  │ ...                                                  │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─ Cache performance ─────────────────────────────────┐ │
│  │ Hit rate: 37% (+5% vs last month)                   │ │
│  │ Estimated savings: ~$4.20 in API costs              │ │
│  │ Cache entries: 234                                   │ │
│  └──────────────────────────────────────────────────────┘ │
╰──────────────────────────────────────────────────────────╯
```

Each panel is rendered using the existing Phase 6 Rich rendering infrastructure (`rendering/components.py`). The dashboard command calls the aggregate endpoint, receives the component array, and renders each component sequentially.

---

## 9. Cursor Dashboard

### 9.1 Dashboard button

A "Dashboard" button is added to the Cursor sidebar header, next to the settings gear icon. Clicking it:

1. Calls GET /admin/analytics/dashboard with the user's API key
2. If the user is not admin or senior_dev, the endpoint returns 403 and the button shows a tooltip: "Admin access required"
3. On success, the webview clears the chat area and renders a multi-component dashboard view

### 9.2 Multi-component rendering

The dashboard response contains an array of components. The Cursor webview renders them as a vertical scrollable stack:

- `metric_card` → row of styled cards (existing renderer)
- `chart` → Chart.js canvas (existing renderer)
- `table` → sortable HTML table (existing renderer)
- `progress` → styled progress bars (existing renderer)

Each component is wrapped in a collapsible section with its title as the header. All sections are expanded by default.

### 9.3 Refresh and navigation

- A "Refresh" button at the top of the dashboard re-fetches all data
- A "Back to chat" button returns to the normal chat interface
- The dashboard auto-refreshes every 5 minutes while visible (configurable, can be disabled)
- Date range selector at the top allows filtering (last 7 days, 30 days, 90 days, custom)

### 9.4 Minimal code changes

The dashboard rendering reuses the existing component renderer from Phase 6. The only new code is:

- A "Dashboard" button in the webview HTML
- A message handler that calls the analytics endpoint and passes the component array to the existing renderer
- A date range selector UI element
- A "Back to chat" navigation handler

Estimated: ~80–100 lines of TypeScript/HTML.

---

## 10. Data Requirements

### 10.1 Minimum data for meaningful analytics

The analytics service returns empty-state messages when insufficient data is available:

| Metric | Minimum data | Empty-state message |
|---|---|---|
| Query frequency | At least 1 query in audit_logs | "No queries recorded yet. Analytics will appear once developers start using Arcana." |
| Coverage gaps | At least 1 indexed source | "No sources indexed. Connect a GitHub repo or Notion workspace first." |
| Popular topics | At least 10 queries | "Not enough queries to identify patterns. Check back after more usage." |
| User activity | At least 1 active user with queries | "No user activity recorded." |
| Cache performance | At least 10 queries (to calculate meaningful hit rate) | "Not enough queries to measure cache performance." |

### 10.2 Analytics summary cache

The lightweight analytics summary (Section 7.2) used for ad-hoc visual queries is cached in memory with a 1-hour TTL. This prevents expensive aggregation queries on every visual request. The cache is invalidated when the dashboard endpoint is called with `?refresh=true`.

---

## 11. Audit Logging

Analytics endpoint calls are logged in audit_logs with a new event type:

| New event type | When logged |
|---|---|
| analytics_viewed | When an admin views the dashboard or any individual metric endpoint |

This requires extending the Phase 4 `event_type` enum via Alembic migration.

The `details` JSON for analytics_viewed events includes:
```json
{
  "metric": "dashboard",  // or "query_frequency", "coverage_gaps", etc.
  "from_date": "2026-03-16",
  "to_date": "2026-04-15",
  "format": "component"
}
```

---

## 12. Environment Variables (additions)

| Variable | Type | Default | Description |
|---|---|---|---|
| ANALYTICS_CACHE_TTL_MINUTES | Integer | 60 | TTL for the analytics summary cache used in ad-hoc visual queries |
| ANALYTICS_DEFAULT_DAYS | Integer | 30 | Default date range for analytics when no from_date is specified |

---

## 13. Acceptance Criteria

1. **Query frequency endpoint:** GET /admin/analytics/query-frequency returns a valid component JSON array with a line chart showing daily query volume and a table of top users. The data matches actual audit_log records.

2. **Coverage gaps endpoint:** GET /admin/analytics/coverage-gaps returns progress bars showing indexed-file-to-total-file ratio per repo. A repo with 200 indexed files out of 250 total shows 80%.

3. **Popular topics endpoint:** GET /admin/analytics/popular-topics returns a bar chart of most-queried sources with correct counts from audit_logs.

4. **User activity endpoint:** GET /admin/analytics/user-activity returns a table with user names, query counts, last active timestamps, and cache hit ratios. Data matches audit_logs.

5. **Cache performance endpoint:** GET /admin/analytics/cache-performance returns a line chart of daily hit rate and a metric card with current totals. Data matches audit_logs cache_hit flags.

6. **Dashboard endpoint:** GET /admin/analytics/dashboard returns all 5 metrics as a single component array with an overview metric_card first. Total response time < 2 seconds.

7. **Raw format:** GET /admin/analytics/query-frequency?format=raw returns plain JSON data without component wrapping. Suitable for programmatic consumption.

8. **Date range filtering:** All endpoints accept from_date and to_date parameters. A request with from_date=2026-04-01&to_date=2026-04-07 returns only data from that week.

9. **Empty state:** With zero queries in audit_logs, the query frequency endpoint returns a component with a meaningful empty-state message, not an error or empty chart.

10. **Auth enforcement:** GET /admin/analytics/dashboard returns 403 for users with role viewer or dev. Returns 200 for senior_dev and admin.

11. **response_schema upgrade:** A visual query via POST /query (e.g., "show me a chart of query volume") returns valid component JSON without regex fallback. The response conforms exactly to the ComponentSchema Pydantic model.

12. **Ad-hoc visual query with real data:** Asking "show me which repos are most queried" via POST /query returns a chart with actual query counts from audit_logs, not hallucinated numbers. The analytics context is visible in the prompt (verifiable via debug logging).

13. **CLI dashboard:** `arcana dashboard` renders a multi-panel view with all 5 metrics displayed as Rich panels. The overview metric card shows real numbers.

14. **CLI single metric:** `arcana dashboard --metric coverage-gaps` renders only the coverage gaps panel.

15. **CLI raw output:** `arcana dashboard --raw` outputs valid JSON to stdout (pipeable to jq or other tools).

16. **Cursor Dashboard button:** Clicking "Dashboard" in the Cursor sidebar renders a multi-component view with all 5 metrics. Charts are interactive (Chart.js hover tooltips). Tables are sortable.

17. **Cursor auth gating:** If the logged-in user is not admin/senior_dev, clicking Dashboard shows "Admin access required" instead of data.

18. **Cursor date range:** The date range selector at the top of the dashboard changes the period. Selecting "Last 7 days" refreshes all components with the shorter range.

19. **Cursor back to chat:** Clicking "Back to chat" returns to the normal chat interface with previous conversation intact (if session is still active).

20. **Analytics audit logging:** Every dashboard and metric endpoint call is logged in audit_logs with event_type=analytics_viewed and correct details.

21. **Pydantic type safety:** All analytics functions return `list[ComponentSchema]`. The component JSON response from every endpoint validates against the ComponentSchema model.

22. **Tests:** At least 22 tests covering: each analytics function with real test data (5 tests), each endpoint response format (5 tests), empty state handling (2 tests), date range filtering (2 tests), auth enforcement (2 tests), response_schema Gemini upgrade (2 tests, mocked), ad-hoc visual query with analytics context (1 test), CLI dashboard rendering (1 test), audit logging (1 test), Pydantic validation (1 test).

---

## 14. Technical Dependencies (additions)

| Package | Version | Purpose |
|---|---|---|
| scikit-learn | >=1.5 | K-means clustering for embedding-based popular topics (stretch goal only) |

All other infrastructure is reused from Phases 1–7. If the lightweight popular topics approach (source frequency) is sufficient, scikit-learn is not needed.

---

## 15. Estimated Effort

| Task | Estimate | Notes |
|---|---|---|
| Analytics service — query frequency function | 3–4 hours | SQL queries, breakdowns, component formatting |
| Analytics service — coverage gaps function | 3–4 hours | ChromaDB metadata queries, ratio calculation |
| Analytics service — popular topics function | 2–3 hours | Lightweight approach (source frequency). Add 3–4 hours for embedding clustering stretch. |
| Analytics service — user activity function | 2–3 hours | SQL joins, aggregation |
| Analytics service — cache performance function | 2–3 hours | SQL aggregation, metric card formatting |
| ComponentSchema Pydantic models | 2–3 hours | Shared models, validation, raw format support |
| Analytics API endpoints | 3–4 hours | 6 endpoints (5 individual + dashboard), query params, auth |
| Gemini response_schema upgrade | 3–4 hours | Config changes, retire regex fallback, test with real queries |
| Ad-hoc visual query analytics context injection | 2–3 hours | Summary cache, prompt injection, hourly refresh |
| CLI dashboard command | 2–3 hours | Multi-panel Rich rendering, --metric filter, --raw output |
| Cursor Dashboard button + rendering | 3–4 hours | Button, endpoint call, multi-component view, date selector, back-to-chat |
| Alembic migration + audit logging | 1–2 hours | New event type, logging integration |
| Test suite | 6–8 hours | 22+ tests across analytics, endpoints, clients |

**Total estimated effort: 34–48 hours (approximately 1.5–2 weeks at thesis pace)**

---

## 16. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| SQL aggregation queries are slow on large audit_logs tables | Medium | Add indexes on audit_logs(timestamp, event_type) and audit_logs(user_id). For the thesis scale (<100K rows), queries will be fast. Production: add materialized views or pre-aggregated daily summaries. |
| Gemini response_schema rejects valid component structures | Low | Test the schema against Gemini before deployment. response_schema is well-supported for structured output. Keep the text fallback as a safety net. |
| Coverage gap calculation is inaccurate if file count changed since ingestion | Low | The file count from Phase 2 ingestion is a snapshot. Re-running coverage gaps after a Phase 7 auto-update reflects the latest state. For real-time accuracy, the updater could refresh the file count on each run. |
| Analytics summary cache serves stale data for ad-hoc visual queries | Low | 1-hour TTL is acceptable — analytics data doesn't change second-by-second. The canned dashboard endpoint always queries fresh data. |
| Admin dashboard exposes team-level data to senior_devs who should only see their team | Medium | For the thesis (single tenant, small team), all senior_devs see all analytics. Production: scope user activity and query frequency by the viewer's team. Coverage gaps and cache performance remain global. |

---

## 17. Known Limitations

| ID | Limitation | Production path |
|---|---|---|
| L8.1 | Analytics are point-in-time snapshots, not real-time streaming. The dashboard shows data as of the last query, not a live updating view. | Add WebSocket-based live updates for the dashboard. Push new data points as queries arrive. Requires a pub/sub mechanism (Redis, SSE long-poll). |
| L8.2 | Popular topics uses source frequency as a proxy, not true semantic topic clustering. "Queries about authentication" and "queries about the auth middleware" would be counted under the same source but not recognized as the same topic. | Implement embedding-based clustering (k-means on query embeddings). Requires scikit-learn and more compute but produces genuine topic groups with representative labels. |
| L8.3 | No export capability. Dashboards can't be saved as PDF, shared as a link, or scheduled as email reports. | Add export endpoints that render components to PDF (via headless browser) or CSV. Add scheduled email reports using the same analytics functions. |
| L8.4 | All analytics are admin-scoped. Individual developers can't see their own usage patterns (e.g., "what topics have I been asking about?"). | Add a GET /analytics/me endpoint scoped to the authenticated user's own audit_logs. Return personal query history, frequently asked topics, and onboarding progress. |
| L8.5 | The response_schema upgrade only applies to visual queries. Non-visual queries still use unstructured text output from Gemini, which may occasionally have formatting inconsistencies. | Evaluate whether response_schema can be used for citation-structured text responses too (e.g., guaranteeing the REFERENCES section format). This would require a more complex schema that accommodates free text + structured citations. |

These limitations are documented in the [Arcana Limitations & Design Decisions Log](./Arcana_Limitations_and_Design_Decisions.md).

---

*End of document*