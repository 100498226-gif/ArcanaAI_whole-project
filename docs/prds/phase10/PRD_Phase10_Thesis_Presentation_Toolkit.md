# PRD — Thesis Presentation Toolkit: Demo Mode, Retrieval Evaluation & Architecture Documentation

**Product:** Arcana — AI-Powered Developer Onboarding Platform
**Type:** Cross-cutting (not a numbered phase — supplements Phases 1–9)
**Version:** 1.0
**Date:** April 2026
**LLM Provider:** Gemini APIs
**Depends on:** Phases 1–6 minimum (Tier 1 complete). Phases 7–9 enhance the demo but are not required.

---

## 1. Overview

Arcana is a technically complete system after Phase 6 (Tier 1) — it ingests code and documentation, answers questions with citations, and respects RBAC. But a thesis defense requires more than a working system. It requires a compelling demonstration, quantitative evidence that the system works well, and clear documentation that maps architectural decisions to code.

This toolkit adds three capabilities that don't change how Arcana works but transform how it's presented and evaluated:

1. **Demo mode** — an isolated environment with pre-populated synthetic data that showcases every Arcana feature without touching real project data. Activated by a flag, completely reversible.

2. **Retrieval quality evaluation** — a repeatable benchmark that measures how well Arcana's retrieval pipeline finds the right chunks for representative developer questions. Produces precision, recall, and MRR metrics.

3. **Architecture-to-code mapping** — a living document in the README and a separate reference that maps every architectural component (from the Phase diagrams) to its exact file path in the codebase.

---

## 2. Demo Mode

### 2.1 Purpose

During a thesis presentation, you need to show analytics dashboards with realistic data, demonstrate the full query pipeline with predictable results, and walk through features like the weekly review and revert flow — all without worrying about API rate limits, empty databases, or live data behaving unpredictably.

Demo mode provides a self-contained, reproducible environment where every feature works perfectly with pre-loaded synthetic data.

### 2.2 Activation

Demo mode is controlled by a single environment variable:

```
ARCANA_DEMO_MODE=true
```

When enabled:

- A separate SQLite database is used: `data/demo.db` (instead of `data/arcana.db`)
- A separate ChromaDB persistence directory is used: `data/demo_chromadb/` (instead of `data/chromadb/`)
- The demo seed script runs automatically on startup if the demo database is empty
- A visual indicator appears in all surfaces:
  - Streamlit: orange banner at the top — "DEMO MODE — Using synthetic data"
  - CLI: colored prefix on every output — `[DEMO]`
  - Cursor: orange dot in the sidebar header (next to the green connection dot)
- All write operations (user creation, sync triggers, cache operations) affect only the demo database
- The real production database is completely untouched

**Deactivation:** Set `ARCANA_DEMO_MODE=false` (or remove the variable) and restart. The demo data remains in `data/demo.db` and `data/demo_chromadb/` but is not loaded. No cleanup needed — the demo and production data are physically separate.

### 2.3 Demo seed script

A `make demo-seed` command (or `python -m arcana.demo.seed`) populates the demo environment with realistic synthetic data.

#### 2.3.1 Users (6 users)

| Name | Email | Role | Team | Queries (30d) | Purpose in demo |
|---|---|---|---|---|---|
| Arcana Admin | admin@demo.arcana | admin | platform | 15 | System administrator, reviews weekly summaries |
| Sarah Chen | sarah@demo.arcana | senior_dev | backend | 142 | Power user, frequent querier, demonstrates high activity |
| James Wilson | james@demo.arcana | dev | frontend | 89 | Active developer, different team scope |
| Priya Patel | priya@demo.arcana | dev | backend | 45 | Moderate user, same team as Sarah |
| Alex Kim | alex@demo.arcana | dev | infra | 12 | Low-activity user, demonstrates "who needs help" analytics |
| Demo Viewer | viewer@demo.arcana | viewer | — | 3 | Demonstrates RBAC restrictions |

Each user gets a predictable API key: `arc_demo_{role}_{name}` (e.g., `arc_demo_admin_arcana`, `arc_demo_dev_sarah`). These are deterministic so the presenter doesn't need to look them up.

#### 2.3.2 Data sources (3 sources)

| Source | Type | Access scope | Chunks | Status |
|---|---|---|---|---|
| demo/backend-api | github_repo | backend-team | ~800 code + 50 docs | active |
| demo/frontend-app | github_repo | frontend-team | ~400 code + 30 docs | active |
| Demo Engineering Wiki | notion_workspace | engineering-docs | ~200 doc sections | active |

**Chunk generation strategy:**

The seed script does NOT clone real repos or call real APIs. Instead, it generates synthetic but realistic chunks:

- **Code chunks** are templated from common patterns: authentication middleware, API route handlers, database models, utility functions, configuration files. Each chunk has realistic file paths (`src/auth/middleware.py`, `src/api/routes/users.py`), function names, language annotations, and line numbers.
- **Documentation chunks** are templated from common engineering documentation: architecture overview, API reference, onboarding guide, deployment runbook, service dependency map. Each has realistic page paths, section headings, and cross-references to code chunks.
- **Cross-references** are pre-computed: the "Auth Service Architecture" doc chunk references `src/auth/middleware.py`, etc.

All chunks are embedded using the real embedding model (Gemini) and stored in the demo ChromaDB collections. This means vector search works correctly — semantic queries return semantically relevant results.

**Estimated seed time:** ~2 minutes (embedding ~1500 chunks at 100/batch).

#### 2.3.3 Audit logs (30 days of synthetic activity)

The seed script generates 30 days of realistic query history in audit_logs:

- ~1000 total query events distributed across users (weighted by their activity levels)
- Queries are sampled from a pool of 50 realistic developer questions:
  - "How does the authentication middleware validate tokens?"
  - "Where is the user profile API endpoint defined?"
  - "What database migrations exist for the payments table?"
  - "How does the frontend handle auth token refresh?"
  - "What's the deployment process for the backend service?"
  - (45 more spanning different topics, sources, and complexity levels)
- Each query event includes realistic `details` JSON: `sources_accessed`, `response_time_ms` (200-4000ms, normally distributed), `cache_hit` (hit rate increasing over time to ~35%), `chunks_retrieved` (5-10)
- Events are distributed across timestamps with realistic patterns: more queries on weekdays, fewer on weekends, slight increase over time (simulating growing adoption)
- Additional event types are generated: user_created, permission_granted (at the start of the 30-day period), analytics_viewed (by admin, weekly)

#### 2.3.4 Update records (Phase 7 data, if Phase 7 is implemented)

If Phase 7 is built, the seed script also generates:

- 4 weeks of daily auto-update records (~60 total)
- A mix of file_added, file_modified, file_deleted changes
- Significance distribution: ~20% significant, ~80% minor
- LLM-generated summaries (pre-computed, not generated at seed time — stored as static text to avoid API calls)
- 1 reverted update with an admin correction (demonstrates the revert flow)
- 4 weekly review summaries (one per week, pre-computed text)

#### 2.3.5 Semantic cache (pre-warmed)

The seed script pre-populates the demo `query_cache` collection with 20 cached query-response pairs. These ensure that during the demo:

- Repeated questions hit the cache instantly (demonstrating cache behavior)
- The cache stats show realistic hit rate numbers
- The presenter can show a cache hit vs. miss side by side

#### 2.3.6 Permissions matrix

| User | backend-api | frontend-app | Engineering Wiki |
|---|---|---|---|
| Arcana Admin | full access | full access | full access |
| Sarah Chen | read | — | read |
| James Wilson | — | read | read |
| Priya Patel | read | — | read |
| Alex Kim | read | read | read |
| Demo Viewer | read (backend only) | — | — |

This matrix demonstrates RBAC: Sarah and James asking the same question get different results because they have access to different repos.

### 2.4 Demo query routing

When demo mode is active and a query is made via POST /query, the system uses the demo databases for retrieval. The Gemini API is still called for response generation (the demo doesn't mock the LLM — real AI answers are more impressive in a presentation).

**One exception:** If the presenter wants to avoid Gemini API costs during rehearsal, a `DEMO_MOCK_LLM=true` flag returns pre-computed responses for the 50 seeded questions. This is useful for rehearsal only — the actual presentation should use real Gemini for authenticity.

### 2.5 Demo CLI commands

```bash
# Activate demo mode
export ARCANA_DEMO_MODE=true

# Seed the demo environment
make demo-seed

# Verify demo data
arcana demo status          # Shows user count, chunk count, audit log count, cache entries

# Reset demo data (wipe and re-seed)
make demo-reset

# Run a demo query as a specific user
arcana ask "how does auth work?" --api-key arc_demo_dev_sarah

# Show RBAC difference
arcana ask "how does auth work?" --api-key arc_demo_dev_james
# (Returns different results — James doesn't have backend access)

# Show cache behavior
arcana ask "how does auth work?" --api-key arc_demo_dev_sarah   # First: full pipeline
arcana ask "how does auth work?" --api-key arc_demo_dev_sarah   # Second: cache hit (fast)

# Deactivate demo mode
unset ARCANA_DEMO_MODE
```

### 2.6 Implementation

| File | Purpose |
|---|---|
| backend/arcana/demo/__init__.py | Demo mode detection and database routing |
| backend/arcana/demo/seed.py | Main seed script orchestrator |
| backend/arcana/demo/users.py | User and permission generation |
| backend/arcana/demo/chunks.py | Synthetic chunk templates and embedding |
| backend/arcana/demo/audit.py | Audit log event generation |
| backend/arcana/demo/updates.py | Update record and weekly review generation (Phase 7) |
| backend/arcana/demo/cache.py | Pre-warmed cache entry generation |
| backend/arcana/demo/questions.py | Pool of 50 realistic demo questions |
| backend/arcana/demo/responses.py | Pre-computed mock responses (for DEMO_MOCK_LLM mode) |

### 2.7 Environment variables

| Variable | Type | Default | Description |
|---|---|---|---|
| ARCANA_DEMO_MODE | Boolean | false | Enable demo mode with isolated synthetic data |
| DEMO_MOCK_LLM | Boolean | false | Use pre-computed responses instead of calling Gemini (rehearsal only) |

---

## 3. Retrieval Quality Evaluation

### 3.1 Purpose

The thesis committee will ask: "How good are the answers?" Subjective impressions aren't sufficient — you need quantitative metrics that measure retrieval quality. This section defines a repeatable evaluation framework.

### 3.2 Evaluation methodology

The evaluation measures retrieval quality, not generation quality. It answers: "Given a question, does the pipeline find the right chunks?" Generation quality (how well Gemini turns chunks into an answer) is harder to measure and depends on prompt engineering — retrieval quality is the foundation.

### 3.3 Gold standard dataset

A manually curated set of 20 evaluation queries, each with a list of "ideal" chunk IDs that should be retrieved.

**Dataset structure:**

```json
[
  {
    "query": "How does the authentication middleware validate tokens?",
    "ideal_chunks": ["backend-api:src/auth/middleware.py:verify_token:45-92", "backend-api:src/auth/jwt.py:decode_jwt:10-35"],
    "ideal_docs": ["notion:Auth Service Architecture:Token Verification"],
    "category": "semantic",
    "difficulty": "easy"
  },
  {
    "query": "getUserProfile",
    "ideal_chunks": ["backend-api:src/api/routes/users.py:getUserProfile:120-145"],
    "ideal_docs": [],
    "category": "exact_match",
    "difficulty": "easy"
  },
  {
    "query": "What happens when a payment fails and the user needs a refund?",
    "ideal_chunks": ["backend-api:src/payments/refund.py:process_refund:30-80", "backend-api:src/payments/webhook.py:handle_failure:55-90"],
    "ideal_docs": ["notion:Payment Service > Refund Flow", "notion:Error Handling Guide > Payment Errors"],
    "category": "multi_source",
    "difficulty": "hard"
  }
]
```

**Query categories (5 each, 20 total):**

| Category | What it tests | Example |
|---|---|---|
| semantic | Vector search — conceptual understanding | "How does auth work?" |
| exact_match | BM25 — function names, config keys | "getUserProfile" |
| multi_source | Cross-reference — code + docs together | "What's the refund flow and where is it implemented?" |
| role_scoped | RBAC — different users get different results | Same query, two users with different scopes |

**Difficulty levels:**
- Easy: answer is in one chunk from one source
- Medium: answer spans 2-3 chunks, possibly from different sources
- Hard: answer requires cross-referencing code and documentation, or the question is ambiguous

### 3.4 Building the gold standard

The gold standard is built manually by the system developer (you) using the demo dataset:

1. Activate demo mode
2. For each query, manually inspect the demo chunks and identify which ones are truly relevant
3. Record the chunk IDs as the "ideal" set
4. Store in `backend/arcana/eval/gold_standard.json`

This takes ~2-3 hours but only needs to be done once. The dataset is committed to the repo and used for all subsequent evaluations.

### 3.5 Metrics

For each query, the evaluation measures:

**Precision@k (k=5, k=10):**
What fraction of the top-k retrieved chunks are in the ideal set?
```
P@k = |retrieved_top_k ∩ ideal| / k
```

**Recall@k (k=10, k=20):**
What fraction of the ideal chunks were found in the top-k?
```
R@k = |retrieved_top_k ∩ ideal| / |ideal|
```

**Mean Reciprocal Rank (MRR):**
How high is the first relevant chunk in the result list?
```
MRR = 1/N Σ (1 / rank_of_first_relevant_chunk)
```

**Hit Rate@k (k=5):**
What fraction of queries have at least one relevant chunk in the top-k?
```
HR@k = |queries_with_at_least_one_hit_in_top_k| / N
```

### 3.6 Evaluation script

```bash
# Run the full evaluation
arcana eval run                           # Runs all 20 queries, prints metrics
arcana eval run --category semantic       # Run only semantic queries
arcana eval run --verbose                 # Show per-query results

# Output
arcana eval run --output eval_results.json   # Save results as JSON
arcana eval run --output eval_results.csv    # Save as CSV for thesis tables
```

**Output format:**

```
╭─ Arcana Retrieval Evaluation ───────────────────────────╮
│                                                          │
│  Queries evaluated: 20                                   │
│  Using gold standard: eval/gold_standard.json            │
│                                                          │
│  ┌─ Overall Metrics ───────────────────────────────────┐ │
│  │ Precision@5:  0.72                                  │ │
│  │ Precision@10: 0.58                                  │ │
│  │ Recall@10:    0.85                                  │ │
│  │ Recall@20:    0.93                                  │ │
│  │ MRR:          0.81                                  │ │
│  │ Hit Rate@5:   0.95                                  │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─ By Category ───────────────────────────────────────┐ │
│  │ Category      P@5   R@10  MRR   HR@5               │ │
│  │ semantic      0.80  0.90  0.88  1.00               │ │
│  │ exact_match   0.76  0.84  0.92  1.00               │ │
│  │ multi_source  0.64  0.80  0.72  0.80               │ │
│  │ role_scoped   0.68  0.86  0.71  1.00               │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─ By Difficulty ─────────────────────────────────────┐ │
│  │ Difficulty    P@5   R@10  MRR                       │ │
│  │ easy          0.84  0.95  0.92                      │ │
│  │ medium        0.72  0.85  0.80                      │ │
│  │ hard          0.56  0.70  0.65                      │ │
│  └─────────────────────────────────────────────────────┘ │
╰──────────────────────────────────────────────────────────╯
```

### 3.7 Evaluation implementation

| File | Purpose |
|---|---|
| backend/arcana/eval/__init__.py | Evaluation module |
| backend/arcana/eval/gold_standard.json | Curated query-answer pairs |
| backend/arcana/eval/runner.py | Runs queries through the retrieval pipeline (without LLM call), collects top-k chunks, computes metrics |
| backend/arcana/eval/metrics.py | Precision, recall, MRR, hit rate calculation functions |
| backend/arcana/eval/report.py | Formats results as Rich tables and exports to JSON/CSV |
| cli/arcana_cli/commands/eval.py | CLI `arcana eval` command group |

### 3.8 How to use in the thesis

The evaluation section of your thesis should include:

1. **Methodology:** "We evaluated retrieval quality using a gold standard dataset of 20 queries across 4 categories (semantic, exact match, multi-source, role-scoped) with manually identified ideal retrieval targets."

2. **Results table:** The metrics from `arcana eval run --output eval_results.csv`, formatted as a thesis table.

3. **Analysis:** "Semantic queries achieved the highest precision (0.80 P@5) due to the vector search component. Exact match queries scored highest MRR (0.92) thanks to BM25 keyword search. Multi-source queries showed lower precision (0.64 P@5), indicating room for improvement in cross-reference boosting."

4. **Ablation comparison (optional but impressive):** Run the evaluation three ways and compare:
   - Vector only (disable BM25): shows BM25's contribution
   - BM25 only (disable vector): shows vector search's contribution
   - Hybrid (both): shows the combined improvement

```bash
arcana eval run --search-mode vector-only --output eval_vector.csv
arcana eval run --search-mode bm25-only --output eval_bm25.csv
arcana eval run --search-mode hybrid --output eval_hybrid.csv
```

### 3.9 Environment variables

| Variable | Type | Default | Description |
|---|---|---|---|
| EVAL_TOP_K | Integer | 20 | Maximum k for retrieval during evaluation |
| EVAL_SKIP_LLM | Boolean | true | Skip LLM generation during eval (only measure retrieval) |

---

## 4. Architecture-to-Code Mapping

### 4.1 Purpose

The thesis committee will read the code. Without a map, they'll spend 30 minutes navigating the monorepo before understanding what they're looking at. This mapping is a reference document that connects every architectural concept (from the PRDs and diagrams) to its exact location in the codebase.

### 4.2 Format

A dedicated `docs/ARCHITECTURE.md` file with two sections: a component map (table) and a data flow trace (narrative).

### 4.3 Component map

| Architectural component | Phase | Primary file(s) | Description |
|---|---|---|---|
| **Ingestion** | | | |
| GitHub connector | 2 | `backend/arcana/ingestion/github.py` | Repo cloning, file traversal, PAT auth |
| Notion connector | 3 | `backend/arcana/ingestion/notion.py` | Block extraction, page hierarchy traversal |
| AST code chunker | 2 | `backend/arcana/ingestion/chunkers/code.py` | tree-sitter parsing, function/class boundaries |
| Line-based chunker | 2 | `backend/arcana/ingestion/chunkers/fallback.py` | 80-120 line blocks with overlap |
| Document chunker | 2, 3 | `backend/arcana/ingestion/chunkers/docs.py` | Heading-based splitting, breadcrumb headers |
| Embedding pipeline | 2 | `backend/arcana/ingestion/embedder.py` | Batch embedding via Gemini, configurable provider |
| DualStore | 5 | `backend/arcana/storage/dual_store.py` | Wraps ChromaDB + FTS5 for atomic dual-write |
| **Storage** | | | |
| Vector store (ChromaDB) | 1 | `backend/arcana/storage/vector_store.py` | Collection management, similarity search |
| Keyword index (FTS5) | 5 | `backend/arcana/storage/keyword_store.py` | SQLite FTS5 table, BM25 search |
| Relational DB (SQLite) | 1 | `backend/arcana/database.py` | SQLAlchemy engine, session factory |
| Database models | 1, 4, 7 | `backend/arcana/models/` | users.py, data_source.py, audit_log.py, permission.py, update_record.py |
| **RBAC** | | | |
| Permission filter service | 4 | `backend/arcana/services/permission_service.py` | Scope resolution, ChromaDB + FTS5 filter generation |
| Auth middleware | 4 | `backend/arcana/middleware/auth.py` | API key validation, role checking |
| **Retrieval pipeline** | | | |
| Hybrid search | 5 | `backend/arcana/services/retrieval/hybrid_search.py` | Parallel vector + BM25, async execution |
| Reciprocal rank fusion | 5 | `backend/arcana/services/retrieval/fusion.py` | RRF algorithm, deduplication |
| Re-ranker | 5 | `backend/arcana/services/retrieval/reranker.py` | Cross-encoder or Cohere, configurable backend |
| Context assembly | 5 | `backend/arcana/services/retrieval/context.py` | Token budget, source ordering, truncation |
| Semantic cache | 5 | `backend/arcana/services/cache.py` | Query embedding cache, scope validation, TTL |
| **LLM** | | | |
| Gemini client | 5 | `backend/arcana/services/gemini_client.py` | API calls, streaming, response_schema config |
| Prompt builder | 5 | `backend/arcana/services/prompt_builder.py` | System prompt, source formatting, role context |
| Citation formatter | 5 | `backend/arcana/services/citation.py` | Stream + cite, reference extraction, code block formatting |
| Component renderer | 5, 8 | `backend/arcana/services/component_renderer.py` | Visual query detection, JSON validation, fallback |
| **Analytics** | | | |
| Analytics service | 8 | `backend/arcana/services/analytics.py` | 5 typed query functions, SQL/ChromaDB queries |
| Analytics endpoints | 8 | `backend/arcana/routers/analytics.py` | GET /admin/analytics/* endpoints |
| **Auto-updater** | | | |
| Change detector (GitHub) | 7 | `backend/arcana/updater/github_diff.py` | GitHub API compare, file classification |
| Change detector (Notion) | 7 | `backend/arcana/updater/notion_diff.py` | Edit time comparison, page change detection |
| Update proposer | 7 | `backend/arcana/updater/proposer.py` | LLM summary generation, update record storage |
| Weekly review generator | 7 | `backend/arcana/updater/weekly_review.py` | Friday narrative generation, alert system |
| Revert handler | 7 | `backend/arcana/updater/revert.py` | Snapshot restoration, correction chunk creation |
| **API layer** | | | |
| FastAPI app factory | 1 | `backend/arcana/main.py` | App creation, middleware, router mounting |
| Health endpoints | 1 | `backend/arcana/routers/health.py` | /health, /health/db, /health/ready |
| Admin endpoints | 4 | `backend/arcana/routers/admin.py` | User CRUD, permissions, sources, audit logs |
| Query endpoint | 5 | `backend/arcana/routers/query.py` | POST /query (SSE streaming) |
| Updater endpoints | 7 | `backend/arcana/routers/updater.py` | Review, revert, history, manual trigger |
| **Client surfaces** | | | |
| Cursor extension entry | 6 | `cursor/src/extension.ts` | Activation, command registration |
| Sidebar provider | 6 | `cursor/src/sidebar/SidebarProvider.ts` | Webview lifecycle management |
| Webview chat UI | 6 | `cursor/webview/main.js` | SSE handling, markdown rendering, citation clicks |
| Component renderer (client) | 6 | `cursor/webview/components.js` | Chart.js, tables, metric cards |
| CLI entry point | 6 | `cli/arcana_cli/main.py` | Typer app, command registration |
| CLI ask command | 6 | `cli/arcana_cli/commands/ask.py` | Streaming query with Rich output |
| CLI admin commands | 6 | `cli/arcana_cli/commands/` | users.py, sources.py, cache.py, audit.py, updater.py |
| **Admin panel** | | | |
| Streamlit app | 9 | `admin/app.py` | Multi-page layout, sidebar navigation |
| Streamlit pages | 9 | `admin/pages/` | 7 pages: overview, users, sources, analytics, audit, review, cache |
| **Evaluation** | — | | |
| Gold standard | — | `backend/arcana/eval/gold_standard.json` | 20 curated query-answer pairs |
| Eval runner | — | `backend/arcana/eval/runner.py` | Retrieval evaluation pipeline |
| **Demo** | — | | |
| Demo seed | — | `backend/arcana/demo/seed.py` | Synthetic data generation |
| Demo questions | — | `backend/arcana/demo/questions.py` | Pool of 50 realistic queries |

### 4.4 Data flow trace

A narrative trace of what happens when a developer asks "How does the authentication middleware work?" — following the request through the entire codebase:

```
1. Cursor webview (cursor/webview/main.js)
   → User types question, presses Enter
   → Sends POST /query via fetch-based SSE

2. FastAPI routing (backend/arcana/routers/query.py)
   → Receives request, extracts API key from X-API-Key header
   → Calls auth middleware (backend/arcana/middleware/auth.py)
   → Validates key, attaches user to request state

3. RBAC scope resolution (backend/arcana/services/permission_service.py)
   → Looks up user's permissions in PostgreSQL
   → Builds ChromaDB where clause + FTS5 filter
   → Returns permitted scopes: ["backend-team", "engineering-docs", "all"]

4. Semantic cache check (backend/arcana/services/cache.py)
   → Embeds the query using Gemini (backend/arcana/services/gemini_client.py)
   → Searches query_cache collection for cosine sim > 0.95
   → Cache miss → continues to retrieval

5. Hybrid search (backend/arcana/services/retrieval/hybrid_search.py)
   → Parallel async execution:
     a. Vector search (backend/arcana/storage/vector_store.py)
        → ChromaDB query with embedding + RBAC where clause → top 20
     b. Keyword search (backend/arcana/storage/keyword_store.py)
        → FTS5 MATCH with RBAC filter → top 20

6. Result fusion (backend/arcana/services/retrieval/fusion.py)
   → Reciprocal rank fusion on both result sets
   → Deduplication, architectural overview boost (+0.15)
   → Cross-reference boost (+0.10)
   → Output: 30 ranked candidates

7. Re-ranking (backend/arcana/services/retrieval/reranker.py)
   → Cross-encoder scores all 30 candidates against the query
   → Output: top 10 re-ranked chunks

8. Context assembly (backend/arcana/services/retrieval/context.py)
   → Orders by source type (overview → docs → code)
   → Fills 6000-token budget greedily
   → Wraps each chunk in [SOURCE N] tags
   → Output: formatted context string

9. Prompt construction (backend/arcana/services/prompt_builder.py)
   → System prompt + role context + assembled sources + question
   → Token budget verification via Gemini count_tokens()

10. LLM generation (backend/arcana/services/gemini_client.py)
    → Sends prompt to Gemini with stream=True
    → Receives streaming response chunks

11. Citation formatting (backend/arcana/services/citation.py)
    → Scans each chunk for [1], [2] references
    → Maps to structured citation objects (file path, lines, Notion URL)
    → Attaches citations to SSE chunk events

12. SSE streaming (backend/arcana/routers/query.py)
    → Sends chunk events to client as they arrive
    → Sends done event with full references list + metadata

13. Cache storage (backend/arcana/services/cache.py)
    → Stores query embedding + full response in query_cache
    → Next identical query will hit cache at step 4

14. Audit logging (backend/arcana/models/audit_log.py)
    → Records query event: user_id, query_text, sources_accessed,
      response_time_ms, cache_hit, chunks_retrieved

15. Cursor rendering (cursor/webview/main.js)
    → Appends streamed text to chat bubble
    → Renders citation badges as clickable pills
    → On click: opens file at line (cursor/src/editor/navigation.ts)
```

---

## 5. Acceptance Criteria

### Demo mode

1. **Isolation:** With `ARCANA_DEMO_MODE=true`, the system uses `data/demo.db` and `data/demo_chromadb/`. With it false, the production databases are used. Switching back and forth preserves both datasets.

2. **Seed completeness:** `make demo-seed` creates 6 users, 3 sources, ~1500 chunks with embeddings, 1000 audit log events, and 20 cache entries. Running seed twice is idempotent.

3. **Demo indicator:** All three surfaces (Streamlit banner, CLI prefix, Cursor dot) show the demo mode indicator when active.

4. **Query works:** A demo query via Cursor or CLI returns a streaming response with citations referencing demo chunk file paths. The answer is contextually relevant to the demo codebase.

5. **RBAC demo:** Querying as `arc_demo_dev_sarah` (backend scope) and `arc_demo_dev_james` (frontend scope) for the same question returns different results — each scoped to their permitted sources.

6. **Analytics populated:** The Streamlit analytics dashboard shows 30 days of data with realistic charts, user activity, and cache performance.

7. **Weekly review populated:** The weekly review page shows 4 weeks of pre-populated summaries with update records and one revert example.

8. **Mock LLM mode:** With `DEMO_MOCK_LLM=true`, queries for seeded questions return pre-computed responses without calling Gemini. Response time < 200ms.

9. **Reset:** `make demo-reset` wipes demo data and re-seeds cleanly.

### Retrieval evaluation

10. **Gold standard:** `backend/arcana/eval/gold_standard.json` contains 20 queries with ideal chunk IDs, categories, and difficulty levels.

11. **Eval run:** `arcana eval run` executes all 20 queries through the retrieval pipeline (no LLM call), computes P@5, P@10, R@10, R@20, MRR, and HR@5, and displays results as a formatted table.

12. **Category breakdown:** Results are broken down by category (semantic, exact_match, multi_source, role_scoped) and by difficulty (easy, medium, hard).

13. **Export:** `arcana eval run --output results.csv` produces a CSV file importable into the thesis as a table.

14. **Ablation:** `arcana eval run --search-mode vector-only` and `--search-mode bm25-only` run the evaluation with one search method disabled, enabling comparison.

15. **Reproducibility:** Running the evaluation twice on the same demo dataset produces identical metrics.

### Architecture documentation

16. **Component map:** `docs/ARCHITECTURE.md` contains a table mapping every architectural component to its file path. Every file listed exists in the repo.

17. **Data flow trace:** The trace in ARCHITECTURE.md follows a query from Cursor input to rendered response, referencing specific files at each step.

18. **README integration:** The main README.md references ARCHITECTURE.md and includes a high-level system diagram.

---

## 6. Estimated Effort

| Task | Estimate | Notes |
|---|---|---|
| Demo mode infrastructure (DB routing, env flag, indicators) | 3–4 hours | Config detection, database path switching |
| Demo seed — users + permissions | 1–2 hours | 6 users, deterministic keys, permission matrix |
| Demo seed — synthetic chunks + embedding | 4–5 hours | Templates, embedding calls, ChromaDB/FTS5 storage |
| Demo seed — audit logs | 2–3 hours | 1000 events, realistic distribution, timestamps |
| Demo seed — update records + weekly reviews (Phase 7) | 2–3 hours | Pre-computed summaries, revert example |
| Demo seed — cache pre-warming | 1–2 hours | 20 cached query-response pairs |
| Demo CLI commands (status, reset) | 1–2 hours | Demo subcommand group |
| Mock LLM mode | 2–3 hours | Pre-computed responses for 50 questions |
| Gold standard dataset creation | 2–3 hours | Manual curation of 20 queries + ideal chunks |
| Eval runner + metrics | 3–4 hours | Pipeline execution, P/R/MRR/HR calculation |
| Eval CLI commands | 1–2 hours | eval run, --category, --search-mode, --output |
| Eval report formatting | 1–2 hours | Rich tables, CSV/JSON export |
| ARCHITECTURE.md component map | 2–3 hours | Mapping every component to files |
| ARCHITECTURE.md data flow trace | 1–2 hours | Step-by-step narrative |
| README.md update | 2–3 hours | Full rewrite with setup, architecture reference, demo instructions |

**Total estimated effort: 28–41 hours (approximately 1–1.5 weeks at thesis pace)**

---

## 7. Known Limitations

| ID | Limitation | Production path |
|---|---|---|
| LT.1 | Demo chunks are synthetic templates, not real code. The AI answers may be less coherent than with a real codebase because the synthetic code lacks internal consistency. | For a more realistic demo, index a real open-source project (e.g., FastAPI itself) instead of synthetic templates. This takes longer to seed but produces more convincing answers. |
| LT.2 | The evaluation gold standard is created by the developer, not by independent annotators. This introduces bias (you know how the system works, so you choose queries it handles well). | Have a colleague or advisor create 10 of the 20 evaluation queries and ideal chunk sets independently. Compare inter-annotator agreement. |
| LT.3 | The evaluation measures retrieval quality but not answer quality. A system with perfect retrieval could still generate poor answers if the prompt engineering is weak. | Add a manual answer quality evaluation: for each of the 20 queries, rate the generated answer on a 1-5 scale for accuracy, completeness, and usefulness. This is subjective but supplements the quantitative retrieval metrics. |

---

*End of document*