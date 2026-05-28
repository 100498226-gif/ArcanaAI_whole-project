# Arcana — Getting Started Guide

A practical put-into-practice guide covering two scenarios:
1. **Running it locally** — to test, verify, and continue developing
2. **Integrating with a real company** — a production deployment for an actual team

---

## Part 1: Testing it yourself locally

This is the path for verifying everything works, continuing development, or demoing it.

### Step 1 — Prerequisites

You need these before anything else:

| Thing | Where to get it |
|---|---|
| Python 3.11+ | Already installed |
| Node.js 18+ | For the Cursor extension only |
| **Ollama** | https://ollama.com (for local LLM and vision models) |
| **Gemini API key** | https://aistudio.google.com/apikey (free tier works) |
| **GitHub PAT** | GitHub → Settings → Developer settings → Personal access tokens → Fine-grained. Needs `contents: read` on the repos you want to index. |
| **Notion token** | Notion → Settings → Connections → Develop or manage integrations. Then share the pages you want indexed with that integration. |

#### Ollama Models (Optional - for Offline Mode)

Arcana uses local Ollama models when running in offline mode:

```bash
# Pull the text model (for offline RAG mode)
ollama pull qwen2.5:3b
```

> **Note:** In offline mode, image analysis is disabled. Images will only get basic captions.
> In online mode, Gemini is used for detailed image analysis.

---

### Step 2 — Clone and install

```bash
git clone <your-repo-url>
cd arcana
source .venv/bin/activate           # always use this venv, not base conda
```

---

### Step 3 — Fill in your secrets

```bash
cd backend
cp .env.example .env
```

Open `backend/.env` and fill in:

```env
APP_SECRET_KEY=any-long-random-string-you-make-up
GEMINI_API_KEY=your_key_from_step_1
GITHUB_PAT=ghp_your_token_from_step_1
NOTION_TOKEN=ntn_your_token_from_step_1
```

Everything else has sane defaults. Leave it alone for now.

---

### Step 4 — Initialize the database and create your admin

```bash
# From the repo root:
make setup       # creates DB tables, installs dependencies
make seed        # creates the default admin user — COPY THE API KEY IT PRINTS
```

The key printed by `make seed` is your admin key. It looks like `arc_k1_xxxx`. Save it.

---

### Step 5 — Start the backend

```bash
make run-backend
# Server is now at http://localhost:8000
# Interactive API docs at http://localhost:8000/docs
```

---

### Step 6 — Connect a source and index it

Open a second terminal (keep the backend running):

```bash
source .venv/bin/activate
make install-cli                              # install the arcana CLI
arcana config set-key arc_k1_your_admin_key   # use the key from step 4
arcana config set-server http://localhost:8000
```

Add a GitHub repo (via the Swagger UI at `http://localhost:8000/docs` → `POST /github/sources`):

```json
{
  "repo_url": "https://github.com/your-org/your-repo",
  "name": "my-repo",
  "scope": "engineering"
}
```

Then sync it:

```bash
arcana sources list                  # find the source ID
arcana sources sync <source_id>      # pulls the repo, chunks it, embeds it
```

The first sync takes a few minutes. You can watch progress in the backend terminal.

---

### Step 7 — Start the admin panel (optional but useful)

```bash
make run-admin
# Opens at http://localhost:8501
# Login with your admin API key
```

From here you can manage users, sources, see analytics, and run the weekly review — all without touching the CLI.

---

### Step 8 — Ask a question

```bash
arcana ask "How does the authentication middleware work?"
```

Or install the Cursor extension:

```bash
make build-extension
# In Cursor: Extensions → ... → Install from VSIX → pick cursor/*.vsix
# Then in Cursor settings set:
#   arcana.apiKey    = your admin key
#   arcana.serverUrl = http://localhost:8000
```

The Arcana sidebar will appear in Cursor's panel.

---

### Step 9 — Run the full test suite to confirm nothing is broken

```bash
make test-backend    # 345 backend tests
make test-cli        # 28 CLI tests
make test-extension  # 52 extension tests (requires Node)
make test-admin      # 29 admin tests
```

All four suites should be green before you consider the install healthy.

---

### Optional: Use demo mode (safe sandbox, real data untouched)

Demo mode routes to completely separate databases (`data/demo.db`, `data/demo_chromadb/`).
Your real data is never touched.

```bash
export ARCANA_DEMO_MODE=true
make demo-seed       # seeds synthetic data: 6 users, ~160 chunks, 1000 audit events

# Pre-baked demo keys (no lookup needed):
arcana ask "how does auth work?" --api-key arc_demo_dev_sarah
arcana ask "how does auth work?" --api-key arc_demo_dev_james

arcana demo status   # health check, user count, chunk count, cache stats
```

All three surfaces (CLI, Cursor, admin panel) show an orange **DEMO MODE** banner when active.

Add `DEMO_MOCK_LLM=true` to skip Gemini API calls entirely — responses come from pre-computed
answers. Useful during rehearsal when you don't want to burn API quota.

**Reset at any time:**

```bash
make demo-reset      # wipes data/demo.db + data/demo_chromadb/, re-seeds
```

---

---

## Part 2: Integrating with a real company

This is a different operation. You're not running it on your laptop — you're deploying it as
a shared service that a real team of developers will query every day.

---

### Phase A — Choose and provision your infrastructure

> Vercel is not suitable — Arcana is a stateful Python backend that needs a persistent
> process (ChromaDB lives on disk, APScheduler runs in-process).

| Option | Best for | Notes |
|---|---|---|
| **Railway** | Easiest, fastest | Click-deploy from GitHub, managed Postgres, ~$5/mo |
| **Fly.io** | More control | Docker-native, global edge, free tier available |
| **VPS (Hetzner, DigitalOcean)** | Maximum control | Run `docker-compose`, cheapest at scale |

Minimum requirements for the server:

- **2 GB RAM** — the cross-encoder re-ranker loads ~300 MB into memory on startup
- **Persistent disk** — ChromaDB data must survive restarts; mount a volume at `/data`
- **Always-on process** — the daily auto-updater runs on APScheduler inside the FastAPI process

---

### Phase B — Switch to PostgreSQL

SQLite works for local dev but cannot handle concurrent writers from multiple developers.
One environment variable is all it takes:

```env
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/arcana
```

SQLAlchemy handles the rest — no code changes required.

After first deploy, run the Alembic migrations:

```bash
cd backend && alembic upgrade head
```

For ChromaDB: start with the local path (mounted volume). If you grow to millions of chunks,
`vector_store.py` is a thin wrapper — you can migrate to Chroma Cloud or Weaviate by swapping
the client initialisation there.

---

### Phase C — Obtain the right credentials for the company

**GitHub PAT:**
- Create a dedicated machine/bot account (not a personal account)
- Generate a fine-grained PAT with `contents: read` on every repo you want indexed
- Recommended: grant it access to all repos in the org — easier to manage as the team grows

**Notion token:**
- Create a Notion integration in the company workspace: Settings → Connections → Develop or manage integrations
- Have a workspace admin share the relevant page trees with that integration
- The integration only sees pages explicitly shared with it — nothing else

**Gemini API key:**
- Set up a Google Cloud project for the company, enable the Gemini API
- Create a service account key — rotate it on a schedule
- At typical team usage (~500 queries/day) costs are under $10/month

---

### Phase D — Deploy the backend

Set these environment variables on your host:

```env
APP_SECRET_KEY=<generate: python -c "import secrets; print(secrets.token_hex(32))">
GEMINI_API_KEY=<company gemini key>
GITHUB_PAT=<company bot PAT>
NOTION_TOKEN=<company notion token>
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/arcana
CHROMADB_PATH=/data/chromadb
LOG_LEVEL=INFO
UPDATER_ENABLED=true
UPDATER_INTERVAL_HOURS=24
```

Deploy via Docker:

```bash
docker build -t arcana ./backend
docker run -d \
  -p 8000:8000 \
  --env-file .env \
  -v /data:/data \
  arcana
```

Or use `docker-compose.yml` (already in the repo):

```bash
docker compose up -d
```

Confirm the deployment is healthy:

```bash
curl https://your-domain.com/health
# {"status": "ok", "demo_mode": false}
```

---

### Phase E — Register sources and trigger the first index

Once the backend is live:

```bash
# Configure the CLI against the production server:
arcana config set-key arc_k1_your_admin_key
arcana config set-server https://your-domain.com

# Verify the connection:
arcana config test
```

Register repos via the Swagger UI (`https://your-domain.com/docs`) or the admin panel:

```
POST /github/sources
{
  "repo_url": "https://github.com/company/backend-api",
  "name":     "backend-api",
  "scope":    "engineering"
}

POST /notion/sources
{
  "root_page_id": "abc123...",
  "name":         "engineering-wiki",
  "scope":        "product-docs"
}
```

Trigger the first sync for each source:

```bash
arcana sources list
arcana sources sync <source_id>
```

A large monorepo (~500 files) takes 10–20 minutes the first time.
After that, the daily auto-updater only re-indexes changed files — takes seconds.

---

### Phase F — Create user accounts for developers

Arcana has **no self-signup**. The admin creates every account. This is intentional — it
enforces RBAC from the very first user.

```bash
# Create an account for a developer:
arcana users create --email alice@company.com --role developer --name "Alice"
# Output: arc_k1_xxxx  ← send this key to Alice

# Grant her access to sources she should see:
# POST /admin/permissions
# { "user_id": <alice_id>, "source_id": <source_id>, "scope": "engineering" }
```

Or do all of this through the admin panel at `http://your-domain:8501`.

**Role reference:**

| Role | Can do |
|---|---|
| `viewer` | Query only |
| `developer` | Query + own audit history |
| `senior_dev` | Query + analytics dashboard |
| `admin` | Everything (user CRUD, source management, weekly review) |

RBAC is enforced at retrieval time — a `viewer` cannot receive chunks from a source they
haven't been granted, even via the cache.

---

### Phase G — Distribute the CLI to developers

Send each developer their API key and these four commands:

```bash
pip install git+https://github.com/your-org/arcana.git#subdirectory=cli

arcana config set-key arc_k1_their_personal_key
arcana config set-server https://your-domain.com
arcana config test    # should print "Connection OK"

arcana ask "How do I set up the local dev environment?"
```

That is the entire onboarding experience from a new hire's perspective.

---

### Phase H — Distribute the Cursor extension

Build the `.vsix` once from your machine, distribute to the team:

```bash
make build-extension    # produces cursor/*.vsix
```

Each developer installs it in Cursor:

1. Cursor → Extensions → `...` → Install from VSIX → pick the `.vsix` file
2. Open Cursor settings and set:
   - `arcana.apiKey` → their personal key
   - `arcana.serverUrl` → `https://your-domain.com`
3. The Arcana sidebar appears. Done.

After indexing, they can select any code in the editor and right-click → **Ask Arcana about selection** — it sends the highlighted snippet as context with the query.

---

### Phase I — Maintain the knowledge base with weekly review

Every Friday, the auto-updater generates a narrative summary of what changed in the codebase
and docs since the previous review. An admin must:

1. Open the admin panel → **Weekly Review** page (or run `arcana updater review-week`)
2. Read the AI-generated summary of what changed and why it matters
3. Click **Acknowledge** — or use **Revert** on any auto-updates that were wrong

This keeps the knowledge base accurate over time without anyone manually re-indexing files.
If the AI mislabelled something (e.g. marked a refactor as a breaking API change), the admin
can revert that specific update record and write a correction.

---

### The difference between local and production at a glance

| | Local testing | Real company |
|---|---|---|
| Database | SQLite (file) | PostgreSQL |
| ChromaDB | Local folder | Persistent volume on server |
| API tokens | Yours personally | Owned by a company bot/service account |
| Users | Just you | One account per developer, admin-created |
| Sources | Any repo you point at | Company repos + Notion workspace |
| Daily updates | Manual trigger | Auto-updater running in background (24h interval) |
| Backend URL | `localhost:8000` | `https://arcana.your-company.com` (behind Nginx/Caddy) |
| Admin panel | `localhost:8501` | Internal URL, ideally behind VPN or IP allowlist |
| Demo mode | Use freely | Keep off (`ARCANA_DEMO_MODE=false`) in production |
