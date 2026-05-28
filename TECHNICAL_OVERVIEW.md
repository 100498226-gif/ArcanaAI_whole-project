# Arcana — Technical Overview

Arcana is an AI-powered developer knowledge assistant. It indexes a team's codebase (GitHub repositories) and internal documentation (Notion pages or local files) into a searchable vector store, then answers natural-language questions with grounded, cited responses. It operates in two independent modes: **online** (Gemini API for both embeddings and LLM) and **offline** (local BGE embeddings + Ollama LLM, no internet required).

---

## Table of Contents

1. [System Architecture](#1-system-architecture)
2. [Stack and Dependencies](#2-stack-and-dependencies)
3. [Environment Variables](#3-environment-variables)
4. [Database Schema](#4-database-schema)
5. [Backend Structure](#5-backend-structure)
6. [RAG Pipeline](#6-rag-pipeline)
7. [Ingestion Pipeline](#7-ingestion-pipeline)
8. [Embedding Strategy](#8-embedding-strategy)
9. [LLM Integration](#9-llm-integration)
10. [Context Assembly](#10-context-assembly)
11. [Frontend Surfaces](#11-frontend-surfaces)
12. [Testing](#12-testing)
13. [CI/CD](#13-cicd)
14. [Reproduction Guide](#14-reproduction-guide)
15. [Known Constraints](#15-known-constraints)

---

## 1. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Client Layer                             │
│  ┌─────────────────────┐    ┌──────────────────────────────┐   │
│  │  Browser UI          │    │  Electron Overlay (macOS)    │   │
│  │  ui/index.html       │    │  electron/main.js            │   │
│  │  Vanilla JS + SSE    │    │  Hotkey: Ctrl+Alt+Space      │   │
│  └──────────┬──────────┘    └──────────────┬───────────────┘   │
└─────────────┼──────────────────────────────┼───────────────────┘
              │  HTTP + SSE                   │
┌─────────────▼──────────────────────────────▼───────────────────┐
│                     FastAPI Backend  :8000                      │
│                                                                  │
│  POST /query/    POST /ingest/*    GET|POST /settings/          │
│  GET  /health/                                                   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    Query Service                         │   │
│  │  1. embed question  →  2. vector search  →  3. assemble  │   │
│  │  4. build prompt    →  5. stream LLM response            │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐ │
│  │  ChromaDB    │  │  SQLite      │  │  settings.json        │ │
│  │  (4 cols)    │  │  (5 tables)  │  │  {online_mode: bool}  │ │
│  └──────────────┘  └──────────────┘  └───────────────────────┘ │
└────────────────┬──────────────────────────┬────────────────────┘
                 │ online mode               │ offline mode
        ┌────────▼─────────┐      ┌─────────▼────────────┐
        │  Gemini API      │      │  Ollama (localhost)   │
        │  gemini-2.5-     │      │  qwen2.5:3b           │
        │  flash-lite      │      │  + BGE embedder       │
        │  + embedding-001 │      │  BAAI/bge-base-en-v1.5│
        └──────────────────┘      └──────────────────────┘
```

### Component responsibilities

| Component | File | Responsibility |
|-----------|------|----------------|
| FastAPI app | `backend/arcana/main.py` | App factory, lifespan hooks, router registration |
| Config | `backend/arcana/config.py` | Pydantic `Settings`, `.env` loading, Gemini client factory |
| Vector store | `backend/arcana/vector_store.py` | ChromaDB singleton, 5 collection accessors |
| Query router | `backend/arcana/routers/query.py` | SSE streaming endpoint `POST /query/` |
| Ingest router | `backend/arcana/routers/ingest.py` | GitHub / Notion / local ingestion endpoints |
| Health router | `backend/arcana/routers/health.py` | `GET /health/` — chunk counts, Ollama ping, model ready |
| Settings router | `backend/arcana/routers/settings.py` | `GET/POST /settings/` — online_mode toggle |
| Query service | `backend/arcana/services/query_service.py` | Full RAG orchestration (embed → retrieve → assemble → stream) |
| Retrieval | `backend/arcana/services/retrieval.py` | ChromaDB query, score threshold, top-k selection |
| Embedder (online) | `backend/arcana/services/embedder.py` | Gemini embedding-001, 3072-dim |
| Embedder (offline) | `backend/arcana/services/local_embedder.py` | BGE bge-base-en-v1.5, 768-dim |
| Gemini client | `backend/arcana/services/gemini_client.py` | Gemini streaming via `google-genai` |
| Ollama client | `backend/arcana/services/local_llm_client.py` | Ollama streaming via OpenAI-compat endpoint |
| Ingestion | `backend/arcana/services/ingestion.py` | GitHub + Notion + local ingest pipelines |
| Chunker | `backend/arcana/services/chunker.py` | AST-based code chunking + doc/PDF/DOCX splitting |
| Traversal | `backend/arcana/services/traversal.py` | File tree walk with ignore rules and size limits |
| Prompt builder | `backend/arcana/services/prompt_builder.py` | System prompts + `[SOURCE N]` block formatting |
| Context assembler | `backend/arcana/services/context_assembler.py` | Dedup, priority sort, token budget fill |
| Settings store | `backend/arcana/services/settings_store.py` | JSON persistence at `backend/data/settings.json` |

---

## 2. Stack and Dependencies

**Runtime:** Python 3.11+  
**Build backend:** Hatchling  
**Package manager:** pip (editable install via `pip install -e ".[dev]"`)

### Core dependencies (`backend/pyproject.toml`)

| Package | Version constraint | Purpose |
|---------|--------------------|---------|
| `fastapi` | `>=0.115.0` | Web framework |
| `uvicorn[standard]` | `>=0.34.0` | ASGI server |
| `sqlalchemy[asyncio]` | `>=2.0.0` | ORM (async) |
| `aiosqlite` | `>=0.21.0` | SQLite async driver |
| `asyncpg` | `>=0.30.0` | PostgreSQL async driver (production swap) |
| `alembic` | `>=1.14.0` | Database migrations |
| `pydantic[email]` | `>=2.10.0` | Data validation |
| `pydantic-settings` | `>=2.7.0` | `.env` config loading |
| `chromadb` | `>=0.6.0` | Vector store |
| `google-genai` | `>=1.0.0` | Gemini LLM + embeddings |
| `sentence-transformers` | `>=3.0,<5.0` | BGE local embeddings |
| `numpy` | `<2` | Required by torch 2.2.x ABI |
| `httpx` | `>=0.28.0` | Async HTTP (Ollama client) |
| `structlog` | `>=24.0.0` | Structured JSON logging |
| `tree-sitter` | `>=0.23` | AST parsing for code chunking |
| `tree-sitter-python/javascript/typescript` | `>=0.23` | Language grammars |
| `tiktoken` | `>=0.8` | Token counting (`cl100k_base`) |
| `PyGithub` | `>=2.0` | GitHub API |
| `gitpython` | `>=3.1` | Git operations |
| `notion-client` | `>=2.0` | Notion API |
| `apscheduler` | `>=3.10` | Scheduled jobs |
| `sse-starlette` | `>=2.0` | Server-sent events |
| `cohere` | `>=5.0` | Reranking (wired, not actively used) |
| `pypdf` | `>=4.0.0` | PDF text extraction |
| `python-docx` | `>=1.1.0` | DOCX text extraction |
| `cryptography` | `>=44.0` | Internal token signing |

### Dev dependencies

`pytest>=8.0.0`, `pytest-asyncio>=0.25.0`, `black>=24.0.0`, `ruff>=0.8.0`, `mypy>=1.13.0`, `pre-commit>=4.0.0`

### Electron (overlay)

`electron@30.0.0`, `uiohook-napi@1.5.5` (global hotkey)

---

## 3. Environment Variables

Copy `backend/.env.example` to `backend/.env`. Variables marked **REQUIRED** must be set; others have sane defaults.

### Core

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `APP_ENV` | Yes | — | `development` \| `testing` \| `production` |
| `APP_SECRET_KEY` | Yes | — | Random 32-byte URL-safe string. Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `DATABASE_URL` | Yes | — | `sqlite+aiosqlite:///./data/arcana.db` for dev; `postgresql+asyncpg://...` for production |
| `CHROMADB_PATH` | Yes | `./data/chromadb` | Filesystem path for persistent ChromaDB storage |
| `LOG_LEVEL` | No | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` |
| `CORS_ORIGINS` | No | `*` | Comma-separated allowed origins |

### Embeddings

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `EMBEDDING_PROVIDER` | Yes | `google` | `google` \| `openai` \| `voyage` |
| `EMBEDDING_MODEL` | Yes | `gemini-embedding-001` | Model name for the chosen provider |

### Gemini (online mode)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_API_KEY` | Yes | — | From [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) |
| `GEMINI_MODEL` | No | `gemini-2.5-flash-lite` | LLM model for answering questions |

### GitHub ingestion

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GITHUB_PAT` | For GitHub | — | Personal access token with `repo` + `read:org` scopes |
| `GITHUB_REPOS` | No | `""` | Comma-separated `owner/repo` list for bootstrap auto-ingest |

### Notion ingestion

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NOTION_TOKEN` | For Notion | — | Internal integration token (`secret_...`) from notion.so/my-integrations |
| `NOTION_PAGE_IDS` | No | `""` | Comma-separated Notion page IDs for bootstrap auto-ingest |
| `NOTION_SYNC_INTERVAL_HOURS` | No | `24` | Hours between scheduled Notion re-syncs |
| `NOTION_MAX_DEPTH` | No | `5` | Maximum page nesting depth to traverse |
| `NOTION_REQUEST_DELAY_MS` | No | `350` | Milliseconds between Notion API calls (rate limit: 3 req/s) |

### Ollama (offline mode)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OLLAMA_BASE_URL` | No | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_FAST_MODEL` | No | `qwen2.5:3b` | Model name to use for offline answering |

### RAG tuning

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `RETRIEVAL_TOP_K` | No | `15` | Chunks retrieved per query |
| `CONTEXT_TOKEN_BUDGET` | No | `6000` | Max tokens assembled into LLM context (online). Offline path hard-codes 3500. |
| `SCORE_THRESHOLD` | No | `0.3` | Minimum cosine similarity to include a chunk |
| `GEMINI_TEMPERATURE` | No | `0.2` | LLM sampling temperature |
| `GEMINI_MAX_OUTPUT_TOKENS` | No | `2000` | Max tokens in Gemini response |

---

## 4. Database Schema

### SQLite tables (managed by Alembic)

**users**
```
id            INTEGER PRIMARY KEY
email         TEXT UNIQUE NOT NULL
name          TEXT
role          TEXT  -- admin | senior_dev | dev | viewer
team          TEXT
api_key_hash  TEXT  -- bcrypt hash
is_active     BOOLEAN DEFAULT 1
created_at    DATETIME
updated_at    DATETIME
```

**data_sources**
```
id              INTEGER PRIMARY KEY
type            TEXT  -- github_repo | notion_workspace
name            TEXT
config_json     TEXT  -- JSON: {url, branch, ...}
access_scope    TEXT
status          TEXT  -- pending | syncing | active | error
last_synced_at  DATETIME
```

**permissions**
```
id            INTEGER PRIMARY KEY
user_id       INTEGER REFERENCES users(id)
source_id     INTEGER REFERENCES data_sources(id)
access_level  TEXT  -- read | read_write | admin
granted_by    INTEGER REFERENCES users(id)
created_at    DATETIME
```

**audit_logs**
```
id                INTEGER PRIMARY KEY
user_id           INTEGER REFERENCES users(id)
query_text        TEXT
sources_accessed  TEXT  -- JSON array
chunks_retrieved  INTEGER
response_time_ms  INTEGER
timestamp         DATETIME
cache_hit         BOOLEAN
embedding_backend TEXT  -- gemini | local_bge
```

**update_records**
```
id               INTEGER PRIMARY KEY
source_id        INTEGER REFERENCES data_sources(id)
change_type      TEXT  -- added | modified | deleted
diff_summary     TEXT
affected_chunks  TEXT  -- JSON array of chunk_ids
confidence       FLOAT
change_timestamp DATETIME
```

**weekly_reviews**
```
id             INTEGER PRIMARY KEY
source_id      INTEGER
narrative      TEXT
status         TEXT  -- pending | acknowledged
generated_at   DATETIME
acknowledged_at DATETIME
```

Migration files are in `backend/migrations/versions/`:
- `0001_initial_schema.py` — all core tables
- `0002_phase7_auto_updater.py` — update_records, weekly_reviews
- `0003_phase8_analytics.py` — audit_logs enhancements
- `0004_fix_audit_logs_and_data_sources.py` — column fixes

### ChromaDB collections

All collections use HNSW with cosine distance (`metadata={"hnsw:space": "cosine"}`).

| Collection | Embedding backend | Dimension | Purpose |
|------------|-------------------|-----------|---------|
| `code_chunks` | Gemini embedding-001 | 3072 | Code chunks — online mode |
| `doc_chunks` | Gemini embedding-001 | 3072 | Documentation chunks — online mode |
| `code_chunks_local` | BAAI/bge-base-en-v1.5 | 768 | Code chunks — offline mode |
| `doc_chunks_local` | BAAI/bge-base-en-v1.5 | 768 | Documentation chunks — offline mode |
| `query_cache` | Gemini embedding-001 | 3072 | Semantic query cache |

**Chunk metadata fields** (stored alongside each vector):
```python
{
    "chunk_id":          str,   # SHA-256[:32] of content
    "repo":              str,   # "owner/repo" or local path label
    "file_path":         str,   # relative file path
    "symbol_name":       str,   # function/class name (code chunks)
    "chunk_type":        str,   # "function" | "class" | "line_block"
    "line_start":        int,
    "line_end":          int,
    "source_type":       str,   # "code" | "documentation" | "notion"
    "page_title":        str,   # Notion page title (if applicable)
    "last_modified":     str,   # ISO timestamp
    "embedding_backend": str,   # "gemini" | "local_bge"
}
```

---

## 5. Backend Structure

```
backend/
├── arcana/
│   ├── main.py                  # FastAPI app, lifespan hooks, router mounts
│   ├── config.py                # Pydantic Settings, .env loading
│   ├── vector_store.py          # ChromaDB singleton + 5 collection accessors
│   ├── routers/
│   │   ├── health.py            # GET /health/
│   │   ├── query.py             # POST /query/  (SSE)
│   │   ├── ingest.py            # POST /ingest/github|notion|local
│   │   └── settings.py          # GET|POST /settings/
│   └── services/
│       ├── query_service.py     # RAG pipeline orchestrator
│       ├── retrieval.py         # Vector search (online + offline)
│       ├── embedder.py          # Gemini embeddings (online)
│       ├── local_embedder.py    # BGE embeddings (offline)
│       ├── gemini_client.py     # Gemini streaming
│       ├── local_llm_client.py  # Ollama streaming
│       ├── ingestion.py         # GitHub + Notion + local ingest
│       ├── chunker.py           # Code/doc/PDF/DOCX chunking
│       ├── traversal.py         # File tree walk with ignore rules
│       ├── context_assembler.py # Token budget, dedup, priority sort
│       ├── prompt_builder.py    # System prompts + source block formatting
│       ├── settings_store.py    # Persistent JSON settings
│       ├── github_service.py    # PyGithub wrapper
│       ├── notion_service.py    # Notion API client
│       ├── notion_extractor.py  # Notion block → text extraction
│       ├── notion_chunker.py    # Notion heading-based splitting
│       └── local_service.py     # File mtime helper
├── migrations/
│   ├── alembic.ini
│   ├── env.py
│   └── versions/0001–0004
├── tests/
│   ├── test_settings.py
│   ├── test_query_routing.py
│   ├── test_retrieval.py
│   ├── test_embedder_tagging.py
│   ├── test_local_embedder.py
│   └── test_ingest_mode_guard.py
├── pyproject.toml
├── Dockerfile
├── .env.example
└── .env.test
```

### Startup sequence (`main.py` lifespan)

1. `get_{code,doc,code_local,doc_local}_collection()` — ensures all 4 ChromaDB collections exist.
2. `asyncio.create_task(_auto_ingest())` — if `GITHUB_REPOS`/`NOTION_PAGE_IDS` are set **and** the KB is empty, runs a full ingest in the background. Server is ready immediately.
3. `asyncio.create_task(_prewarm_local_model())` — loads BAAI/bge-base-en-v1.5 into memory in the background so offline queries don't stall on first use.

### API endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health/` | None | Returns `{status, online_mode, ollama_available, embedding_model_ready, code_chunks, doc_chunks}` |
| `POST` | `/query/` | None | SSE stream. Body: `{question: str, history?: [{role, content}]}` |
| `GET` | `/settings/` | None | Returns `{online_mode: bool}` |
| `POST` | `/settings/` | None | Body: `{online_mode: bool}`. Persists to `settings.json`. |
| `POST` | `/ingest/` | None | Trigger GitHub + Notion ingest (background). 503 in offline mode. |
| `POST` | `/ingest/github` | None | GitHub only (background). 503 in offline mode. |
| `POST` | `/ingest/notion` | None | Notion only (background). 503 in offline mode. |
| `POST` | `/ingest/local` | None | Local directory ingest (synchronous). Always available. Body: `{paths: [str]}` |

The browser UI is served as static files mounted at `/` from the `ui/` directory.

---

## 6. RAG Pipeline

`query_service.run_query_stream()` is an async generator that yields SSE event dicts.

### Event schema

```python
{"event": "chunk", "data": {"text": "..."}}   # partial LLM output
{"event": "done",  "data": {"chunks_used": N}} # final event
{"event": "error", "data": {"message": "..."}} # on failure
```

### 15-step data flow — single user question to streamed response

```
 1. User types a question in the Browser UI (ui/index.html) or Electron overlay
    (electron/main.js). Both surfaces share the same HTML/JS front-end.

 2. UI opens an SSE fetch stream → POST /query/ with body {question, history[]}.
    An AbortController enforces a hard timeout (60 s).

 3. FastAPI routes the request to query_service.run_query_stream()
    (backend/arcana/routers/query.py).

 4. Identity short-circuit: if the question matches "who are you / what are you /
    what can you do", yield a hardcoded _IDENTITY_RESPONSE and stop.

 5. Read online_mode from backend/data/settings.json via settings_store.get_online_mode().
    All subsequent steps fork on this flag.

 6. Embed the question:
    • Online  → embedder.embed_query()       — Gemini embedding-001, task=RETRIEVAL_QUERY → 3072-dim
    • Offline → local_embedder.embed_query_local() — BGE with query prefix → 768-dim

 7. Vector search in ChromaDB (backend/arcana/services/retrieval.py):
    • Online  → vector_search()         — queries code_chunks + doc_chunks (cosine, n=15)
    • Offline → vector_search_offline() — queries code_chunks_local + doc_chunks_local

 8. Score threshold filter: discard any chunk with cosine similarity < 0.3.
    Sort remaining chunks by score descending.

 9. KB hit check:
    • No chunks above threshold → stream_fallback() — LLM answers from general knowledge,
      no [SOURCE N] blocks, prepend "⚠ No relevant information found" notice.
    • Chunks found → continue to step 10.

10. Context assembly (backend/arcana/services/context_assembler.py):
    deduplicate by (file_path, page_title) → priority-sort (architectural_overview →
    documentation/notion → code) → greedy token fill (budget: 6 000 online / 3 500 offline).

11. Prompt construction (backend/arcana/services/prompt_builder.py):
    wrap each selected chunk in [SOURCE N | origin: … | repo: … | file: …] blocks,
    combine with the appropriate system prompt (online vs. offline) and conversation history.

12. Stream LLM response:
    • Online  → gemini_client.stream_response()    — Gemini generate_content_stream, T=0.2
    • Offline → local_llm_client.stream_response() — Ollama /v1/chat/completions,
                                                       keep_alive=300 s, num_ctx=4096

13. Yield SSE chunk events as they arrive → {event: "chunk", data: {text: "…"}}.

14. Yield final SSE done event → {event: "done", data: {chunks_used: N}}.

15. UI appends streamed text to the chat bubble via marked.js; on the "done" event
    Mermaid re-renders any diagram fences in the completed response.
```

### Full pipeline (step by step)

```
User question
    │
    ▼
Step 0: Identity check
    ├─ matches any of: "who are you", "what are you", "what can you do", ...
    └─ Yes → yield hardcoded _IDENTITY_RESPONSE, done

    ▼
Step 1: Read online_mode from settings.json

    ┌─── ONLINE (online_mode = True) ───────────────────────────────────────┐
    │                                                                       │
    │  Step 2: embed question                                               │
    │    services/embedder.py :: embed_query(question)                     │
    │    → Gemini embedding-001 with task_type=RETRIEVAL_QUERY             │
    │    → returns 3072-dim float list                                     │
    │                                                                       │
    │  Step 3: vector search                                                │
    │    services/retrieval.py :: vector_search(question)                  │
    │    → query code_chunks + doc_chunks (cosine, n_results=15)           │
    │    → filter score ≥ 0.3, sort descending, return top-15             │
    │                                                                       │
    │  Step 4a (KB miss): no chunks above threshold                        │
    │    → prepend "⚠️ No relevant information found..." notice            │
    │    → stream_fallback(question) directly from Gemini                  │
    │                                                                       │
    │  Step 4b (KB hit):                                                    │
    │    assemble_context(chunks, token_budget=6000)                        │
    │    build_prompt(question, chunks, offline=False)                     │
    │    → online system prompt                                            │
    │    stream_response(prompt_pkg) from Gemini                           │
    └───────────────────────────────────────────────────────────────────────┘

    ┌─── OFFLINE (online_mode = False) ─────────────────────────────────────┐
    │                                                                       │
    │  Step 2: embed question                                               │
    │    services/local_embedder.py :: embed_query_local(question)         │
    │    → prepend BGE prefix, encode with SentenceTransformer             │
    │    → returns 768-dim float list                                      │
    │                                                                       │
    │  Step 3: vector search                                                │
    │    services/retrieval.py :: vector_search_offline(question)          │
    │    → query code_chunks_local + doc_chunks_local (cosine, n=15)       │
    │    → filter score ≥ 0.3, sort descending, return top-15             │
    │                                                                       │
    │  Step 4a (KB miss):                                                   │
    │    → prepend notice                                                  │
    │    → local_stream_fallback(question, model=qwen2.5:3b)               │
    │                                                                       │
    │  Step 4b (KB hit):                                                    │
    │    assemble_context(chunks, token_budget=3500)  ← smaller budget     │
    │    build_prompt(question, chunks, offline=True)                      │
    │    → offline system prompt (simpler, step-by-step for small models)  │
    │    local_stream_response(prompt_pkg, model=qwen2.5:3b)               │
    └───────────────────────────────────────────────────────────────────────┘

    ▼
Step 5: Yield {"event": "done", "data": {"chunks_used": N}}
```

---

## 7. Ingestion Pipeline

### Source types

| Source | Endpoint | Mode restriction | Strategy |
|--------|----------|-----------------|---------|
| GitHub repo | `POST /ingest/github` | Online only | Clone via PyGithub, diff by commit timestamp |
| Notion workspace | `POST /ingest/notion` | Online only | Traverse page tree, diff by `last_edited_time` |
| Local directory | `POST /ingest/local` | Always | Scan filesystem, diff by file `mtime` |

All three paths produce `Chunk` objects which are passed to `store_chunks()` (online) or `store_chunks_local()` (offline).

### Chunker (`services/chunker.py`)

| File type | Strategy | Details |
|-----------|----------|---------|
| `.py` | Tree-sitter AST | Function and class boundaries; imports extracted |
| `.js` / `.ts` / `.tsx` / `.jsx` | Tree-sitter AST | Same AST approach |
| Other code (`.go`, `.rs`, `.java`, etc.) | Line-block fallback | 100-line windows, 10-line overlap, min 5 lines |
| `.md` / `.mdx` / `.rst` | Heading split | Each H1/H2/H3 section becomes a chunk |
| `.yaml` / `.yml` / `.toml` / `.json` | Whole file or top-level key split | |
| `.pdf` | pypdf extraction | Line-based chunks |
| `.docx` | python-docx extraction | Paragraph-based chunks |

Each chunk gets a **deterministic SHA-256 ID** derived from its content, allowing idempotent upserts.

### File traversal (`services/traversal.py`)

- Skips: `node_modules/`, `.venv/`, `dist/`, `build/`, `.git/`, `__pycache__/`, etc.
- Respects `.codemindignore` files (same syntax as `.gitignore`).
- Max file size: **500 KB**.
- Supported extensions: `.py`, `.js`, `.ts`, `.tsx`, `.jsx`, `.go`, `.rs`, `.java`, `.rb`, `.php`, `.c`, `.cpp`, `.h`, `.md`, `.mdx`, `.rst`, `.txt`, `.yaml`, `.yml`, `.toml`, `.json`, `.pdf`, `.docx`

### Diff strategy

All ingest paths are **incremental by default**:
- GitHub: compares file timestamps against last ingestion record; skips unchanged files, deletes stale chunks.
- Notion: compares `last_edited_time` against stored value; re-chunks modified pages only.
- Local: compares file `mtime`; re-chunks changed files only.

The `/ingest/local` endpoint is **synchronous** and returns immediately with `{embedded: N, skipped: N}`.

---

## 8. Embedding Strategy

### Why two separate embedding spaces

ChromaDB enforces a single vector dimension per collection. Gemini embedding-001 produces **3072-dim** vectors; BGE bge-base-en-v1.5 produces **768-dim** vectors. Cross-space cosine similarity scores are meaningless, so Arcana uses **four separate collections** — one pair per backend.

### Online: Gemini embedding-001

- **Dimension:** 3072
- **Collections:** `code_chunks`, `doc_chunks`
- **Task types:** `RETRIEVAL_DOCUMENT` (at ingest), `RETRIEVAL_QUERY` (at query time)
- **Batch size:** 20 texts per API call
- **Backend tag:** `embedding_backend = "gemini"` stored in chunk metadata

### Offline: BAAI/bge-base-en-v1.5

- **Dimension:** 768
- **Collections:** `code_chunks_local`, `doc_chunks_local`
- **Asymmetric retrieval:** Documents are embedded as-is. Queries prepend the BGE instruction prefix:
  ```
  "Represent this sentence for searching relevant passages: "
  ```
  This mirrors Gemini's `RETRIEVAL_QUERY` task type by projecting the query into a "searching" sub-space.
- **Model size:** ~440 MB (downloads once to `~/.cache/torch/sentence_transformers/`)
- **Loading:** lazy-loaded on first call via `@lru_cache(maxsize=1)`, stays resident in memory for the session
- **Batch size:** 64 (sentence-transformers handles batches efficiently)
- **CPU execution:** runs in `asyncio.get_running_loop().run_in_executor(None, ...)` to avoid blocking the event loop
- **Backend tag:** `embedding_backend = "local_bge"` stored in chunk metadata

---

## 9. LLM Integration

### Online: Gemini (`services/gemini_client.py`)

- **Library:** `google-genai >= 1.0.0` (migrated from deprecated `google-generativeai`)
- **Model:** configured via `GEMINI_MODEL` (default: `gemini-2.5-flash-lite`)
- **Streaming:** `client.models.generate_content_stream(...)`
- **Temperature:** `0.2`; max output tokens: `2000`
- **Error handling:** `GeminiConfigError` for missing API key; `__ERROR__:` prefix sentinel for inline errors propagated to SSE

### Offline: Ollama (`services/local_llm_client.py`)

- **Endpoint:** `{OLLAMA_BASE_URL}/v1/chat/completions` (OpenAI-compatible)
- **Model:** `OLLAMA_FAST_MODEL` (default: `qwen2.5:3b`, ~2.2 GB)
- **Streaming:** `httpx.AsyncClient.stream("POST", ...)`, parses SSE `data:` lines
- **Key parameters:**
  - `keep_alive: 300` — model stays loaded in RAM for 5 minutes between queries, eliminating cold-start latency on back-to-back requests
  - `options.num_ctx: 4096` — context window
  - `options.num_predict: 512` — max output tokens
- **Timeouts:** `connect=5s`, `read=65s`, `write=10s`
- **Error handling:** `OllamaError` raised on connection failure (e.g. Ollama not running)

### System prompts (`services/prompt_builder.py`)

**Online prompt** (`_SYSTEM_PROMPT`): Instructions to answer using only provided sources, cite as `[Notion (N)]` / `[GitHub (N)]`, include file paths and line numbers, use code blocks, generate Mermaid diagrams when architecturally relevant.

**Offline prompt** (`_OFFLINE_SYSTEM_PROMPT`): Simplified sequential instructions ("Step 1: read sources, Step 2: answer, Step 3: cite as [SOURCE N]...") tuned for smaller models that follow explicit steps more reliably than abstract rule sets.

### Source block format

Each chunk is formatted as:
```
[SOURCE N | origin: GitHub | repo: owner/repo | file: path/to/file.py | symbol: MyClass.method]
<chunk content>
[END SOURCE N]
```
or for Notion:
```
[SOURCE N | origin: Notion | page: Page Title]
<chunk content>
[END SOURCE N]
```

---

## 10. Context Assembly

`services/context_assembler.py :: assemble_context(chunks, token_budget, user_team)`

### Steps

1. **Deduplicate** — chunks sharing the same `(file_path, page_title)` key: keep the one with the higher score.
2. **Team bias** — if `user_team` matches a repo name or page title, add a `+0.005` score bump as a soft tiebreaker.
3. **Sort** — by source priority then score descending:
   - Priority 0: `architectural_overview`
   - Priority 1: `documentation` / `notion`
   - Priority 2: `code`
4. **Architectural reserve** — architectural overview chunks fill first, up to `min(500, budget/5)` tokens.
5. **Greedy fill** — remaining chunks fill the rest of the budget. Chunks that don't fit entirely are truncated at paragraph/code-block boundaries to avoid mid-block cuts.
6. **Format** — each selected chunk wrapped in `[SOURCE N | ...]` blocks (1-indexed).

**Token counting:** `tiktoken` with `cl100k_base` encoding.

**Token budgets:**
- Online path: `CONTEXT_TOKEN_BUDGET` (default 6000)
- Offline path: hard-coded 3500 (matched to `num_ctx=4096` minus prompt overhead)

---

## 11. Frontend Surfaces

### Browser UI (`ui/index.html`)

Single-page app, zero build tooling.

- **Rendering:** vanilla JavaScript, `marked.js` for Markdown, `mermaid` for diagrams
- **Query flow:** `fetch` with `ReadableStream` consuming SSE events
- **Abort:** `AbortController` with a 60-second hard timeout
- **Mode toggle:** Online (blue theme `theme-online`) / Offline (amber theme `theme-offline`)
- **Countdown timer:**
  - "Setting up local environment…" — shown while `embedding_model_ready = false` (polls `/health/` every 2s)
  - "Thinking — ~Ns remaining" — countdown (15s online, 45s offline)
  - "Streaming…" — transitions on first SSE chunk received
  - "Done — {source} | {N} exchanges · {t}s" — on `done` event
- **Ingest bar:** GitHub, Notion (disabled in offline mode), Local (always enabled)
- **Conversation history:** up to 10 prior `{role, content}` pairs sent with each query

### Electron Overlay (`electron/main.js`)

macOS menu-bar application.

- **Window:** hidden from Dock, 680×520px, always-on-top, floats above fullscreen apps
- **Global hotkey:** `Ctrl+Alt+Space` via `uiohook-napi`
- **Tray menu:** "Update GitHub", "Update Notion", "Update Local", "Show Overlay", "Quit"
- **IPC:** `ipcMain.handle('pick-directory', ...)` exposes native directory picker dialog to the renderer
- **Backend assumption:** expects FastAPI running at `http://localhost:8000`

---

## 12. Testing

**Framework:** pytest + pytest-asyncio (mode: `auto`)

**Test files:**

| File | What it tests |
|------|---------------|
| `test_settings.py` | Settings store: read/write, API endpoints, persistence across restarts |
| `test_query_routing.py` | `online_mode=True` routes to Gemini; `online_mode=False` routes to Ollama |
| `test_retrieval.py` | Vector search: score threshold filtering, top-k limit, empty collection handling |
| `test_embedder_tagging.py` | Gemini-embedded chunks tagged `embedding_backend="gemini"` |
| `test_local_embedder.py` | BGE model loading, BGE query prefix prepending, 768-dim output shape |
| `test_ingest_mode_guard.py` | `POST /ingest/github` and `/ingest/notion` return 503 in offline mode; `/ingest/local` always accepts |

**Run:**
```bash
cd backend
source .venv/bin/activate
python -m pytest tests/ -q
```

**Test configuration** (`pyproject.toml`):
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

Test-specific env overrides are in `backend/.env.test`.

---

## 13. CI/CD

**File:** `.github/workflows/ci.yml`

- **Trigger:** push / pull_request to `main`
- **Matrix:** Python 3.11, Python 3.12, Ubuntu latest
- **Steps:**
  1. Checkout
  2. Set up Python
  3. `pip install -e ".[dev]"`
  4. `ruff check .` (linting)
  5. `black --check .` (formatting)
  6. `pytest tests/ -q` (working directory: `backend/`)

---

## 14. Reproduction Guide

### Prerequisites

- Python 3.11+
- Git
- (Optional, for offline mode) [Ollama](https://ollama.ai) installed

### Step 1 — Clone and set up the backend

```bash
git clone <repo-url>
cd ig-arcana-simple/backend

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
```

### Step 2 — Configure environment

```bash
cp .env.example .env
```

Edit `.env` with at minimum:
```
GEMINI_API_KEY=your_api_key_here
APP_SECRET_KEY=<output of: python -c "import secrets; print(secrets.token_urlsafe(32))">
```

For GitHub ingestion also add `GITHUB_PAT` and `GITHUB_REPOS`.  
For Notion ingestion also add `NOTION_TOKEN` and `NOTION_PAGE_IDS`.

### Step 3 — Initialize the database

```bash
# From backend/ with .venv active
alembic upgrade head
```

This creates `backend/data/arcana.db` with all 6 tables.

### Step 4 — (Optional) Set up offline mode

```bash
# Install Ollama
brew install ollama          # macOS
# or download from https://ollama.ai for other platforms

# Pull the offline model (~2.2 GB)
ollama pull qwen2.5:3b

# Start Ollama (keep this running in a separate terminal)
ollama serve
```

The BGE embedding model (~440 MB) downloads automatically on first offline query (or on server startup via the pre-warm hook).

### Step 5 — Start the backend

```bash
# From repo root
make run          # production mode
# or
make dev          # hot-reload (uvicorn --reload)
```

Equivalent manual command:
```bash
cd backend
uvicorn arcana.main:app --host 0.0.0.0 --port 8000 --reload
```

### Step 6 — Open the UI

Navigate to [http://localhost:8000](http://localhost:8000).

### Step 7 — Ingest your knowledge base

**Via UI:** Click the GitHub / Notion / Local button in the ingest bar.

**Via API:**
```bash
# GitHub
curl -X POST http://localhost:8000/ingest/github

# Notion
curl -X POST http://localhost:8000/ingest/notion

# Local directory
curl -X POST http://localhost:8000/ingest/local \
  -H "Content-Type: application/json" \
  -d '{"paths": ["/path/to/your/code"]}'
```

### Step 8 — (Optional) Run the Electron overlay

```bash
cd electron
npm install
npm start
```

Use `Ctrl+Alt+Space` to toggle the floating overlay window.

### Step 9 — Run the test suite

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/ -v
```

### Docker alternative

```bash
# From repo root
docker-compose up
```

The `api` service builds from `backend/Dockerfile`, mounts `./data` for persistence, and reads `backend/.env`.

---

## 15. Known Constraints

**Embedding space separation:** Chunks ingested in online mode (Gemini, 3072-dim) are stored in `code_chunks` / `doc_chunks`. Chunks ingested in offline mode (BGE, 768-dim) are stored in `code_chunks_local` / `doc_chunks_local`. The two embedding spaces are **never mixed** — a query in offline mode will not find chunks ingested in online mode, and vice versa. If you switch modes, re-ingest via `POST /ingest/local` to populate the correct collections.

**Single offline model:** The offline path is locked to `qwen2.5:3b` (configured via `OLLAMA_FAST_MODEL`). There is no model selector in the current UI.

**Ollama must run separately:** Arcana does not start or manage the Ollama process. `ollama serve` must be running independently for offline mode to work. The health endpoint (`GET /health/`) reports `ollama_available: false` when it cannot reach Ollama.

**No authentication on API:** All endpoints are unauthenticated. The RBAC schema (users, permissions) is present in the database but not enforced in the current query/ingest flow. Intended for internal team deployment behind a network boundary.

**Local ingestion token budget:** The offline path uses a 3500-token context budget (vs. 6000 online) to fit within Ollama's `num_ctx=4096` constraint. Fewer chunks will be included in offline answers for the same query.

**BGE model cold start:** On first offline query after server restart, if pre-warming did not complete, the BGE model may need 30–60 seconds to load from disk. The UI polls `/health/` every 2 seconds and shows a spinner with a countdown until `embedding_model_ready: true`.
