# Arcana — Daily Context

> This file is updated at the end of every session. Read it at the start of each day to resume without re-explaining context.

---

**Last updated:** 2026-04-25 (session 18)

---

## Project Overview

AI-powered developer onboarding platform. Backend-first. Clients: Cursor extension, CLI, Electron overlay, and a browser web UI. Full description in README.md.

**Stack:** Python, FastAPI, ChromaDB, SQLite + SQLAlchemy async, Gemini API, Electron (macOS overlay).
**Monorepo layout:** `backend/` (FastAPI), `cli/` (Python CLI), `cursor/` (Cursor extension), `electron/` (macOS menu-bar overlay), `ui/` (browser web UI), `docs/` (PRDs, session logs, limitations).

---

## Current Phase

**Phase 1 — Project scaffold** ✅ COMPLETE

**Phase 2 — GitHub ingestion pipeline** ✅ COMPLETE

**Phase 3 — Notion ingestion pipeline** ✅ COMPLETE

**Phase 4 — RBAC** ✅ COMPLETE

**Phase 5 — AI Orchestration + Retrieval** ✅ COMPLETE

**Phase 6 — Cursor Extension + CLI** ✅ COMPLETE

**Phase 7 — Auto-updater (backend + CLI)** ✅ COMPLETE (PR #5, merged 2026-04-07)

**Phase 7.5 — Cursor UI for auto-updater** ✅ COMPLETE (PR #7, merged 2026-04-08)

**Phase 8 — Analytics data layer + admin dashboards** ✅ COMPLETE (PR #8, merged 2026-04-09)

**Phase 9 — Internal admin panel (Streamlit)** ✅ COMPLETE (PR #9, merged 2026-04-11)

**Phase 10 — Thesis Presentation Toolkit** ✅ COMPLETE (PR #10, merged 2026-04-11)

**Phase 11 — Local File Ingestion + PDF/DOCX support** ✅ COMPLETE (PR #13, merged 2026-04-14)

**Phase 12 — Local Models + Online/Offline Mode** ✅ COMPLETE (PR #14, merged 2026-04-15)

---

## What We Did Today (2026-04-25, session 18)

Added image analysis capability using vision models. Images are now analyzed at ingestion time and stored as detailed text descriptions in the RAG, enabling users to ask questions about image content (DNI, receipts, screenshots, etc.).

**New files:**
- `backend/arcana/services/vision_analyzer.py` — Analyzes images using Gemini (online mode only)
- `backend/arcana/services/vision_ocr.py` — OCR fallback using pytesseract
- `backend/arcana/services/image_captioner.py` — Basic caption fallback
- `backend/tests/test_image_ingestion.py` — Tests for image chunk generation

**Modified files:**
- `backend/arcana/services/chunker.py` — Added image handling branch (`language == "image"`) that:
  - Uses Gemini vision analysis in online mode
  - Falls back to caption + OCR in offline mode
  - Creates chunks with `source_type="image"` and `chunk_type="image_vision"` or `"image_text"`
- `backend/arcana/services/traversal.py` — Added image extensions (.png, .jpg, .jpeg, .gif, .bmp, .webp, .svg, .tiff) to `DEFAULT_INCLUDE_EXTENSIONS` and `LANGUAGE_MAP`
- `backend/arcana/config.py` — Added `image_caption_api_url` setting (optional remote captioning)
- `docs/GETTING_STARTED.md` — Updated prerequisites with Ollama setup instructions
- `backend/arcana/main.py` — Removed OCR startup check (optional dependencies)

**Behavior:**
- **Online mode**: Gemini analyzes images → detailed descriptions stored in RAG → users can ask questions about image content
- **Offline mode**: Vision analysis skipped → falls back to basic caption + OCR → limited image understanding
- Fallback chain: vision → caption → OCR → "Image file: {filename}"

**Testing:** 
- Users can ingest images (DNI, receipts, etc.) and ask questions like "What is the DNI number in the image?"
- In online mode, Gemini provides detailed image descriptions
- In offline mode, only basic caption + OCR is available (no vision model)

---

## What We Did Today (2026-04-15, session 17)

Deep RAG pipeline overhaul across 4 PRs. Root cause: Gemini embeddings are **3072-dim** while BGE local embeddings are **768-dim** — sharing collections caused a dimension mismatch that silently filtered out all retrieved chunks (score < threshold). Fixed by fully separating embedding spaces plus a cascade of speed/quality improvements.

**PR #15 — RAG accuracy improvements:**
- `config.py`: `retrieval_top_k=15` (was 10), `score_threshold=0.3` (new)
- `retrieval.py`: Rewrote with `_run_search(collections, embedding, top_k, label)` helper. Score threshold applied after sort. Removed all where-filter / legacy-fallback complexity. `vector_search` routes to `code_chunks`/`doc_chunks`; `vector_search_offline` routes to `code_chunks_local`/`doc_chunks_local`.
- `vector_store.py`: Added `get_code_collection_local()` and `get_doc_collection_local()` (separate BGE 768-dim collections).
- `local_embedder.py`: Switched model to `BAAI/bge-base-en-v1.5` (was `all-mpnet-base-v2`). Added `_BGE_QUERY_PREFIX`; `embed_query_local` prepends prefix (asymmetric retrieval). `store_chunks_local` tags `embedding_backend="local_bge"`.
- `embedder.py`: `store_chunks` tags `embedding_backend="gemini"` on every upserted chunk.
- `local_llm_client.py`: Added `"options": {"num_ctx": 8192, "num_predict": 2048}` to both `stream_response` and `stream_fallback` payloads.
- `prompt_builder.py`: Added `_OFFLINE_SYSTEM_PROMPT` (step-by-step, small-model optimised). `build_prompt` accepts `offline: bool = False`.
- `query_service.py`: Offline RAG branch now uses `assemble_context(chunks, token_budget=3500)` and `build_prompt(..., offline=True)`.
- New tests: `test_retrieval.py` (5 tests), `test_embedder_tagging.py` (2 tests), `test_query_routing.py` extended (3 new tests), `test_local_embedder.py` extended (query ≠ document embedding test).

**PR #16 — Local model speed:**
- `local_llm_client.py`: `_TIMEOUT` → 65.0 s. `keep_alive=300` (model stays in Ollama RAM 5 min). `num_ctx=4096`, `num_predict=512`.
- `ui/index.html`: Added elapsed timer (later replaced by PR #18).

**PR #17 — Critical dimension mismatch fix + pre-warm + setup spinner:**
- Root cause confirmed: `retrieval.query_error error='Collection expecting embedding with dimension of 3072, got 768'`. The old shared `code_chunks` / `doc_chunks` collections contain Gemini 3072-dim vectors; querying them with 768-dim BGE vectors raises a ChromaDB error → zero results → KB-miss fallback on every offline query.
- Fix already in `retrieval.py` (PR #15) — now route offline queries to the `_local` collections.
- `local_embedder.py`: Added `is_model_loaded() -> bool` (checks `_get_model.cache_info().currsize > 0`).
- `main.py`: FastAPI lifespan initialises local ChromaDB collections and fires `asyncio.create_task(_prewarm_local_model())` on startup so BGE model downloads/loads before any user query.
- `routers/health.py`: Returns `"embedding_model_ready": is_model_loaded()` in `/health/` response.
- `ui/index.html`: `_ensureLocalModelReady()` polls `/health/` every 2 s; shows `"⚙️ Setting up local environment (first-time download, one-time only)…"` spinner. Called on page load if offline, and when user switches to offline mode.

**PR #18 — Countdown timer:**
- Replaced elapsed timer with a countdown from mode-specific budget (15 s online, 45 s offline).
- Status line: `"Thinking — ~Ns remaining"` / `"Local model — ~Ns remaining"` counting down each second.
- Transitions to `"Streaming…"` on first SSE `chunk` event.
- 60 s hard abort via `AbortController` → `"Timed out after Xs — model took too long"`.
- Done line: `"Done — {src} | {n} exchanges · {t}s"`.

**Re-ingestion required for offline KB:**
Existing 189 Gemini-embedded chunks are in `code_chunks`/`doc_chunks` (3072-dim) — accessible only in online mode. To use the knowledge base in offline mode, re-ingest local files: switch to offline mode, then call `/ingest/local` with your paths. This populates `code_chunks_local`/`doc_chunks_local` with BGE 768-dim vectors.

---

## What We Did Today (2026-04-15, session 16)

Completed and shipped Phase 12. Also added Cancel button and simplified the offline model UI.

**Phase 12 shipped (PR #14, merged to main):**
- Full online/offline mode toggle with persistent settings (`backend/data/settings.json`)
- Ollama client (`local_llm_client.py`), local embedder (`local_embedder.py`, all-mpnet-base-v2, 768-dim)
- Settings store + router (`GET/POST /settings/`), mode-aware query pipeline, ingest guard (503 for GitHub/Notion in offline mode)
- Dual-theme UI in both Electron overlay and browser (bright blue = online, dark amber = offline)
- `pyproject.toml` pinned `sentence-transformers<5.0` and `numpy<2` (torch 2.2.x ABI constraint on Intel Mac)

**Post-merge changes (all committed directly to main):**
- **Models changed:** original model names (`qwen3.5`, `minimax-m2.7`) not yet in Ollama registry. Switched to `qwen2.5:3b` (Fast, ~2.2 GB) and `phi4` (Think, ~9.1 GB, 14B). Both confirmed available via `ollama pull`.
- **Fast/Think selector removed:** Think Mode requests were not completing reliably. Simplified to a single offline model: `qwen2.5:3b` always. Removed Fast/Think pill buttons from both UIs, removed `offline_model` from settings store and API, `query_service` now uses `settings.ollama_fast_model` directly.
- **Cancel button:** red-outlined Cancel button appears while a query streams in both UIs. Aborts the fetch via `AbortController`, re-enables Ask, shows "Cancelled" in status. Works for both online and offline modes.
- **Bug fix:** `routers/health.py` still imported `get_offline_model` after it was removed — caused `ImportError` on startup. Fixed.
- **README updated** with three-terminal run instructions (ollama serve + backend + overlay), model download steps, online/offline mode table.

**Current offline model:** `qwen2.5:3b` (only one model, no selector)

**Settings stored in `backend/data/settings.json`:** only `online_mode` (bool). `offline_model` key removed entirely.

**Setup required (first-time offline use):**
```bash
# Ollama is likely already running (check with: ollama ps)
ollama pull qwen2.5:3b    # ~2.2 GB — the only offline model
# sentence-transformers all-mpnet-base-v2 auto-downloads on first offline query (~420 MB, must be online once)
```

**Tests:** 16 pass (settings, query routing, ingest guards). 4 `test_local_embedder` tests have a venv environment conflict (torch 2.2.x / numpy / transformers version mismatch in the shared venv) — not a code issue, tests were green after the initial Phase 12 implementation.

---

## What We Did Today (2026-04-14, session 14)

Implemented Phase 11: on-demand local file ingestion without requiring GitHub or Notion credentials.

**Backend (`backend/`):**
- `POST /ingest/local` — accepts `{"paths": ["/abs/path/to/dir"]}`, runs **synchronously** (not a background task), returns `{embedded, skipped_files, deleted_chunks, errors}` immediately.
- **Smart mtime diffing:** compares `os.stat().st_mtime` against the `last_modified` value stored in ChromaDB metadata; only re-embeds files that changed since last ingest. Stale chunks deleted for removed files.
- **PDF support** (`pypdf>=4.0.0`): `_extract_pdf_text()` in `chunker.py`; text → line-based chunks with `source_type="documentation"` → routed to `doc_chunks` collection.
- **DOCX support** (`python-docx>=1.1.0`): `_extract_docx_text()` in `chunker.py`; paragraphs joined, same routing.
- **`.pdf` + `.docx`** added to `traversal.py` `DEFAULT_INCLUDE_EXTENSIONS` + `LANGUAGE_MAP`.
- New `services/local_service.py` — single function `get_file_mtime(abs_path: Path) -> str` returning UTC ISO timestamp.
- `repo_key = f"local:{local_path.resolve()}"` uses full resolved path to prevent chunk ID collisions between directories with the same name.
- Diff helpers query **both** ChromaDB collections (`code_chunks` + `doc_chunks`) since local dirs can contain mixed file types.
- Local ingestion is **never auto-run on startup** — always explicit/on-demand by user choice.
- 422 validation in router if `paths` is empty or absent.

**Electron overlay (`electron/`):**
- ⊕ Local button added to status bar (`electron/index.html`).
- Clicking opens a native macOS directory picker dialog (`dialog.showOpenDialog`); selected path sent to `POST /ingest/local`.
- "Update local knowledge…" item added to tray context menu (`electron/main.js`).
- `onIngestStatus` handler refactored to handle all three sources (github/notion/local) generically via `INGEST_LABELS` map.

**Browser UI (`ui/`):**
- "Local" button added to the ingest bar; clicking toggles a path input row.
- User types an absolute directory path and presses Enter or "Sync".
- Shows `embedded / skipped` counts on completion (works because the endpoint is synchronous).

**Bugs caught in audit:**
- `repo_key` used only `local_path.name` → collision risk for same-named dirs → fixed to use `local_path.resolve()`.
- Bare `except Exception: pass` in `_get_existing_local_timestamps` → replaced with `log.warning(...)`.
- Router originally used `BackgroundTasks` → `data.embedded` in JS would always be undefined → made endpoint synchronous.
- Stale "overrides LOCAL_PATHS env var" comment → removed.

**PR #13** squash-merged to main (2026-04-14).

---

## What We Did Today (2026-04-11, session 13)

- Implemented Phase 10 (Thesis Presentation Toolkit) in full across 7 tasks, PR #10 open:
- **Demo mode:** `ARCANA_DEMO_MODE=true` routes to isolated `data/demo.db` + `data/demo_chromadb/` via `Settings.effective_database_url` / `effective_chromadb_path`. Seed script: 6 users (deterministic `arc_demo_*` API keys), 3 sources, ~160 synthetic chunks, 1 000 audit events, 4 weeks of update records + weekly reviews, 20 pre-warmed cache entries.
- **Retrieval evaluation:** `arcana eval run` benchmarks against a 20-query gold standard (4 categories, 3 difficulty levels). Metrics: P@5, P@10, R@10, R@20, MRR, HR@5 — with ablation modes (hybrid/vector-only/bm25-only) and CSV/JSON export.
- **Visual indicators (all surfaces):** `/health` endpoint returns `demo_mode: bool`. Streamlit: `show_demo_banner()` on all 7 pages. CLI: `[DEMO]` prefix in `_global_callback`. Cursor: amber `DEMO` badge in sidebar header fed by `pingHealth()` returning `{latencyMs, demoMode}`.
- **CLI commands:** `arcana demo status`, `arcana eval run`, `arcana ask --api-key` override.
- **Makefile:** `demo-seed`, `demo-reset`, `test-demo`, `test-eval`.
- **Docs:** `docs/ARCHITECTURE.md` (component map + 15-step data flow trace), README updated (demo/eval sections, new env vars, phases table, Makefile table).
- **Tests:** 68 new tests (`test_demo.py` + `test_eval.py`) → **345 total, 1 skipped**
- Fixed `demo.py` CLI bug: `api_get` call had wrong `api_key_` parameter name and dict passed as `api_key`.
- Fixed `gold_standard.json` bug: Python `.replace()` method call embedded in JSON (invalid) → replaced with static string.

## What We Did Today (2026-04-11, session 12)

- Implemented Phase 9 in full: 7-page Streamlit admin panel consuming the existing FastAPI API surface
- **`admin/` monorepo directory:** `app.py` (entry point + auth redirect), `config.py`, `utils.py`, `api_client.py` (shared HTTP client with full error handling), `auth.py` (auto-login via env var, manual login, session management)
- **Pages:** Overview (health cards, metrics, alerts, quick actions, 60s auto-refresh), Users (CRUD + permissions + key rotate), Sources (status cards, re-sync, sensitive toggle), Analytics (5 Plotly charts + date range), Audit Log (filterable + paginated), Weekly Review (narrative + revert flow + acknowledgment), Cache (metrics + flush/invalidate)
- **Tests:** 29 admin panel tests covering API client (success + 6 error paths), auth flow (5 scenarios), utilities (format_relative_time, validate_correction)
- **Bug caught in audit:** `_revert_section` in `6_Weekly_Review.py` defined after use — fixed by hoisting to top of file
- **Infrastructure:** `admin` service added to `docker-compose.yml` (bound to `127.0.0.1:8501`), `run-admin` + `test-admin` Makefile targets
- **Total tests:** 277 backend + 28 CLI + 52 extension + 29 admin = **386 total, all passing**

---

## What We Did Today (2026-04-09, session 10)

- Implemented Phase 8 in full: real analytics data layer replacing hallucinated LLM numbers
- **Backend:** `analytics_service.py` (5 SQL/ChromaDB functions + TTL context cache), `schemas/analytics.py` (5 Pydantic component types), 6 endpoints at `/admin/analytics/` (senior_dev+), Alembic migration 0003 (audit_logs.user_id index), `AuditEventType.analytics_viewed`
- **Gemini upgrade:** `response_schema` + `application/json` mime type for visual queries; regex fallback removed from `component_renderer.py`
- **Analytics context injection:** `prompt_builder.py` injects real SQL aggregates into visual ad-hoc queries via sync module-level cache
- **Query completion tracking:** `routers/query.py` updates audit_log with `cache_hit`, `latency_ms`, `chunks_used` from SSE done event
- **CLI:** `arcana dashboard` command (`--metric`, `--from`, `--to`, `--raw`) with full Rich rendering
- **Cursor:** Dashboard button (⬡), separate `#dashboard-screen` div, range selector, collapsible component sections, auto-refresh
- Fixed pre-existing test env issue: project venv at `.venv/` (Python 3.12 + SQLAlchemy 2.x) — not base conda env
- Fixed 3 test bugs: module-level imports for `get_code_collection`/`get_doc_collection`/`cache_stats` (patchable), `src.type` string handling in coverage gaps, `pytest.importorskip` for CLI test
- **277 backend + 28 CLI + 52 extension = 357 tests, all passing (1 skipped: CLI venv)**

## What We Did Today (2026-04-09, session 11)

- Squash-merged PR #8 to main (`d2293f8`); main is clean and fully up to date
- No new code — housekeeping session only

## What We Did Today (2026-04-08, session 9)

- Fixed `test_auto_updater.py` path bug (tests failed under `make test` due to hardcoded relative path)
- Implemented Phase 7.5 in full: review badge, weekly summary card, revert inline form (PR #7)
- Three rounds of audit — 15+ bugs caught and fixed across all rounds
- 52 cursor extension tests (up from 20), 250 backend tests, all passing
- Cleaned up 15 Finder duplicate `* 2` files; PR #7 squash-merged to main

---

## What We Did Today (2026-04-07, session 8)

- Cleaned up Finder duplicate `* 2.*` files left by a bad git pull
- Phase 7 PRD finalized (4 design decisions answered): GitHub API compare over persistent clones, first-run baseline strategy, Cursor UI deferred to 7.5, backend + CLI only in Phase 7
- Implemented Phase 7 in full:
  - `auto_updater.py`, `github_updater.py`, `notion_updater.py`, `update_summarizer.py`, `weekly_review_service.py`
  - `UpdateRecord`, `WeeklyReview` models + Alembic migration `0002_phase7_auto_updater.py`
  - `AuditEventType` extended (6 new types)
  - 10 API endpoints under `/admin/updater/*` + `DELETE /corrections/{id}`
  - CLI: `arcana updater run|review-week|revert|reverts|history|correction-delete` + Friday banner
  - Unified APScheduler (`daily_auto_update` + `weekly_review` jobs)
  - 7 new config settings, `notion_sync_interval_hours` deprecated
- Two rounds of PRD gap analysis; all gaps resolved:
  - Round 1: reranker boost for admin_correction chunks, delete correction endpoint
  - Round 2: `get_page_status()` for archived Notion pages, HTTP 400 (not 422) for short corrections, deprecation comment in config
- 250 backend tests pass (198 existing + 52 new Phase 7 tests)
- PR #5 squash-merged to main
- Git committer name changed from "Gigsify" to "Ignacio"

---

## What We Did Today (2026-04-05, session 7)

- Migrated Gemini SDK from `google-generativeai` (deprecated) to `google-genai` (PR #4, squash-merged to main):
  - `backend/arcana/services/gemini_client.py` — `_get_model()` → `_get_client()` using `genai.Client(api_key=...)`. Streaming via `client.models.generate_content_stream()`, non-streaming via `client.models.generate_content()`. Both use `types.GenerateContentConfig(temperature, max_output_tokens)`.
  - `backend/arcana/services/prompt_builder.py` — `_count_tokens_gemini()` updated to `client.models.count_tokens()`.
  - `backend/pyproject.toml` — `google-generativeai>=0.8.0` → `google-genai>=1.0.0`.
  - 198 backend tests pass, zero warnings.
- Confirmed all branches are behind or equal to `main` (no diverged work outside main).

---

## What We Did Today (2026-04-05, session 6)

- Reorganised repo into monorepo layout (1 commit):
  - `backend/` — all existing FastAPI code (arcana package, migrations, tests, pyproject.toml, alembic.ini, Dockerfile, .env*)
  - `cli/` — Python CLI (new)
  - `cursor/` — Cursor extension (new)
  - `docs/` — PRDs, LIMITATIONS.md, session logs
  - Updated `Makefile` (new targets: run-backend, test-backend, build-extension, test-extension, install-cli, test-cli), `docker-compose.yml` (build context → ./backend), `.github/workflows/ci.yml` (working-directory: backend), `.pre-commit-config.yaml` (pytest + mypy paths)

- Executed Phase 6 PRD in full (1 commit, branch `feature/phase6-cursor`):

  **CLI (`cli/`):**
  - `arcana_cli/config.py` — TOML config at `~/.arcana/config.toml` (0600 perms), mask_key helper
  - `arcana_cli/api/client.py` — httpx + httpx-sse SSE streaming + REST helpers (get/post/patch/delete), typed error classes
  - `arcana_cli/rendering/citations.py` — OSC 8 clickable hyperlinks (iTerm2/kitty), Rich Panel references block
  - `arcana_cli/rendering/components.py` — table (Rich Table), metric_card (Rich Panels), chart (plotext + text fallback), timeline (Rich Tree), progress bars; `detect_component()` for JSON detection
  - `arcana_cli/rendering/markdown.py` — Rich Markdown wrapper
  - `arcana_cli/commands/ask.py` — streaming with Rich Live + Markdown, visual component detection on done event
  - `arcana_cli/commands/config.py` — set-key, set-server, show (masked), test (health ping)
  - `arcana_cli/commands/users.py` — list, create, update, deactivate, rotate-key
  - `arcana_cli/commands/sources.py` — list, status, sync, sensitive toggle; auto-detects GitHub vs Notion sync URL
  - `arcana_cli/commands/cache.py` — stats, flush (with --yes confirmation), invalidate --scope
  - `arcana_cli/commands/audit.py` — list with --user/--type/--from/--to filters
  - `arcana_cli/main.py` — Typer app + `reindex <id>|--all` (iterates sources, detects type, fires sync)
  - 28 tests all passing

  **Cursor extension (`cursor/`):**
  - `src/extension.ts` — activation, command registration (ask, askAboutSelection, clearChat)
  - `src/sidebar/SidebarProvider.ts` — WebviewViewProvider, nonce CSP, config injection, 60s health ping, message routing
  - `src/api/arcanaClient.ts` — fetch-based SSE generator (`streamQuery`), `parseSSEEvent`, `pingHealth`
  - `src/editor/navigation.ts` — `openCodeCitation` (jump to line + 1.5s highlight, GitHub fallback), `openExternal`, `resolveWorkspacePath`
  - `src/context/activeFile.ts` — `onDidChangeActiveTextEditor` tracker → sends `context_file` with every query
  - `webview/styles.css` — VS Code theme variables, chat bubbles, citation badges, all component styles
  - `webview/main.js` — chat UI, fetch-based SSE streaming, marked.js markdown, Prism.js syntax highlighting, Chart.js charts, sortable tables, metric cards, timeline, progress bars, citation badges + references panel
  - `build.js` — esbuild bundle + copy webview libs from node_modules (marked, prism, chart.js)
  - 20 Jest tests all passing (SSE parsing, component detection, path resolution)

- **Total tests:** 198 (backend) + 28 (CLI) + 20 (extension) = 246, all passing

---

## Key Decisions (cumulative)

- **No Next.js** — FastAPI is the single backend
- **SQLite for dev, PostgreSQL for prod** — swap via DATABASE_URL in `.env`
- **Gemini API** (not Anthropic) for LLM
- **GITHUB_PAT + NOTION_TOKEN in `.env`** — tokens never stored in DB
- **Commit + push per feature**
- **PRD-driven** — each task has a PRD in `docs/prds/phase<n>/`
- **Same repo** — main is the active Python branch
- **Not deploying to Vercel** — Railway/Fly.io/VPS recommended
- **User API keys hashed in DB (not env vars)** — kept because per-user audit logs and permission scoping depend on it
- **Access control** — all CLI and extension requests require a valid API key issued by the admin (`arcana users create`). No self-signup. Roles enforced server-side.
- **Phase 7: GitHub API compare over persistent clones** — same data, zero disk management
- **Phase 7: First-run baseline** — record HEAD, skip on missing `last_synced_commit`, no noisy records
- **Phase 7.5 (Cursor UI) deferred** — backend API fully supports it; implement separately
- **Phase 11: local ingestion is always on-demand** — user selects paths explicitly; no `LOCAL_PATHS` env var; no auto-run on startup
- **Phase 11: synchronous endpoint for local** — unlike GitHub/Notion (background tasks), `/ingest/local` awaits completion so frontends receive embedded/skipped counts immediately
- **Phase 11: repo_key uses full resolved path** — prevents chunk ID collisions for directories with the same name
- **Phase 12: keep_alive=0 on Ollama** — model unloads after each request; cold-start tradeoff accepted for Intel i5 hardware
- **Phase 12: all-mpnet-base-v2 (768-dim)** — same dimension as gemini-embedding-001; ChromaDB collections structurally compatible across online/offline modes
- **Phase 12: offline restricts ingestion only** — existing embedded chunks (GitHub, Notion, local) remain queryable in offline mode
- **Phase 12: settings in backend/data/settings.json** — both frontends read/write through `/settings/` API; persistent across restarts
- **Phase 12: single offline model** — Fast/Think selector removed; `qwen2.5:3b` always used in offline mode; `offline_model` setting removed entirely
- **Phase 12: Cancel button** — `AbortController` already wired; Cancel button shows while streaming, aborts on click, works for both Gemini and Ollama paths
- **Development scope rule:** all UI/feature changes apply to both online and offline modes unless explicitly scoped otherwise
- **Session 17: Separate ChromaDB collections per embedding space** — Gemini (3072-dim) uses `code_chunks`/`doc_chunks`; BGE (768-dim) uses `code_chunks_local`/`doc_chunks_local`. Sharing was impossible: ChromaDB enforces consistent dimension per collection and cross-space cosine scores are meaningless.
- **Session 17: Switch to BAAI/bge-base-en-v1.5** — Replaces all-mpnet-base-v2. Asymmetric: query prefix prepended at query time only; documents stored without prefix. Same 768-dim; no ChromaDB schema change.
- **Session 17: keep_alive=300 on Ollama** — Model stays in RAM 5 min between queries; eliminates cold-start latency on back-to-back questions. Was 0 (unload immediately).
- **Session 17: num_ctx=4096, num_predict=512** — Matches actual context budget (3500 token assembly + overhead). Was 8192/2048.
- **Session 17: BGE pre-warm on server startup** — `asyncio.create_task(_prewarm_local_model())` in lifespan ensures the 768-dim model is loaded before any user query. UI polls `/health/` and shows a one-time setup spinner.
- **Session 17: Countdown timer (not elapsed)** — Mode-specific budget (15 s online / 45 s offline) counts down; transitions to "Streaming…" on first token; 60 s hard abort.

---

## Local Dev Setup (already done)

```bash
cd /Users/Ignacio/Desktop/Workspace/ig-arcana-simple
source .venv/bin/activate   # always activate first
```

Remaining first-time steps (not done yet):
```bash
pre-commit install           # activate pre-commit hooks (once)
cd backend && cp -n .env.example .env   # fill in APP_SECRET_KEY + GEMINI_API_KEY + GITHUB_PAT + NOTION_TOKEN
make setup                   # creates DB tables (runs from backend/)
make seed                    # prints admin API key
make run-backend             # starts server at http://localhost:8000/docs
```

First-time Phase 5 setup (after `make setup`):
```bash
cd backend && python -m arcana.scripts.backfill_fts5   # backfill existing chunks into FTS5 (idempotent)
```

First-time Phase 6 setup:
```bash
make install-cli             # installs arcana CLI into the venv
make build-extension         # bundles cursor/out/extension.js + copies webview libs
# To install extension: sideload cursor/*.vsix in Cursor via Extensions > Install from VSIX
```

**Tests:**
```bash
make test-backend            # 345 backend tests (use project venv .venv/, not base conda)
make test-cli                # 28 tests
make test-extension          # 52 tests (Jest)
make test-admin              # 29 tests (admin panel)
make test-demo               # 34 demo isolation tests
make test-eval               # 34 retrieval eval tests
```

---

## Known Issues / Deferred

- `test_local_embedder` (4 tests) fail due to venv environment conflict: torch 2.2.x compiled against NumPy 1.x, but the shared venv keeps reverting to NumPy 2.x after package installs. Not a code issue — tests were green at initial implementation. Fix requires stabilising the shared venv or isolating the project venv.
- **Offline KB is empty until re-ingested.** Existing 189 Gemini chunks are 3072-dim and live in `code_chunks`/`doc_chunks` — only accessible in online mode. To query local knowledge offline, user must call `/ingest/local` with source paths while in offline mode to populate `code_chunks_local`/`doc_chunks_local` with BGE 768-dim vectors.

---

## Next Session

1. **Re-ingest for offline KB:** switch to offline mode, call `POST /ingest/local` with project paths to populate BGE collections. Verify offline queries return non-empty chunks.
2. **Verify offline mode end-to-end after re-ingest:** ask a question in offline mode, confirm chunks surface and Qwen2.5:3b uses them.
3. **Consider next feature** — possible candidates: watch mode for local paths (auto-reingest on file change via `watchdog`), conversation history panel, source filtering UI

---

## Branches

| Branch | Purpose |
|---|---|
| `main` | Active development |
| `v0-project-29mar` | Archived Next.js prototype — reference only |

---

## Session Log

| Date | Session | What happened |
|---|---|---|
| 2026-03-29 | 1 | Migrated to Python/FastAPI, executed Phase 1 PRD (full scaffold), set up CI |
| 2026-03-29 | 2 | Executed Phase 2 PRD (GitHub ingestion pipeline), refactored to env-var token storage |
| 2026-03-29 | 3 | Executed Phase 3 PRD (Notion ingestion pipeline), created LIMITATIONS.md, updated .env.example |
| 2026-04-04 | 4 | Executed Phase 4 PRD (RBAC + Permission System), documented env var vs. DB key tradeoff (L4.3b) |
| 2026-04-05 | 5 | Executed Phase 5 PRD (AI Orchestration + Retrieval Pipeline), 198 tests all passing |
| 2026-04-05 | 6 | Reorganised repo into monorepo (backend/cli/cursor/docs), executed Phase 6 PRD (CLI + Cursor extension), 246 tests total |
| 2026-04-05 | 7 | Migrated Gemini SDK to google-genai (PR #4), confirmed main is ahead of all branches |
| 2026-04-07 | 8 | Executed Phase 7 PRD (auto-updater + weekly review + revert flow), 2 gap audits, 250 tests, PR #5 merged |
| 2026-04-08 | 9 | Phase 7.5 (Cursor UI): review badge, summary card, revert form; 3 audit rounds; 52 extension tests; PR #7 merged |
| 2026-04-09 | 10 | Phase 8 (Analytics): real SQL/ChromaDB data layer, 6 admin endpoints, CLI dashboard command, Cursor dashboard screen; 357 tests passing |
| 2026-04-09 | 11 | Squash-merged PR #8 to main; main clean and up to date |
| 2026-04-11 | 12 | Phase 9 (Streamlit admin panel): 7 pages, 29 tests, PR #9 merged |
| 2026-04-11 | 13 | Phase 10 (Thesis Toolkit): demo mode, retrieval eval, architecture docs, 68 new tests → 345 total, PR #10 merged |
| 2026-04-14 | 14 | Phase 11 (Local File Ingestion): `POST /ingest/local`, mtime diffing, PDF+DOCX support, Electron dir picker, browser UI path input; PR #13 merged |
| 2026-04-15 | 15 | Phase 12 (Local Models + Online/Offline): Ollama client, local embedder (all-mpnet-base-v2), settings store+router, mode-aware query pipeline, ingest guard, dual-theme frontend; 24 tests |
| 2026-04-15 | 16 | Phase 12 shipped (PR #14 merged); models switched to qwen2.5:3b + phi4; Fast/Think selector removed (single model); Cancel button added to both UIs; health.py ImportError bug fixed; README updated |
| 2026-04-15 | 17 | RAG pipeline overhaul (4 PRs): BGE model switch, separate 3072/768-dim ChromaDB collections, score threshold, offline system prompt + token budget, Ollama keep_alive/num_ctx, BGE pre-warm on startup, countdown timer in UI |
