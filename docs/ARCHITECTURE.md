# Arcana — Architecture-to-Code Mapping

This document maps every architectural component to its exact file in the codebase, and traces a complete request from Cursor input to rendered response.

---

## Component map

| Architectural component | Phase | File(s) | Description |
|---|---|---|---|
| **Ingestion** | | | |
| GitHub connector | 2 | `backend/arcana/services/github_service.py` | Repo fetch via PyGithub, file tree ingestion |
| GitHub traversal | 2 | `backend/arcana/services/traversal.py` | Recursive tree walk, language detection, file filtering |
| Notion connector | 3 | `backend/arcana/services/notion_service.py`, `notion_ingestion.py` | Block extraction, page hierarchy traversal |
| Notion extractor | 3 | `backend/arcana/services/notion_extractor.py` | Block-level content extraction |
| Code chunker | 2 | `backend/arcana/services/chunker.py` | tree-sitter parsing, function/class boundaries, 80–120 line fallback |
| Notion chunker | 3 | `backend/arcana/services/notion_chunker.py` | Heading-based splitting, breadcrumb headers |
| Embedding pipeline | 2 | `backend/arcana/services/embedder.py` | Batch embedding via Gemini, configurable model |
| DualStore | 5 | `backend/arcana/services/dual_store.py` | Atomic write to ChromaDB + FTS5 in one call |
| **Storage** | | | |
| Vector store (ChromaDB) | 1 | `backend/arcana/vector_store.py` | Collection management, cosine similarity search, singleton client |
| Keyword index (FTS5) | 5 | `backend/arcana/services/fts5_store.py` | SQLite FTS5 table, BM25 keyword search |
| Relational DB (SQLite) | 1 | `backend/arcana/database.py` | SQLAlchemy async engine, session factory, demo path routing |
| DB models | 1, 4, 7 | `backend/arcana/models/user.py`, `data_source.py`, `audit_log.py`, `permissions.py`, `update_record.py`, `weekly_review.py`, `update_proposal.py` | ORM models for all entities |
| **RBAC** | | | |
| Permission service | 4 | `backend/arcana/services/permission_service.py` | Scope resolution, ChromaDB `where` filter + FTS5 filter generation |
| Auth middleware | 4 | `backend/arcana/middleware/auth.py` | API key hashing, validation, role extraction, request state injection |
| **Retrieval pipeline** | | | |
| Hybrid search + RRF | 5 | `backend/arcana/services/retrieval.py` | Parallel vector + BM25, reciprocal rank fusion, deduplication, boosts |
| Re-ranker | 5 | `backend/arcana/services/reranker.py` | Cross-encoder (ms-marco-MiniLM), configurable backend |
| Context assembler | 5 | `backend/arcana/services/context_assembler.py` | Token budget fill, source ordering, `[SOURCE N]` tagging |
| Semantic cache | 5 | `backend/arcana/services/semantic_cache.py` | Query embedding cache, cosine threshold, TTL, scope validation |
| **LLM** | | | |
| Gemini client | 5 | `backend/arcana/services/gemini_client.py` | Streaming generation, `count_tokens`, `generate_content`, response_schema |
| Prompt builder | 5 | `backend/arcana/services/prompt_builder.py` | System prompt construction, role context, source formatting |
| Stream + cite | 5 | `backend/arcana/services/stream_cite.py` | Streaming citation extraction, `[N]` reference mapping, SSE packaging |
| Component renderer | 5, 8 | `backend/arcana/services/component_renderer.py` | Visual query detection, JSON schema validation, chart/table/metric dispatch |
| Query orchestrator | 5 | `backend/arcana/services/query_service.py` | End-to-end pipeline: cache → retrieve → rank → prompt → LLM → cite |
| **Analytics** | | | |
| Analytics service | 8 | `backend/arcana/services/analytics_service.py` | Query frequency, user activity, coverage gaps, cache performance |
| Analytics router | 8 | `backend/arcana/routers/analytics.py` | `GET /admin/analytics/*` endpoints |
| **Auto-updater** | | | |
| GitHub updater | 7 | `backend/arcana/services/github_updater.py` | GitHub API compare, file change classification |
| Notion updater | 7 | `backend/arcana/services/notion_updater.py` | Edit-time comparison, page change detection |
| Update summarizer | 7 | `backend/arcana/services/update_summarizer.py` | LLM summary generation, update record storage |
| Weekly review service | 7 | `backend/arcana/services/weekly_review_service.py` | Friday narrative generation, alert system |
| Auto-updater scheduler | 7 | `backend/arcana/services/auto_updater.py` | APScheduler integration, interval control |
| Audit service | 1 | `backend/arcana/services/audit_service.py` | Event logging, query result storage |
| **API layer** | | | |
| App factory | 1 | `backend/arcana/main.py` | FastAPI app creation, middleware registration, router mounting |
| Settings | 1 | `backend/arcana/config.py` | Pydantic settings, env var loading, demo DB path routing |
| Health endpoints | 1 | `backend/arcana/routers/health.py` | `GET /health`, `/health/db`, `/health/ready` (includes `demo_mode` flag) |
| Admin endpoints | 4 | `backend/arcana/routers/admin.py` | User CRUD, source management |
| Permissions endpoints | 4 | `backend/arcana/routers/permissions.py` | Permission grant/revoke |
| Audit log endpoints | 1 | `backend/arcana/routers/audit_logs.py` | Audit log query |
| Query endpoint | 5 | `backend/arcana/routers/query.py` | `POST /query/` SSE streaming |
| Updater endpoints | 7 | `backend/arcana/routers/updater.py` | Review, revert, history, manual trigger |
| GitHub endpoints | 2 | `backend/arcana/routers/github.py` | Source registration, sync trigger |
| Notion endpoints | 3 | `backend/arcana/routers/notion.py` | Source registration, sync trigger |
| **Client surfaces** | | | |
| Cursor extension entry | 6 | `cursor/src/extension.ts` | Activation, VS Code command registration |
| Sidebar provider | 6 | `cursor/src/sidebar/SidebarProvider.ts` | Webview lifecycle, health ping, review badge, demo badge |
| Backend API client (TS) | 6 | `cursor/src/api/arcanaClient.ts` | SSE streaming, health ping, updater + analytics API calls |
| Active file tracker | 6 | `cursor/src/context/activeFile.ts` | VS Code editor event subscription, file path propagation |
| Editor navigation | 6 | `cursor/src/editor/navigation.ts` | `openCodeCitation()`, line jumping, external URL opening |
| Webview chat + dashboard | 6, 8 | `cursor/webview/main.js` | SSE streaming, markdown rendering, chart components, citation clicks |
| Webview styles | 6 | `cursor/webview/styles.css` | Sidebar UI, status dot, review badge, demo badge |
| CLI entry point | 6 | `cli/arcana_cli/main.py` | Typer app, command registration, demo mode prefix, review banner |
| CLI ask command | 6 | `cli/arcana_cli/commands/ask.py` | Streaming query with Rich Live rendering, `--api-key` override |
| CLI demo command | — | `cli/arcana_cli/commands/demo.py` | `arcana demo status` — health check, stats, key display |
| CLI eval command | — | `cli/arcana_cli/commands/eval.py` | `arcana eval run` — evaluation runner + report |
| CLI admin commands | 6 | `cli/arcana_cli/commands/` | `users.py`, `sources.py`, `cache.py`, `audit.py`, `updater.py`, `dashboard.py` |
| **Admin panel** | | | |
| Streamlit app | 9 | `admin/app.py` | Multi-page layout, auth redirect |
| Streamlit pages | 9 | `admin/pages/` | 7 pages: overview, users, sources, analytics, audit, weekly review, cache |
| Admin auth | 9 | `admin/auth.py` | API key login, session management, demo mode banner |
| Admin API client | 9 | `admin/api_client.py` | Shared HTTP client wrapping the FastAPI backend |
| **Demo mode** | | | |
| Demo module | — | `backend/arcana/demo/__init__.py` | `is_demo_mode()`, `is_mock_llm()`, `DEMO_BANNER` constant |
| Demo seed orchestrator | — | `backend/arcana/demo/seed.py` | Full seed pipeline: sources → users → permissions → audit → updates → chunks → cache |
| Demo users | — | `backend/arcana/demo/users.py` | 6 demo users, deterministic API keys, permission matrix |
| Demo chunks | — | `backend/arcana/demo/chunks.py` | ~160 synthetic code + doc chunks across 3 sources |
| Demo audit | — | `backend/arcana/demo/audit.py` | 1 000 synthetic query events over 30 days |
| Demo updates | — | `backend/arcana/demo/updates.py` | 4 weeks of update records + weekly reviews |
| Demo cache | — | `backend/arcana/demo/cache.py` | 20 pre-warmed cache entries |
| Demo questions | — | `backend/arcana/demo/questions.py` | Pool of 50 realistic developer queries |
| Demo responses | — | `backend/arcana/demo/responses.py` | Pre-computed responses for `DEMO_MOCK_LLM` mode |
| **Retrieval evaluation** | | | |
| Gold standard | — | `backend/arcana/eval/gold_standard.json` | 20 curated queries with ideal chunk IDs, categories, and difficulty |
| Eval runner | — | `backend/arcana/eval/runner.py` | Retrieval pipeline execution, metric computation per query |
| Eval metrics | — | `backend/arcana/eval/metrics.py` | Precision@k, Recall@k, MRR, Hit Rate@k — pure functions |
| Eval report | — | `backend/arcana/eval/report.py` | Rich terminal tables, JSON/CSV export |

---

## Data flow trace

What happens when a developer asks **"How does the authentication middleware work?"** in the Cursor sidebar:

```
1. Cursor webview  (cursor/webview/main.js)
   → User types question and presses Enter
   → Initiates fetch-based SSE stream to POST /query/

2. FastAPI routing  (backend/arcana/routers/query.py)
   → Receives POST with X-API-Key header
   → Calls auth middleware (backend/arcana/middleware/auth.py)
   → Hashes key, looks up user in DB, attaches to request state

3. RBAC scope resolution  (backend/arcana/services/permission_service.py)
   → Looks up the user's granted sources in SQLite
   → Builds ChromaDB `where` clause + FTS5 filter string
   → Permitted scopes: ["backend-team", "engineering-docs"]

4. Semantic cache check  (backend/arcana/services/semantic_cache.py)
   → Embeds the query via Gemini  (backend/arcana/services/gemini_client.py)
   → Searches query_cache collection, threshold 0.95 cosine
   → Cache miss → continues to retrieval

5. Hybrid search  (backend/arcana/services/retrieval.py)
   → Parallel async execution:
     a. Vector search  (backend/arcana/vector_store.py)
        → ChromaDB query with embedding + RBAC where clause → top 20
     b. Keyword search  (backend/arcana/services/fts5_store.py)
        → FTS5 MATCH with RBAC filter → top 20

6. Result fusion  (backend/arcana/services/retrieval.py)
   → Reciprocal rank fusion across both result sets
   → Deduplication, architecture-overview boost (+0.15), cross-ref boost (+0.10)
   → Output: 30 ranked candidates

7. Re-ranking  (backend/arcana/services/reranker.py)
   → Cross-encoder (ms-marco-MiniLM-L-6-v2) scores each candidate vs. query
   → Output: top 10 re-ranked chunks

8. Context assembly  (backend/arcana/services/context_assembler.py)
   → Orders by source type: overviews → docs → code
   → Fills 6 000-token budget greedily with [SOURCE N] tags
   → Returns formatted context string

9. Prompt construction  (backend/arcana/services/prompt_builder.py)
   → Combines system prompt + role context + assembled sources + question
   → Verifies token budget via Gemini count_tokens()

10. LLM generation  (backend/arcana/services/gemini_client.py)
    → Streams response from Gemini with stream=True

11. Citation formatting  (backend/arcana/services/stream_cite.py)
    → Scans each streamed chunk for [N] references
    → Maps references to structured citation objects (file path, line range, URL)
    → Attaches citations to SSE chunk events

12. SSE streaming  (backend/arcana/routers/query.py)
    → Sends `chunk` events as they arrive from Gemini
    → Sends final `done` event with the full references list

13. Cache storage  (backend/arcana/services/semantic_cache.py)
    → Stores query embedding + full response in query_cache
    → Identical future queries will hit the cache at step 4

14. Audit logging  (backend/arcana/services/audit_service.py)
    → Records query event: user_id, query_text, sources_accessed,
      response_time_ms, cache_hit, chunks_retrieved

15. Cursor rendering  (cursor/webview/main.js)
    → Appends streamed markdown text to chat bubble via marked.js
    → Renders citation pills as clickable badges
    → On click: calls openCodeCitation() (cursor/src/editor/navigation.ts)
      which opens the file at the specified line in the editor
```

---

## Demo mode routing

When `ARCANA_DEMO_MODE=true`, database path routing happens at settings load time:

```
Settings.effective_database_url  →  data/demo.db        (instead of data/arcana.db)
Settings.effective_chromadb_path →  data/demo_chromadb/ (instead of data/chromadb/)

backend/arcana/database.py       uses effective_database_url   for SQLAlchemy engine
backend/arcana/vector_store.py   uses effective_chromadb_path  for ChromaDB client
backend/arcana/services/dual_store.py  uses effective_database_url  for FTS5 path
```

The production databases are completely untouched when demo mode is active.

---

## Key design decisions

| Decision | File | Rationale |
|---|---|---|
| All business logic in `services/` | `backend/arcana/services/` | Thin routers, testable services, no logic in ORM models |
| Singleton ChromaDB client | `backend/arcana/vector_store.py` | Avoid repeated disk I/O on cold starts; `reset_client()` allows test/demo switching |
| FTS5 inside the SQLite file | `backend/arcana/services/fts5_store.py` | No separate process, atomic DB migration, zero infra overhead |
| SSE for query streaming | `backend/arcana/routers/query.py` | Native browser support, no WebSocket upgrade, works through proxies |
| RBAC enforced at retrieval time | `backend/arcana/services/permission_service.py` | Users can never receive chunks they don't have access to, even via cache |
| Demo path routing in Settings | `backend/arcana/config.py` | Single env var controls all path routing; no if/else scattered through the code |
| Deterministic demo API keys | `backend/arcana/demo/users.py` | Presenter can reference keys in slides without runtime lookup |

See [docs/LIMITATIONS.md](LIMITATIONS.md) for 50 documented tradeoffs with production paths.
