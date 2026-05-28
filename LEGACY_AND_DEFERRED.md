# Arcana — Legacy, Removed, and Deferred Features

This document catalogues everything that was either (a) fully built and later replaced, (b) fully built in the wider project but absent from this simplified repository, or (c) explicitly planned but never implemented. It serves as a record of the product's history and a map of the road not yet taken.

---

## Table of Contents

1. [The Next.js Prototype (Abandoned)](#1-the-nextjs-prototype-abandoned)
2. [Full Monorepo Features — Built but Not in This Repo](#2-full-monorepo-features--built-but-not-in-this-repo)
   - 2.1 Python CLI
   - 2.2 Cursor IDE Extension
   - 2.3 Streamlit Admin Panel
   - 2.4 Analytics Data Layer
   - 2.5 Auto-Updater + Weekly Review
   - 2.6 Demo Mode + Retrieval Evaluation Harness
3. [Superseded Internals — Built Then Replaced Within This Repo](#3-superseded-internals--built-then-replaced-within-this-repo)
4. [RBAC: Designed, Partially Built, Not Enforced](#4-rbac-designed-partially-built-not-enforced)
5. [Planned but Never Implemented](#5-planned-but-never-implemented)
6. [Design Decisions Considered and Rejected](#6-design-decisions-considered-and-rejected)

---

## 1. The Next.js Prototype (Abandoned)

**Branch:** `v0-project-29mar` (archived, reference only)

The project began as a Next.js full-stack application. The original architecture placed both the web UI and the API inside a single Next.js app, using API routes for the backend. This prototype was built before session 1 and formed the initial concept baseline.

**Why it was abandoned:** In session 1 (March 29, 2026), the decision was made to rebuild from scratch in Python/FastAPI. The reasoning:

- The primary consumers of Arcana's data are not browsers — they are a CLI, a Cursor IDE extension, and an Electron overlay. A Python backend is more natural for this access pattern than a JavaScript/TypeScript monolith.
- The ML/embedding stack (ChromaDB, sentence-transformers, tree-sitter) has significantly better Python integration than Node.js equivalents.
- A FastAPI-only backend is a clean separation: the API is the product, and any UI is a thin layer on top of it.

**What it had:** Basic query interface, a web form for asking questions, an initial routing structure for GitHub ingestion. No ingestion pipeline, no vector store, no streaming.

**What replaced it:** The entire current system — FastAPI backend, ChromaDB, Gemini API integration, and multiple frontend surfaces.

---

## 2. Full Monorepo Features — Built but Not in This Repo

The full development history of Arcana produced a larger monorepo with directories `backend/`, `cli/`, `cursor/`, `admin/`, `electron/`, and `ui/`. This repository (`ig-arcana-simple`) retains only `backend/`, `electron/`, and `ui/`. The following features were fully implemented, tested, and merged to main in the full version but are not present here.

---

### 2.1 Python CLI (`cli/`)

**Implemented in:** Session 6 (Phase 6, April 5, 2026)  
**Tests:** 28 passing

A full command-line interface built with [Typer](https://typer.tiangolo.com/) and [Rich](https://rich.readthedocs.io/). It communicated with the FastAPI backend over HTTP and streamed responses in real time.

**Commands implemented:**

| Command | Description |
|---------|-------------|
| `arcana ask "<question>"` | Stream a query answer with Rich Markdown + source citations as clickable OSC 8 hyperlinks |
| `arcana config set-key <key>` | Store API key in `~/.arcana/config.toml` (0600 permissions) |
| `arcana config set-server <url>` | Configure backend URL |
| `arcana config show` | Show config with masked API key |
| `arcana config test` | Ping backend health endpoint |
| `arcana users list/create/update/deactivate/rotate-key` | Full user lifecycle management |
| `arcana sources list/status/sync` | Data source management with auto-detection of GitHub vs. Notion URL |
| `arcana sources sensitive` | Toggle sensitive flag on a source |
| `arcana cache stats/flush/invalidate` | Cache management with `--yes` confirmation gate |
| `arcana audit list` | Audit log browsing with `--user`, `--type`, `--from`, `--to` filters |
| `arcana reindex <id>\|--all` | Trigger re-ingestion of one or all sources |
| `arcana updater run/review-week/revert/history` | Auto-updater CLI controls (Phase 7) |
| `arcana dashboard` | Real-time analytics dashboard with `--metric`, `--from`, `--to`, `--raw` flags |
| `arcana demo status` | Show demo mode status |
| `arcana eval run` | Run retrieval evaluation benchmark |

**Visual rendering system:**  
The CLI included a component renderer that detected JSON component responses from the backend (chart, table, metric_card, timeline, progress) and rendered them using Rich tables, panels, and [plotext](https://github.com/piccolomo/plotext) text-based charts. Citations were rendered as OSC 8 clickable hyperlinks in terminals that support them (iTerm2, kitty, Ghostty).

**Config storage:** `~/.arcana/config.toml` with `api_key` (masked in display), `server_url`, and session state.

---

### 2.2 Cursor IDE Extension (`cursor/`)

**Implemented in:** Session 6 (Phase 6) + Session 9 (Phase 7.5)  
**Tests:** 52 passing (Jest)  
**Language:** TypeScript

A VS Code/Cursor extension distributed as a `.vsix` sideload (not marketplace-published). It added an Arcana sidebar panel to the editor with a full chat UI.

**Core components:**

| File | Responsibility |
|------|----------------|
| `src/extension.ts` | Extension activation, command registration (`arcana.ask`, `arcana.askAboutSelection`, `arcana.clearChat`) |
| `src/sidebar/SidebarProvider.ts` | `WebviewViewProvider` with nonce-based CSP, 60-second health ping, message routing to/from webview |
| `src/api/arcanaClient.ts` | `streamQuery()` fetch-based SSE generator, `parseSSEEvent()`, `pingHealth()`, `fetchDashboard()` |
| `src/editor/navigation.ts` | `openCodeCitation()` — jumps to line with 1.5s highlight; GitHub fallback URL; workspace path resolution |
| `src/context/activeFile.ts` | `onDidChangeActiveTextEditor` — sends `context_file` with every query so the model knows what the developer is looking at |
| `webview/main.js` | Full chat UI, SSE streaming, marked.js markdown, Prism.js syntax highlighting, Chart.js charts, sortable tables, citation badges, references panel |
| `webview/styles.css` | VS Code theme variable integration, chat bubbles, component styles, dashboard styles |
| `build.js` | esbuild bundle + copies webview libs from node_modules |

**Phase 7.5 additions (session 9):**
- **Review badge** — polls `GET /admin/updater/review/pending`; shows an amber dot on the Arcana icon when a weekly review is waiting for acknowledgment
- **Weekly summary card** — displays the `WeeklyReviewOut` payload with narrative text and high-risk change highlights
- **Revert inline form** — calls `POST /admin/updater/revert/{id}` with a mandatory correction text input; shows confirmation and refreshes the review card

**Dashboard screen (Phase 8):**
- A full analytics dashboard screen accessible via a `⬡` button in the sidebar
- Collapsible sections per metric (query frequency, coverage gaps, popular topics, user activity, cache performance)
- Date range selector and auto-refresh toggle

**Active file context:** The extension tracked which file was open in the editor and attached it as context to every query, allowing the backend to give more relevant answers when a developer was looking at a specific file.

---

### 2.3 Streamlit Admin Panel (`admin/`)

**Implemented in:** Session 12 (Phase 9, April 11, 2026)  
**Tests:** 29 passing  
**Port:** `127.0.0.1:8501` (bound to localhost only, not exposed externally)

A 7-page Streamlit admin panel consuming the FastAPI API surface. Ran as a separate service in `docker-compose.yml`.

**Pages:**

| Page | Contents |
|------|----------|
| **Overview** | System health cards (backend, ChromaDB, Ollama), key metrics summary, recent alerts, quick action buttons, 60-second auto-refresh |
| **Users** | Full user CRUD: create, edit role/team, deactivate/reactivate, view permissions per user, API key rotation |
| **Sources** | Data source status cards, re-sync triggers, sensitive flag toggle |
| **Analytics** | 5 Plotly charts: query frequency over time, coverage gap heatmap, popular topics bar chart, user activity leaderboard, cache hit/miss ratio |
| **Audit Log** | Filterable + paginated audit log with columns for event type, user, timestamp, details |
| **Weekly Review** | Narrative display of LLM-generated weekly summary, high-risk change flags, revert flow with correction form, acknowledgment button |
| **Cache** | Cache hit rate, size metrics, flush button (with confirmation), invalidate-by-scope form |

**Authentication:** Auto-login via `ARCANA_ADMIN_KEY` env var; fallback to manual API key input form. Session state stored in Streamlit `session_state`.

**Supporting modules:**
- `api_client.py` — shared HTTP client with full error handling for all 6xx/5xx cases
- `auth.py` — login flow, session management, role detection
- `utils.py` — `format_relative_time()`, `validate_correction()` helpers

---

### 2.4 Analytics Data Layer

**Implemented in:** Session 10 (Phase 8, April 9, 2026)  
**Tests:** 25 backend analytics tests + reflected in Cursor and CLI surfaces

A real SQL/ChromaDB analytics engine replacing the placeholder that returned hallucinated numbers from the LLM.

**Five analytics functions (`analytics_service.py`):**

| Function | Data source | What it computes |
|----------|-------------|-----------------|
| `get_query_frequency(from, to)` | `audit_logs` | Queries per day, bucketed by time range |
| `get_coverage_gaps(days)` | `audit_logs` join `data_sources` | Sources that are indexed but never queried (potential blind spots) |
| `get_popular_topics(limit)` | `audit_logs` | Most-queried data sources by query count |
| `get_user_activity(from, to)` | `audit_logs` | Per-user query counts and last-active timestamps |
| `get_cache_performance(days)` | `audit_logs` + ChromaDB | Cache hit rate, total cache entries, avg response delta (cached vs. uncached) |

**Six REST endpoints** under `/admin/analytics/` requiring `senior_dev+` role:
- `GET /admin/analytics/dashboard` — all five metrics assembled into a single response
- `GET /admin/analytics/query-frequency`
- `GET /admin/analytics/coverage-gaps`
- `GET /admin/analytics/popular-topics`
- `GET /admin/analytics/user-activity`
- `GET /admin/analytics/cache-performance`

**Analytics context injection:** A module-level TTL cache (`analytics_cache_ttl_minutes=60`) injected real aggregate numbers into Gemini's visual query prompts, replacing placeholder values.

**Gemini structured output upgrade:** Visual queries (`response_schema` + `application/json` mime type) produced guaranteed-valid JSON component responses, replacing a regex post-processing fallback.

---

### 2.5 Auto-Updater + Weekly Review (`services/auto_updater.py` and related)

**Implemented in:** Session 8 (Phase 7, April 7, 2026) + Session 9 (Phase 7.5)  
**Tests:** 52 Phase 7 tests  
**PR:** #5 and #7, both merged to main

An automated change-detection and weekly review system that kept the knowledge base current without manual re-ingestion.

**Core change detection:**
- **GitHub:** Used the GitHub API compare endpoint (`GET /repos/{owner}/{repo}/compare/{base}...{head}`) to diff the last indexed commit against the current HEAD. Only modified, added, or deleted files were re-processed. No persistent local clones.
- **Notion:** Compared `last_edited_time` on every page against `last_synced_at` in the database. Re-processed changed pages only.
- **Significance classification:** Changes were classified as `critical`, `significant`, or `minor` based on file type and size of diff, to prioritize weekly review highlights.

**Weekly review system:**
- Every Friday, APScheduler fired `generate_weekly_review()` which assembled all changes from the past 7 days and sent them to Gemini to produce a narrative summary.
- The summary identified high-risk changes, called out architectural modifications, and recommended which changes the admin should manually verify.
- The admin could **acknowledge** (mark as reviewed) or **revert** any individual change.

**Revert flow:**
- `POST /admin/updater/revert/{update_id}` required a mandatory correction text (minimum length enforced).
- Reverting re-embedded the pre-change chunk state and stored the admin's correction as a new chunk with a `+0.15` retrieval boost, ensuring corrected content surfaces first in future queries.
- `DELETE /admin/updater/corrections/{chunk_id}` allowed removing a correction if it was no longer accurate.

**APScheduler jobs (unified scheduler):**
- `daily_auto_update` — runs every 24 hours (configurable via `UPDATER_RUN_HOUR`)
- `weekly_review` — runs on the configurable review day (default: Friday)

**New models:**
- `UpdateRecord` — stores each detected change: `source_id`, `change_type` (added/modified/deleted), `diff_summary`, `affected_chunks`, `confidence`, `before_content`, `after_content`
- `WeeklyReview` — stores the generated narrative, status (pending/acknowledged), and acknowledgment timestamp

**10 API endpoints** under `/admin/updater/*`:
`POST /run`, `POST /run/{source_id}`, `GET /history`, `GET /history/{record_id}`, `GET /review/pending`, `GET /review`, `POST /review/{id}/acknowledge`, `POST /revert/{update_id}`, `DELETE /corrections/{id}`, `GET /stats`, `GET /reverts`

---

### 2.6 Demo Mode + Retrieval Evaluation Harness

**Implemented in:** Session 13 (Phase 10, April 11, 2026)  
**Tests:** 34 demo isolation tests + 34 eval tests = 68 new tests  
**PR:** #10, merged to main

**Demo mode** (`ARCANA_DEMO_MODE=true`):
- Routed all database and ChromaDB operations to isolated `data/demo.db` and `data/demo_chromadb/` paths, completely separate from the real knowledge base.
- A seed script populated the demo environment with: 6 synthetic users (deterministic `arc_demo_*` API keys), 3 data sources, ~160 synthetic code and documentation chunks, 1,000 audit events distributed across 4 weeks, 4 weeks of update records + weekly reviews, and 20 pre-warmed semantic cache entries.
- All surfaces showed a demo indicator: Streamlit showed `show_demo_banner()` on every page, the CLI prefixed all output with `[DEMO]`, and the Cursor extension showed an amber `DEMO` badge in the sidebar header.
- `arcana demo status` and `arcana demo reset` CLI commands. `make demo-seed` and `make demo-reset` Makefile targets.

**Retrieval evaluation harness** (`arcana eval run`):
- A 20-query gold standard (`gold_standard.json`) covering 4 categories (architecture, implementation, debugging, onboarding) at 3 difficulty levels (easy, medium, hard).
- Metrics computed: **P@5**, **P@10**, **R@10**, **R@20**, **MRR**, **HR@5** (Hit Rate at 5).
- Ablation modes: `hybrid` (vector + BM25), `vector-only`, `bm25-only` — for comparing retrieval strategies.
- Output: console table via Rich, plus optional CSV/JSON export.
- Purpose: thesis presentation evidence for retrieval quality claims.

**Architecture documentation (`docs/ARCHITECTURE.md`):** A 15-step data flow trace from user question to streamed response, with a component-to-file mapping table.

---

## 3. Superseded Internals — Built Then Replaced Within This Repo

These are features or components that were implemented, shipped, and then superseded by a better version — all within this repository.

### 3.1 `google-generativeai` → `google-genai`

**Replaced in:** Session 7 (PR #4, April 5, 2026)

The original backend used `google-generativeai>=0.8.0` (deprecated). After Google deprecated this SDK in favor of `google-genai>=1.0.0`, the entire Gemini integration was rewritten:

- `gemini_client.py`: `_get_model()` singleton → `_get_client()` using `genai.Client(api_key=...)`. Streaming via `client.models.generate_content_stream()`.
- `prompt_builder.py`: Token counting via `client.models.count_tokens()`.
- `pyproject.toml`: Dependency updated.

All 198 existing tests passed after the migration without modification.

---

### 3.2 `all-mpnet-base-v2` → `BAAI/bge-base-en-v1.5`

**Replaced in:** Session 17 (PR #15, April 15, 2026)

The original offline embedding model was `sentence-transformers/all-mpnet-base-v2` (768-dim, symmetric retrieval). It was replaced by `BAAI/bge-base-en-v1.5` (768-dim, asymmetric retrieval) for two reasons:

1. **Asymmetric retrieval:** BGE supports a query instruction prefix (`"Represent this sentence for searching relevant passages: "`) that projects queries into a "searching" sub-space, significantly improving retrieval precision. `all-mpnet-base-v2` does not support asymmetric retrieval.
2. **Documented outperformance on code retrieval benchmarks.**

The BGE prefix is prepended only at query time — documents stored in ChromaDB are embedded without the prefix, as per BGE's asymmetric protocol.

---

### 3.3 Shared ChromaDB collections → Separate per-embedding-space collections

**Fixed in:** Session 17 (PR #15, April 15, 2026)

The initial Phase 12 implementation used the same `code_chunks` and `doc_chunks` collections for both Gemini embeddings (3072-dim) and BGE embeddings (768-dim). This was silently broken: ChromaDB enforces a single dimension per collection and rejects queries with a mismatched dimension at runtime.

The failure mode was invisible at first glance — no crash, just zero results. The actual error appeared in the log: `Collection expecting embedding with dimension of 3072, got 768`. Every offline query fell through to the KB-miss fallback.

**Fix:** Two new collections — `code_chunks_local` (BGE, 768-dim) and `doc_chunks_local` (BGE, 768-dim) — were added alongside the existing Gemini collections. The query routing was updated to use the correct pair per mode.

**Consequence:** Chunks ingested in one mode are not queryable in the other mode without re-ingestion.

---

### 3.4 Fast/Think model selector → Single `qwen2.5:3b`

**Removed in:** Session 16 (April 15, 2026)

Phase 12 was originally designed with two offline model tiers:
- **Fast mode:** `qwen3.5` (~3B parameters) — faster responses
- **Think mode:** `minimax-m2.7` — deeper reasoning, slower

**Why it was removed:**
1. Neither `qwen3.5` nor `minimax-m2.7` were available in the Ollama registry at implementation time. Both were replaced with `qwen2.5:3b` (Fast) and `phi4` (Think).
2. Think mode (`phi4`, 14B parameters, ~9.1 GB) requests were not completing reliably on the development hardware (Intel i5 MacBook).
3. The UI complexity (Fast/Think pill buttons on both Electron and browser surfaces) was not justified for the reliability improvement it provided.

**What was removed:**
- Fast/Think pill button UI components from both `electron/index.html` and `ui/index.html`
- `offline_model` field from `settings.json` and the settings store/API
- Model-selection logic from `query_service.py`

**What replaced it:** Single model `qwen2.5:3b`, always. Model name configured via `OLLAMA_FAST_MODEL` env var.

---

### 3.5 Ollama `keep_alive=0` → `keep_alive=300`

**Changed in:** Session 17 (PR #16, April 15, 2026)

The initial Ollama client configuration unloaded the model immediately after each response (`keep_alive=0`). This was documented as an accepted tradeoff ("cold-start tradeoff accepted for Intel i5 hardware").

After profiling, the cold-start cost (30–60 seconds to reload `qwen2.5:3b` from disk) was unacceptable for realistic usage patterns — developers ask follow-up questions, not isolated single queries. `keep_alive=300` keeps the model in RAM for 5 minutes after the last query, eliminating cold-start latency for back-to-back questions.

---

### 3.6 Oversized Ollama context window → Correctly sized

**Changed in:** Session 17 (PR #16, April 15, 2026)

The initial Ollama parameters were:
```
num_ctx: 8192     # context window
num_predict: 2048  # max output tokens
```

These were reduced to:
```
num_ctx: 4096     # matches actual context budget (3500 tokens assembly + overhead)
num_predict: 512   # sufficient for typical developer Q&A answers
```

The oversized values wasted GPU/CPU memory and sometimes caused Ollama to refuse requests on resource-constrained hardware. The correct values match the actual token budget used by the context assembler (3500 tokens for offline mode).

---

### 3.7 Elapsed timer → Countdown timer

**Changed in:** Session 17 (PR #18, April 15, 2026)

The original UI showed an elapsed timer ("Thinking… 4s", "Thinking… 5s…") that counted upward from zero. This was replaced by a countdown timer that counts down from a mode-specific budget:
- Online mode: 15 seconds
- Offline mode: 45 seconds

**Why:** A countdown provides more useful information to the user ("~12s remaining" sets expectations) than an elapsed timer ("been waiting 8s" creates anxiety). On first token received, both modes transition to "Streaming…" regardless of countdown state. A 60-second hard abort via `AbortController` remains as the safety net.

---

### 3.8 GitHub/Notion ingestion available in offline mode → 503 guard

**Added in:** Session 16 (Phase 12, April 15, 2026)

Before the online/offline mode concept was introduced, all three ingest endpoints (`/ingest/github`, `/ingest/notion`, `/ingest/local`) were always available. When offline mode was added, an explicit guard was added: `/ingest/github` and `/ingest/notion` return HTTP 503 in offline mode with the message "GitHub/Notion ingestion requires online mode." Only `/ingest/local` remains unconditionally available.

---

## 4. RBAC: Designed, Partially Built, Not Enforced

**Phase 4 was fully designed and its database schema was implemented.** The users, permissions, and audit_logs tables exist and are populated by the Alembic migrations. However, the enforcement layer — the pre-retrieval permission filter that gates which chunks a user can see — is **not active in the current query pipeline**.

**What was built:**
- Full user/permission database schema (users table with role, permissions table with access_level, audit_logs with event_type enum)
- API key generation, hashing, and rotation flow
- Admin endpoints for user and permission CRUD

**What was designed but not enforced in the current `query_service.py`:**
- `PermissionFilterService` — the service that resolves a user's permitted `access_scope` values and constructs a ChromaDB `where` clause
- Pre-retrieval filtering (the `where` parameter on ChromaDB `collection.query()`) — currently absent; all chunks are returned regardless of user identity
- Endpoint-level role enforcement on `/query/` and `/ingest/` — currently there is no `X-API-Key` header check on these public endpoints

**Why it was deferred in the simplified version:** Arcana is intended for internal team deployment behind a network boundary. For a single-team single-tenant deployment, the operational overhead of managing API keys and permissions for all developers was not justified for the thesis scope. The schema and the PRD (Phase 4) exist as a full production-ready design for when enforcement is needed.

**The full RBAC design** (roles: viewer, dev, senior_dev, admin; permission matrix; sensitive content tagging; FTS5 filter builder; audit event types) is documented in `docs/prds/phase4/PRD_Phase4_RBAC_+_Permission_System.md`.

---

## 5. Planned but Never Implemented

These are items that were explicitly discussed, planned, or backlogged during development but never made it into any version of the code.

### 5.1 Watch mode for local files

**From:** Session 17 "Next Session" backlog

Automatically re-ingest local files when they change on disk, using Python's `watchdog` library to monitor configured directories. The user would add a path to a watch list; Arcana would detect file modifications and call the local ingest pipeline in the background. Currently, local re-ingestion requires an explicit call to `POST /ingest/local`.

---

### 5.2 Conversation history panel

**From:** Session 17 "Next Session" backlog

A sidebar panel in both the browser UI and Electron overlay showing prior conversation exchanges, allowing developers to scroll back through the session history. Currently, the conversation `history` array is only maintained in memory for the current page load; there is no persistence or UI for reviewing past Q&A pairs.

---

### 5.3 Source filtering UI

**From:** Session 17 "Next Session" backlog + RBAC design

UI controls allowing the user to filter which data sources a query searches across (e.g., "only search the backend repo, not Notion"). Currently, all queries search all indexed chunks regardless of source.

---

### 5.4 GitHub webhooks for real-time change detection

**From:** Limitation L7.1 (LIMITATIONS.md)

The auto-updater uses daily polling. GitHub webhooks would enable near-instant knowledge base updates when code is pushed. Requires a publicly accessible backend endpoint (not the case for a localhost thesis deployment) and webhook signature validation.

---

### 5.5 GitLab and Bitbucket support

**From:** Limitation L2.4 (LIMITATIONS.md)

Only GitHub is supported as a code ingestion source. The chunking and embedding pipeline after cloning is source-agnostic; only the connector that clones repos and fetches metadata would need to be implemented per platform.

---

### 5.6 Per-file and per-directory permissions

**From:** Limitation L4.1 (LIMITATIONS.md)

Current RBAC design grants access at the data source level (whole repo or whole Notion workspace). Finer-grained permissions — "access `src/auth/` but not `src/payments/`" within the same repo — were designed but not implemented.

---

### 5.7 Permission sync from GitHub/Notion

**From:** Limitation L4.2 (LIMITATIONS.md)

When a developer's access is revoked in GitHub or Notion, Arcana doesn't detect it automatically. A periodic sync job would check upstream permissions and revoke Arcana access to match.

---

### 5.8 OAuth/SSO authentication

**From:** Limitation L4.3 (LIMITATIONS.md)

API key authentication only. No "sign in with GitHub/Google," no OAuth2 flow, no OIDC, no automatic key expiry. Planned for post-thesis.

---

### 5.9 Multi-turn conversation memory (server-side)

**From:** Limitation L5.1 (LIMITATIONS.md)

The current implementation passes a `history` array from the client to the server, but this history lives only in the client's JavaScript memory and is lost on page reload. Server-side session storage (a `conversations` table with session management) would persist history across reloads and allow resuming conversations.

---

### 5.10 FTS5 hybrid search (BM25 + vector)

**From:** Phase 5 PRD + Limitation L5.2 (LIMITATIONS.md)

Phase 5 designed a dual-store retrieval system combining ChromaDB vector search with SQLite FTS5 BM25 keyword search, fused via Reciprocal Rank Fusion (RRF). The RBAC filter builder (`PermissionFilterService`) even pre-generated FTS5 SQL WHERE clauses in anticipation of this. In the current codebase, only vector search is active; the FTS5 index and BM25 path were never wired into the query pipeline in this simplified version.

---

### 5.11 Cross-encoder re-ranker

**From:** Phase 5 PRD + Limitation L5.3 (LIMITATIONS.md); `cohere>=5.0` is in `pyproject.toml`

A re-ranking pass using either a local cross-encoder model (`cross-encoder/ms-marco-MiniLM-L-6-v2`) or the Cohere Rerank API was designed to improve precision on the top-k retrieved chunks. The `cohere` package is present in `pyproject.toml` but the re-ranking call was never added to the retrieval pipeline in this version.

---

### 5.12 Semantic query cache (active serving)

**From:** Phase 5 design

The `query_cache` ChromaDB collection (`vector_store.py :: get_cache_collection()`) was designed to store query embeddings + full response text, serving cached responses for semantically similar repeated queries (cosine threshold: ~0.95). The collection is created on startup but the cache lookup and cache write logic was not implemented in the simplified version's `query_service.py`.

---

### 5.13 CodeLens provider and hover hints for Cursor extension

**From:** Limitation L6.3 (LIMITATIONS.md)

Inline annotations above function/class definitions ("Arcana: explain") and hover-on-symbol context tooltips were planned as passive intelligence features. Neither was implemented; the extension only responds to explicit user queries in the sidebar.

---

### 5.14 Auto-update for CLI and extension

**From:** Limitation L6.5 (LIMITATIONS.md)

No auto-update mechanism. Developers must manually reinstall the extension `.vsix` and re-run `pip install` for the CLI when a new version is released. Planned: an `arcana version --check` command and VS Code marketplace publication for auto-updates.

---

### 5.15 Personal developer analytics

**From:** Limitation L8.4 (LIMITATIONS.md)

All analytics endpoints are admin/senior_dev-scoped. Individual developers cannot see their own usage patterns: how many questions they've asked, which topics they've explored, or an "onboarding coverage" metric showing what percentage of key knowledge areas they've queried. A `GET /analytics/me` endpoint was planned but not implemented.

---

### 5.16 Dashboard export and scheduled reports

**From:** Limitation L8.3 (LIMITATIONS.md)

Analytics dashboards cannot be exported or shared. Planned: PDF export via Playwright headless rendering, CSV export for raw data, and scheduled email reports using the same analytics functions. Not implemented.

---

### 5.17 Multi-tenant architecture

**From:** Limitation LX.2 (LIMITATIONS.md); marked "Tier 3"

Arcana is strictly single-tenant. All data, all users, and all ChromaDB vectors are in a single database and a single vector store. Multi-tenancy would require `tenant_id` foreign keys on all tables, per-tenant ChromaDB namespaces, and an onboarding/provisioning flow. This was explicitly deferred as out-of-scope for the thesis.

---

### 5.18 Self-hosted LLM option

**From:** Limitation LX.1 (LIMITATIONS.md)

When a developer queries Arcana, retrieved code chunks are sent to the Gemini API. For organizations with strict data residency requirements, a self-hosted LLM (via Ollama, vLLM, or Google Cloud private endpoints) was planned as an alternative. Offline mode (Ollama + local embeddings) partially addresses this for complete air-gap operation, but the production self-hosted Gemini alternative was not pursued.

---

### 5.19 Notion comment and discussion extraction

**From:** Limitation L3.3 (LIMITATIONS.md)

Page comments and discussion threads in Notion are not ingested. The Notion API exposes them separately from page content. Planned as a low-priority optional toggle due to the signal-to-noise concern (most comments are ephemeral).

---

### 5.20 Branch-aware indexing

**From:** Limitation L7.3 (LIMITATIONS.md)

Only the default branch (`main`/`master`) is indexed. Feature branches, open pull requests, and other branches are invisible to Arcana. A developer asking about code in a PR will not get answers about that code until it merges.

---

### 5.21 Citation accuracy verification

**From:** Limitation L5.6 (LIMITATIONS.md)

The current system instructs the LLM to cite sources and post-processes the output to extract citation numbers, but cannot verify that a cited source actually supports the claim it's cited for. A secondary NLI (Natural Language Inference) model or embedding-similarity check was planned to flag low-confidence citations.

---

### 5.22 React/Next.js web UI

**From:** Limitation LX.3 (LIMITATIONS.md)

Arcana has no customer-facing web application. Developer interaction happens through the Cursor extension, CLI, or Electron overlay. A React/Next.js frontend consuming the existing FastAPI REST API was planned as a post-thesis deliverable. The backend is designed to support this without any changes — all operations are exposed as REST endpoints.

---

## 6. Design Decisions Considered and Rejected

These are architectural choices that were explicitly evaluated and ruled out, not just deferred.

| Decision | What was considered | What was chosen | Why |
|----------|--------------------|-----------------|----|
| **LLM provider** | Anthropic (Claude) | Gemini API | Developer preference; Gemini's embedding-001 model offered 3072-dim vectors with asymmetric task types that aligned well with the retrieval design |
| **Vector database** | Pinecone, Weaviate, Qdrant | ChromaDB (embedded) | Zero infrastructure, zero additional service dependency, sufficient for thesis-scale data |
| **Relational database** | PostgreSQL from day one | SQLite (dev) / PostgreSQL (prod swap via env var) | Single-tenant, single-developer thesis context; SQLite requires no server; `DATABASE_URL` swap requires no code change |
| **Backend framework** | Next.js API routes (from prototype) | FastAPI | Better Python/ML ecosystem fit; primary consumers are CLI/extension/overlay not browsers |
| **Re-ranking backend** | Local cross-encoder (`ms-marco-MiniLM-L-6-v2`) | Cohere Rerank API (wired, not active) | API-based reranking eliminates CPU/GPU requirement on the server; neither was ultimately active |
| **Offline embedding model** | `all-mpnet-base-v2` (symmetric) | `BAAI/bge-base-en-v1.5` (asymmetric) | Asymmetric retrieval (query prefix) demonstrably outperforms symmetric models on retrieval benchmarks |
| **Offline LLM** | `phi4` (14B, think mode) | `qwen2.5:3b` only | `phi4` (~9.1 GB) too large and unreliable on Intel i5 hardware; `qwen2.5:3b` (~2.2 GB) reliable and fast |
| **Admin UI framework** | React + AdminJS, Retool | Streamlit (in full version) | Python-only, zero frontend build tooling, fast to implement for internal tooling; the full version built it in Streamlit; this simplified repo omits it entirely |
| **Extension distribution** | VS Code Marketplace | `.vsix` sideload | Marketplace requires publisher account, listing assets, and review process; sideload sufficient for single-company deployment |
| **Conversation history** | Server-side sessions table | Client-side `history[]` array passed per request | Keeps the backend stateless; sufficient for thesis Q&A use case; history is reset on page reload |
| **Ingest granularity** | Per-file continuous watch | On-demand user-triggered | Continuous watch requires `watchdog` process management and complicates the startup model; on-demand is explicit and predictable |
