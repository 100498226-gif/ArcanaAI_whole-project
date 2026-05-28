# Arcana

> **Quick-start instructions are at the top. Everything below the horizontal rule is legacy documentation from the original complex system and no longer reflects the current codebase.**

---

## How to use Arcana

### Prerequisites

- Python 3.9+
- Node.js 18+
- [Gemini API key](https://aistudio.google.com/apikey) — required for online mode
- GitHub Personal Access Token (PAT) — required for GitHub ingestion
- Notion integration token — required for Notion ingestion
- [Ollama](https://ollama.com) — required for offline mode

### 1. First-time setup

```bash
git clone https://github.com/100498226-gif/ig-arcana-personal.git
cd ig-arcana-personal

make setup          # creates backend/.venv and installs Python dependencies
make setup-overlay  # installs Electron dependencies
```

### 2. Configure credentials

Edit `backend/.env`:

```env
GEMINI_API_KEY=your_gemini_key
GITHUB_PAT=your_github_pat
GITHUB_REPOS=owner/repo1,owner/repo2
NOTION_TOKEN=your_notion_token
NOTION_PAGE_IDS=your_page_id_here
```

> **Notion**: share the page with your Notion integration first (open the page → ··· → Connections → add your integration).
>
> **GitHub repos**: use the `owner/repo` format (e.g. `acme/backend-api`).

### 3. Install local models (one-time, requires internet)

Ollama manages the local models used in offline mode. Install it and pull both models while online — this only needs to happen once; models persist on disk.

```bash
# Install Ollama (if not already installed)
brew install ollama

# Pull the two offline models (~2.2 GB + ~9.1 GB)
ollama pull qwen2.5:3b   # Fast Mode
ollama pull phi4          # Think Mode
```

> **Fast Mode (`qwen2.5:3b`)** — 2.2 GB, cold-starts in ~5–8 s on CPU. Optimised for quick answers over code and docs.
>
> **Think Mode (`phi4`)** — 9.1 GB, Microsoft Phi-4 14B. Best-in-class reasoning for complex technical questions. Requires ~12 GB RAM during a query (loads fully, then unloads when done).

### 4. Run

Open **three** terminals from the project root:

```bash
# Terminal 1 — Ollama (keep running; needed for offline mode)
ollama serve

# Terminal 2 — backend
make dev
# or: make run  (with hot-reload for .py changes)

# Terminal 3 — Electron overlay
make overlay
```

> Ollama is only required for offline mode. If you only use online mode (Gemini), two terminals are enough — the app will work normally and simply report Ollama as unavailable.

The backend starts on `http://localhost:8000`.

### 5. Ask questions

**Overlay (recommended):** Press `Ctrl+Alt+Space` anywhere on your Mac → type your question → `Enter` to submit → `Esc` to dismiss.

**Browser UI:** Open `http://localhost:8000` in any browser.

### 6. Online / Offline mode

The mode toggle appears in both the Electron overlay and the browser UI.

| Mode | Theme | LLM | Embedder | Ingestion |
|---|---|---|---|---|
| **Online** | Bright blue | Gemini | Gemini | GitHub + Notion + Local |
| **Offline** | Dark amber | Ollama (local) | sentence-transformers | Local files only |

- Toggle persists across restarts — the setting is saved in `backend/data/settings.json`.
- Your knowledge base (ChromaDB) is accessible in both modes. Chunks embedded online can be searched offline, and vice versa.
- In offline mode, the **Fast** / **Think** pill selector appears — switch between `qwen2.5:3b` and `phi4` at any time.
- GitHub and Notion ingest buttons are automatically disabled in offline mode.

### 7. Ingest knowledge

Click the ingest buttons only when you want to add or refresh content — nothing is re-indexed automatically on startup.

- **⬡ GitHub** — indexes configured repos (online mode only)
- **◈ Notion** — indexes configured pages (online mode only)
- **Local** — indexes files you drop in; works in both modes

Only changed or new files are re-embedded. Unchanged content is skipped. The knowledge base is additive — ingesting again never wipes existing chunks.

### Makefile commands

| Command | Description |
|---|---|
| `make dev` | Start backend without hot-reload (recommended) |
| `make run` | Start backend with hot-reload |
| `make overlay` | Launch the Electron menu bar overlay |
| `make setup` | Install Python dependencies |
| `make setup-overlay` | Install Electron dependencies (first time only) |
| `make clean` | Wipe ChromaDB data (forces full re-index on next start) |

---

## Legacy documentation

**AI-powered developer onboarding platform that turns your codebase and institutional knowledge into a conversational, self-updating knowledge base — delivered where developers already work.**

---

## The problem

Every new developer at a scaling tech company spends 2 to 6 weeks unproductive while learning the codebase, tools, and infrastructure. During this period, they constantly pull senior engineers away from their own work to ask context questions. The result is a compounding cost: the new hire isn't delivering value, and the people helping them aren't either.

## What Arcana does

Arcana connects to your GitHub repositories and Notion documentation, builds a rich knowledge base with RBAC-scoped access control, and answers developer questions through Cursor and the terminal — with specific file references, line numbers, and documentation links.

The system maintains itself through daily auto-updates that detect codebase and documentation changes, with weekly admin review to course-correct when needed. An analytics layer provides real-time visibility into usage, coverage gaps, and onboarding progress.

---

## Architecture

Arcana is a backend-first system with thin client surfaces. All intelligence lives in the FastAPI backend; the Cursor extension and CLI are rendering layers.

```
Data Sources          Knowledge Store          Query Pipeline           Clients
┌──────────┐         ┌──────────────┐         ┌────────────────┐      ┌─────────┐
│  GitHub   │───┐     │  ChromaDB    │    ┌───▶│ Hybrid search  │      │ Cursor  │
│  Notion   │───┤     │  (vectors)   │    │    │ Re-rank        │      │ CLI     │
│  Linear*  │   ├────▶│              │────┤    │ Context assem. │─────▶│ Admin   │
│  Slack*   │   │     │  SQLite      │    │    │ Gemini + cite  │      │ panel   │
└──────────┘   │     │  (metadata)  │    │    │ Semantic cache │      └─────────┘
               │     │              │    │    └────────────────┘
               │     │  FTS5        │────┘
               │     │  (keywords)  │
               │     └──────────────┘
               │            │
               │     ┌──────┴───────┐
               └────▶│ RBAC filter  │
                     └──────────────┘

* Linear and Slack are designed for but not yet implemented
```

For the full component-to-file mapping, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Monorepo structure

```
arcana/
├── backend/                  # FastAPI application (Python)
│   ├── arcana/               # Main package
│   │   ├── main.py           # App factory, middleware, router mounting
│   │   ├── config.py         # Pydantic settings, env var loading
│   │   ├── database.py       # SQLAlchemy engine, session factory
│   │   ├── vector_store.py   # ChromaDB wrapper
│   │   ├── models/           # ORM models (users, sources, audit, permissions, updates)
│   │   ├── schemas/          # Pydantic request/response schemas
│   │   ├── routers/          # API endpoints (health, admin, query, analytics, updater)
│   │   ├── services/         # All business logic (retrieval, ingestion, updater, analytics, cache, permissions)
│   │   ├── middleware/       # Auth, logging, CORS, error handling
│   │   └── scripts/          # DB seed, FTS5 backfill
│   ├── migrations/           # Alembic database migrations
│   ├── tests/                # pytest test suite
│   ├── .env.example          # Environment variable template
│   ├── .env.test             # Test environment overrides
│   └── pyproject.toml        # Python package config
│
├── cli/                      # Command-line interface (Python)
│   ├── arcana_cli/
│   │   ├── main.py           # Typer app, command registration
│   │   ├── commands/         # ask, users, sources, cache, audit, updater, dashboard, demo, eval, config
│   │   ├── api/              # HTTP + SSE client
│   │   └── rendering/        # Rich markdown, citations, code blocks, components
│   └── pyproject.toml
│
├── cursor/                   # Cursor editor extension (TypeScript)
│   ├── src/
│   │   ├── extension.ts      # Entry point, command registration
│   │   ├── sidebar/          # Webview provider
│   │   ├── api/              # Backend API client
│   │   ├── editor/           # File navigation, line jumping
│   │   └── context/          # Active file tracking
│   ├── webview/              # Sidebar HTML/CSS/JS
│   └── package.json          # Extension manifest
│
├── admin/                    # Streamlit admin panel (Python)
│   ├── app.py                # Entry point + auth redirect
│   ├── pages/                # Overview, users, sources, analytics, audit, review, cache
│   ├── api_client.py         # Shared HTTP client
│   ├── auth.py               # Login flow, session management
│   ├── config.py             # Environment configuration
│   ├── utils.py              # Shared formatting helpers
│   ├── tests/                # Admin panel test suite (29 tests)
│   └── requirements.txt
│
├── docs/                     # Documentation
│   ├── prds/                 # Product requirement documents (Phases 1-9 + toolkit)
│   ├── sessions/             # Development session logs
│   ├── ARCHITECTURE.md       # Component-to-code mapping + data flow trace
│   └── LIMITATIONS.md
│
├── CONTEXT.md                # Agent briefing file (hook system)
├── AGENTS.md                 # AI agent interaction guidelines
├── README.md                 # This file
├── Makefile                  # Developer shortcuts
├── docker-compose.yml        # Local development (backend + admin panel)
└── .gitignore
```

---

## Quick start

### Prerequisites

- Python 3.11+
- Node.js 18+ (for Cursor extension)
- A Gemini API key ([get one here](https://aistudio.google.com/apikey))
- A GitHub Personal Access Token (for the repo you want to index)
- A Notion integration token (for the workspace you want to index)

### 1. Clone and set up the backend

```bash
git clone https://github.com/your-org/arcana.git
cd arcana
make setup    # Installs deps, creates .env from template, initializes databases
```

Edit `backend/.env` with your API keys:

```env
GEMINI_API_KEY=your_gemini_key
GITHUB_PAT=ghp_your_github_token
NOTION_TOKEN=ntn_your_notion_token
APP_SECRET_KEY=generate_a_random_string_here
```

### 2. Start the backend

```bash
make run      # Starts FastAPI on http://localhost:8000
```

### 3. Create an admin user and connect sources

```bash
make seed     # Creates default admin, prints API key

# Set your API key for CLI
arcana config set-key arc_k1_your_admin_key

# Connect and sync sources via admin endpoints or CLI
arcana sources sync <source_id>
```

### 4. Install the Cursor extension

```bash
cd cursor
npm install
npm run build
# Install the generated .vsix file in Cursor:
# Cursor → Extensions → ... → Install from VSIX
```

Configure in Cursor settings:
- `arcana.apiKey`: your API key
- `arcana.serverUrl`: `http://localhost:8000`

### 5. Ask a question

In Cursor's Arcana sidebar:
```
How does the authentication middleware work?
```

Or via CLI:
```bash
arcana ask "How does the authentication middleware work?"
```

### 6. (Optional) Start the admin panel

```bash
make run-admin    # Starts Streamlit on http://localhost:8501
```

---

## Demo mode

Demo mode provides an isolated environment with pre-populated synthetic data for thesis presentations — without touching the production knowledge base.

**Activate:**
```bash
export ARCANA_DEMO_MODE=true
make demo-seed    # Seeds 6 users, 3 sources, ~160 chunks, 1000 audit events, 20 cache entries
```

**Demo API keys** (deterministic, no lookup needed):

| User | Key |
|---|---|
| admin@demo.arcana | `arc_demo_admin_arcana` |
| sarah@demo.arcana | `arc_demo_dev_sarah` |
| james@demo.arcana | `arc_demo_dev_james` |
| viewer@demo.arcana | `arc_demo_viewer_demo` |

**Demo queries** (demonstrating RBAC — Sarah and James get different results):
```bash
arcana ask "how does auth work?" --api-key arc_demo_dev_sarah
arcana ask "how does auth work?" --api-key arc_demo_dev_james

arcana demo status    # Shows user count, chunks, audit events, cache stats
```

**Visual indicators** — all three surfaces show an orange "DEMO MODE" banner/badge when `ARCANA_DEMO_MODE=true`.

**Reset:** `make demo-reset` wipes `data/demo.db` + `data/demo_chromadb/` and re-seeds.

**Rehearsal mode:** Set `DEMO_MOCK_LLM=true` to return pre-computed responses without calling Gemini (skips API costs during rehearsal).

---

## Retrieval evaluation

A repeatable benchmark that measures how well the retrieval pipeline finds the right chunks for 20 representative developer queries.

```bash
arcana eval run                                             # All 20 queries, overall metrics
arcana eval run --category semantic --verbose              # Per-query breakdown
arcana eval run --search-mode vector-only                  # Ablation: vector only
arcana eval run --search-mode bm25-only                    # Ablation: BM25 only
arcana eval run --output thesis_results.csv                # Export for thesis tables
```

**Metrics reported:** Precision@5, Precision@10, Recall@10, Recall@20, MRR, Hit Rate@5 — broken down by category (semantic, exact_match, multi_source, role_scoped) and difficulty.

The gold standard dataset is at `backend/arcana/eval/gold_standard.json` (20 queries with manually curated ideal chunk IDs).

---

## Makefile commands

| Command | Description |
|---|---|
| `make setup` | Install all dependencies, create .env, initialize databases |
| `make run` | Start FastAPI backend (port 8000) |
| `make run-admin` | Start Streamlit admin panel (port 8501) |
| `make test` | Run full backend test suite |
| `make lint` | Run black + ruff + mypy |
| `make migrate` | Generate and apply Alembic migration |
| `make seed` | Create default admin user |
| `make demo-seed` | Populate demo database with synthetic data |
| `make demo-reset` | Wipe and re-seed the demo database |
| `make test-demo` | Run demo isolation tests |
| `make test-eval` | Run retrieval evaluation tests |
| `make docker-up` | Start all services via Docker Compose |
| `make clean` | Remove data/, __pycache__, .pytest_cache |

---

## Environment variables

### Required

| Variable | Description |
|---|---|
| `APP_SECRET_KEY` | Secret for hashing API keys |
| `GEMINI_API_KEY` | Gemini API key for LLM and embeddings |
| `GITHUB_PAT` | GitHub Personal Access Token |
| `NOTION_TOKEN` | Notion integration token |

### Optional (with defaults)

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | sqlite+aiosqlite:///./data/arcana.db | SQLAlchemy async connection string |
| `CHROMADB_PATH` | ./data/chromadb | ChromaDB persistence directory |
| `GEMINI_MODEL` | gemini-2.0-flash | Gemini model for generation |
| `EMBEDDING_MODEL` | models/text-embedding-004 | Embedding model |
| `LOG_LEVEL` | INFO | Logging level |
| `CACHE_ENABLED` | true | Toggle semantic cache |
| `CACHE_TTL_HOURS` | 24 | Cache entry TTL |
| `UPDATER_INTERVAL_HOURS` | 24 | Hours between auto-updates |
| `UPDATER_ENABLED` | true | Toggle daily auto-updater |
| `REVIEW_ALERT_DAY` | friday | Day for weekly review alert |
| `ARCANA_DEMO_MODE` | false | Enable demo mode (isolated `data/demo.db` + `data/demo_chromadb/`) |
| `DEMO_MOCK_LLM` | false | Return pre-computed responses instead of calling Gemini (rehearsal only) |
| `EVAL_TOP_K` | 20 | Maximum k for retrieval during evaluation |
| `EVAL_SKIP_LLM` | true | Skip LLM generation during eval (measures retrieval quality only) |

See `backend/.env.example` for the complete list.

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLAlchemy, Alembic |
| Vector store | ChromaDB (local, migrateable to Pinecone/Weaviate) |
| Keyword search | SQLite FTS5 (BM25) |
| LLM | Gemini APIs (google-genai) |
| Re-ranker | cross-encoder/ms-marco-MiniLM-L-6-v2 (local, swappable to Cohere) |
| Cursor extension | TypeScript, VS Code Extension API |
| CLI | Python, Typer, Rich |
| Admin panel | Streamlit, Plotly, Pandas |
| Ingestion | PyGithub, notion-client, tree-sitter |

---

## Development phases

| Phase | Name | Tier | Status |
|---|---|---|---|
| 1 | Project scaffold + database foundations | Tier 1 (MVP) | Complete |
| 2 | GitHub ingestion pipeline | Tier 1 | Complete |
| 3 | Notion ingestion pipeline | Tier 1 | Complete |
| 4 | RBAC + permission system | Tier 1 | Complete |
| 5 | AI orchestration + retrieval pipeline | Tier 1 | Complete |
| 6 | Cursor extension + CLI | Tier 1 | Complete |
| 7 | Auto-updater with weekly review | Tier 2 (stretch) | Complete |
| 8 | Analytics data layer + admin dashboards | Tier 2 | Complete |
| 9 | Internal admin panel (Streamlit) | Tier 2 | Complete |
| — | Thesis toolkit (demo, eval, architecture docs) | Cross-cutting | Complete |

PRDs are in [docs/prds/](docs/prds/). Limitations and design decisions are in [docs/LIMITATIONS.md](docs/LIMITATIONS.md) (50 entries with production paths).

---

## Testing

```bash
make test-backend                  # 277 backend tests (pytest)
make test-cli                      # 28 CLI tests
make test-extension                # 52 Cursor extension tests (Jest)
make test-admin                    # 29 admin panel tests
make test                          # Alias for make test-backend
pytest --cov=arcana --cov-report=html   # Coverage report (run from backend/)
```

---

## Documentation

| Document | Location | Description |
|---|---|---|
| Architecture mapping | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Component-to-file map + data flow trace |
| Limitations log | [docs/LIMITATIONS.md](docs/LIMITATIONS.md) | 50 documented tradeoffs with production paths |
| Phase PRDs | [docs/prds/](docs/prds/) | Detailed specs for all 9 phases + toolkit |
| Session logs | [docs/sessions/](docs/sessions/) | Development session notes |

---

## License

This project is developed as a thesis project at [University]. License terms TBD.

---

*Built by Ignacio — 2026*

## MVP Local Guide

This guide provides a quick-start for running a minimal MVP locally (Notion + GitHub) with an HTML UI. It assumes you want to test end-to-end in a local environment without pulling in the full production stack.

- Prerequisites: Python 3.11+, a Python venv is optional but recommended; a recent Node is not required for the HTML UI.
- Environment: copy backend/.env.example to backend/.env and fill in the required keys (GEMINI_API_KEY, GITHUB_PAT, NOTION_TOKEN, APP_SECRET_KEY).
- Flow: start the backend, then open the UI at a local URL.

Steps
- 1) Prepare .env for MVP
  - Go to backend
  - cp .env.example .env
  - Fill in GEMINI_API_KEY, GITHUB_PAT, NOTION_TOKEN, APP_SECRET_KEY
  - Set UPDATER_ENABLED=false, RBAC_ENABLED=false, ALLOWED_SOURCES=notion,github
- 2) Start the backend
  - cd backend
  - source <path-to-venv>/bin/activate (optional if you already have the venv active)
  - uvicorn arcana.main:app --reload --port 8000 --host 0.0.0.0
- 3) Open the UI
  - Open http://localhost:8000/ui/index.html
- 4) Validation tips
  - Use Notion and GitHub tokens in env vars; the UI talks to the backend which holds the credentials.
  - To stop: Ctrl+C

Notas
- Este MVP local es para validar la integración Notion/GitHub y la UI HTML. RBAC y updater están desactivados para evitar bloqueos durante las pruebas locales.
- Si quieres, más adelante te puedo proporcionar un script Makefile rápido o un script bash para automatizar estos pasos.
