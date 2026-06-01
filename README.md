# Arcana — Backend & User Guide

Arcana is a personal document assistant. You upload your own files (`.md` and `.txt`), ask questions in plain English, and get answers grounded in your documents — with a citation showing exactly which file the answer came from.

Three pieces must run at the same time:

| Piece | What it does | Port |
|-------|-------------|------|
| **This repo — Backend** | AI engine, RAG pipeline, conversation database | `8000` |
| **Arcana_frontend** | Browser chat interface | `5173` |
| **Arcana_overlay** | macOS desktop overlay + menu bar icon | — |

---

## Part 1 — First-Time Setup

You only need to do this once. After this, starting Arcana every day takes three terminal commands.

### What you will need
- A Mac (Apple Silicon or Intel)
- An active internet connection
- A free **Google AI Studio** account (for a Gemini API key)
- All three repos cloned to your computer

### Step 1 — Get your Gemini API key

1. Go to **https://aistudio.google.com/** in your browser
2. Sign in with a Google account
3. Click **"Get API key"** → **"Create API key"**
4. Copy the key (it looks like `AIzaSy...`)

> Keep this key safe — treat it like a password. It is stored only in a local file on your computer.

### Step 2 — Configure the backend

```bash
cd Arcana_backend/backend
cp .env.example .env
```

Open `.env` in any text editor and replace the placeholder:

```
GEMINI_API_KEY=paste_your_key_here
```

### Step 3 — Start the backend

```bash
cd Arcana_backend/backend
.venv/bin/python3.9 -m uvicorn arcana.main:app --reload --port 8000
```

Wait until you see `Application startup complete.` — leave this terminal open.

### Step 4 — Load the demo documents (first time only)

Open a new terminal and run:

```bash
curl -X POST http://localhost:8000/ingest/local \
  -H "Content-Type: application/json" \
  -d '{"paths":["<absolute_path_to>/Arcana_backend/demo-knowledge"]}'
```

Wait for a response like `{"embedded": 244, ...}`. This takes 30–60 seconds and only needs to be done once.

### Step 5 — Start the frontend

```bash
cd Arcana_frontend
npm install    # first time only
npm run dev
```

Wait until you see `Local: http://localhost:5173`.

### Step 6 — Start the overlay app

```bash
cd Arcana_overlay
npm install    # first time only
npm start
```

The Arcana logo will appear in your macOS menu bar.

### Step 7 — Grant Accessibility permission (first time only)

A dialog will appear asking for Accessibility access — required for the **Shift+Ctrl** keyboard shortcut.

1. Click **"Open Settings"** in the dialog
2. Go to **System Settings → Privacy & Security → Accessibility**
3. Enable **Arcana** (or Electron)
4. Restart the overlay app (`Ctrl+C` → `npm start`)

### You are ready

Open **http://localhost:5173** in your browser, or press **Shift+Ctrl** to open the overlay.

---

## Part 2 — Daily Startup

Three terminals, three commands:

```bash
# Terminal 1 — Backend
cd Arcana_backend/backend
.venv/bin/python3.9 -m uvicorn arcana.main:app --reload --port 8000

# Terminal 2 — Frontend
cd Arcana_frontend
npm run dev

# Terminal 3 — Overlay
cd Arcana_overlay
npm start
```

Then open **http://localhost:5173** or press **Shift+Ctrl**.

---

## Part 3 — How to Use Arcana

### Ask a question

Type your question in the **"I want to know..."** box and press Enter. The answer appears word by word. Questions to try with the demo documents:

- *"What is the early termination penalty in my rental contract?"*
- *"Which of my insurance policies covers water damage?"*
- *"What was the total on the electrician invoice?"*

### Read an answer

Each answer shows a **source bubble** at the bottom-right — click it to open the source file in macOS Finder.

If the question has no answer in your documents, a dialog appears offering to search with Google, ChatGPT, or Claude instead.

### Upload your own files

1. Send a first message (the right sidebar opens)
2. Click the **→** arrow to expand the sidebar
3. Click **"Sync here"** → pick any `.md` or `.txt` file
4. Ask questions about it

### Manage history

All conversations are saved automatically. In the history sidebar:
- Click a card to reload a past conversation
- Hover a card → click **⋮** → **Pin** (max 3, kept at the top) or **Delete**

### Overlay shortcuts

| Action | How |
|--------|-----|
| Open / close overlay | **Shift+Ctrl** |
| Open from menu bar | Click Arcana logo → "Open overlay" |
| Open in browser | Click Arcana logo → "Open in browser" |
| Collapse to slim bar | Minimize button (top-left, overlay only) |
| Quit | Click Arcana logo → "Quit Arcana" |

---

## Part 4 — Troubleshooting

| Problem | Fix |
|---------|-----|
| `Search failed` | Check `backend/.env` — API key must be valid. Restart the backend. |
| `Rate limit hit` | Gemini free tier: ~10 req/min. Wait 1–2 minutes. |
| Shift+Ctrl does nothing | Accessibility not granted — see Step 7. Fallback: **Ctrl+Shift+Space**. |
| Overlay shows blank page | Frontend not running — start `npm run dev` first. |
| History doesn't load | Backend not running — start it first. |
| Port 8000 in use | `kill $(lsof -ti :8000)` then restart the backend. |
| Port 5173 in use | `kill $(lsof -ti :5173)` then restart the frontend. |
| `LLM configuration error` | Check the API key in `.env`. |

---

## Backend Reference

### Technology Stack

| Technology | Role |
|-----------|------|
| Python 3.9 | Runtime |
| FastAPI | Async web framework, automatic docs at `/docs` |
| ChromaDB | Local vector store (HNSW + cosine distance) |
| SQLite + Alembic | Conversation persistence, versioned migrations |
| Gemini API | Embeddings (`gemini-embedding-001`) + generation (`gemini-2.5-flash-lite`) |
| structlog | Structured JSON logging |

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health/` | Server status and chunk counts |
| `POST` | `/query/` | Stream an answer via SSE |
| `POST` | `/ingest/local` | Ingest a directory of `.md`/`.txt` files |
| `POST` | `/ingest/upload` | Upload a single `.md`/`.txt` file from the browser |
| `GET` | `/conversations/` | List all conversations |
| `GET` | `/conversations/{id}` | Get messages for a conversation |
| `DELETE` | `/conversations/{id}` | Delete a conversation |
| `GET` | `/files/reveal?path=...` | Open a file in macOS Finder |

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | Yes | Google AI Studio API key |
| `DATABASE_URL` | No | SQLite path (default: `./data/arcana.db`) |
| `CHROMADB_PATH` | No | ChromaDB directory (default: `./data/chromadb`) |
| `GEMINI_MODEL` | No | Generation model (default: `gemini-2.5-flash-lite`) |

### Repository Structure

```
backend/
├── arcana/
│   ├── main.py              # FastAPI app, lifespan, router registration
│   ├── config.py            # Pydantic settings, env var loading
│   ├── database.py          # Async SQLAlchemy engine and session factory
│   ├── models.py            # Conversation and Message ORM models
│   ├── vector_store.py      # ChromaDB collections
│   ├── routers/             # query, ingest, conversations, files, health
│   └── services/            # retrieval, ingestion, query_service,
│                            # gemini_client, prompt_builder, context_assembler
├── migrations/
│   └── versions/
│       └── 0001_conversations.py
├── demo-knowledge/          # 35+ sample .md and .txt files
├── .env.example
└── pyproject.toml
```

---

*Arcana — built by Ignacio, 2026*
