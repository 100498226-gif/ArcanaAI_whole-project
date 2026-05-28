# How AI Built Arcana — Development Process and Methodology

This document describes how Arcana was built using AI-assisted development: what the workflow looked like, how decisions were made, what role the AI played at each stage, and what patterns emerged across 17 sessions spanning roughly three weeks.

---

## Overview

Arcana was built entirely through **conversational AI-assisted development** using Claude (Claude Code). There was no team, no sprint planning, and no traditional project management. A single developer worked with an AI agent in an iterative loop: describe the intent, let the AI implement, review the output, catch bugs, refine.

The project went from zero to a fully functional RAG platform — with a FastAPI backend, CLI, Cursor IDE extension, Electron overlay, browser UI, Streamlit admin panel, analytics layer, auto-updater, demo mode, and offline LLM support — across **17 sessions** between March 29 and April 15, 2026.

---

## The Working Model

### Sessions, not sprints

Each unit of work was a **session** — a single conversation with the AI. Sessions ranged from focused feature implementations (2–3 hours) to multi-PR overhauls (a full day). A session had a clear goal going in, often defined by a Phase PRD (Product Requirements Document), and ended with a CONTEXT.md update so the next session could pick up without re-explaining context.

This is the key structural element: the AI had no persistent memory across sessions. The `CONTEXT.md` file at the repo root served as the AI's long-term memory — a running log of what was built, what decisions were made, and what was deferred. The developer maintained this file, and the AI read it at the start of every session to restore context.

### PRD-driven implementation

Every phase was preceded by a **PRD** (Product Requirements Document) written collaboratively or provided by the developer. The PRD specified:
- What to build (scope)
- What to defer
- Design decisions that had already been made
- Acceptance criteria (often expressed as test cases)

The AI then implemented the PRD end-to-end: creating files, writing services, wiring routers, writing tests, and running the test suite to confirm all acceptance criteria passed before closing the session.

This PRD-first pattern had a concrete benefit: it forced clarification of ambiguous design questions *before* any code was written, which eliminated a major source of rework.

### Mandatory post-implementation audit

Every session that produced code was followed by a **3-pass quality audit** run by the AI itself, defined in `.claude/commands/audit-phase.md` and enforced in `CLAUDE.md`:

- **Pass 1 — Correctness & Bugs:** unused imports, interface inconsistencies, silent errors, missing validation
- **Pass 2 — Production Readiness:** async correctness, SQL portability, security issues, migration coverage
- **Pass 3 — Homogeneity:** consistent auth patterns, logging conventions, test naming, error handling across phases

This audit ran automatically, without the developer having to ask, after every implementation. Bugs caught in audit were fixed within the same session before the PR was opened. The session logs document dozens of bugs caught this way — in Phase 7, for example, three rounds of audit caught 15+ issues across services and tests.

---

## How AI Was Used at Each Stage

### Architecture and design

The AI proposed and defended architectural choices in response to high-level requirements. Key decisions that emerged from these conversations:

- **FastAPI over Next.js** — The project started with a Next.js prototype (`v0-project-29mar` branch). In session 1, the decision was made to drop it entirely and build a clean Python/FastAPI backend. The AI reasoned through the tradeoff: the primary surface is an API consumed by multiple clients (CLI, extension, overlay), not a web app, so a Python backend is more natural and consistent with the ML stack.
- **ChromaDB over Pinecone/Weaviate** — Embedded, zero-infrastructure vector store appropriate for a thesis-scale project. No additional managed service needed.
- **SQLite for dev, PostgreSQL for prod** — Single `DATABASE_URL` env var swap; no code changes required.
- **Gemini over Anthropic** — Developer preference. The AI adapted the entire LLM layer to `google-genai` and later migrated it again when the SDK was deprecated (session 7).
- **Separate ChromaDB collections per embedding space** — This was the AI's diagnosis in session 17. Sharing `code_chunks`/`doc_chunks` between Gemini (3072-dim) and BGE (768-dim) vectors caused ChromaDB to reject queries with a dimension mismatch error. The fix — four separate collections — was the AI's proposal, not a pre-planned design.

### Code generation

The AI wrote all production code, including:
- Full FastAPI application with async SQLAlchemy, Alembic migrations, Pydantic models
- GitHub and Notion ingestion pipelines with tree-sitter AST chunking
- Complete RAG pipeline (embed → retrieve → assemble context → stream LLM response)
- Gemini and Ollama streaming clients
- A Python CLI built with Typer and Rich
- A Cursor IDE extension in TypeScript with a full webview UI
- A macOS Electron overlay with global hotkey and tray menu
- A 7-page Streamlit admin panel
- A demo mode with synthetic data seeding
- A retrieval evaluation harness with P@k, R@k, MRR metrics
- Browser UI in vanilla JavaScript with SSE streaming, Mermaid diagrams, and countdown timers

No scaffolding tools, no templates, no boilerplate generators. Every file was written from scratch by the AI in response to the PRD or a conversational description.

### Bug detection and diagnosis

Some of the most valuable AI contributions were bugs the AI caught that would have been hard to diagnose manually:

**Dimension mismatch (session 17):** The offline mode appeared to work — no crash, no obvious error — but every query returned the fallback response ("No relevant information found"). The root cause was buried in ChromaDB's error log: `Collection expecting embedding with dimension of 3072, got 768`. The old `code_chunks` collection had been created by Gemini embeddings and ChromaDB silently rejected all BGE query attempts. The AI diagnosed this from the error log and proposed the architectural fix (separate collections) within the same session.

**Background task returning undefined (Phase 11):** The local ingest endpoint was implemented as a `BackgroundTasks` endpoint. The JavaScript frontend was receiving `undefined` for `data.embedded` because the response returned before the background task completed. The AI caught this in the audit pass and converted the endpoint to synchronous before any user reported the bug.

**Import error on startup (session 16):** After removing the `get_offline_model` function from the settings store, `routers/health.py` still imported it — causing an `ImportError` on every server startup. The AI caught the stale import during cleanup.

**Collision risk in local ingestion (Phase 11):** The initial implementation used `local_path.name` (just the directory name) as the `repo_key` for chunk IDs. Two directories named `src/` in different projects would have collided. The AI caught this in the audit and changed the key to `local_path.resolve()` (full absolute path).

**Function defined after use (Phase 9):** In `6_Weekly_Review.py`, the `_revert_section` function was called before it was defined. Python's function scoping allows this in some cases, but the structure was fragile. The AI caught and fixed it in the audit.

### Refactoring and migration

When external dependencies changed, the AI handled migrations without breaking the existing functionality:

**Gemini SDK migration (session 7):** Google deprecated `google-generativeai` in favor of `google-genai`. The AI updated all three affected files (`gemini_client.py`, `prompt_builder.py`, `pyproject.toml`), rewrote the client from the old `GenerativeModel` API to the new `genai.Client` API, verified all 198 tests still passed, and opened a PR — in a single session.

**Model consolidation (session 16):** The initial offline implementation included a Fast/Think model selector (two Ollama models). After discovering the Think model (`phi4`) was unreliable, the AI removed the entire selector concept: stripped the UI controls, removed `offline_model` from the settings store, simplified `query_service.py` to use `settings.ollama_fast_model` directly, and updated both frontends — all in one session with zero leftover dead code.

### Testing

The AI wrote all tests. The test count grew from 17 (session 1) to 345+ (session 17), covering:
- Unit tests for every service function
- Integration tests for all API endpoints
- SSE streaming and event-shape tests
- Authentication and permission boundary tests
- Embedding backend tagging (verifying that Gemini chunks get `embedding_backend="gemini"` and BGE chunks get `embedding_backend="local_bge"`)
- Ingest mode guards (verifying 503 responses for GitHub/Notion in offline mode)
- Demo mode isolation (verifying demo data never touches the real database)

Test writing was treated as part of implementation, not a separate phase. The AI wrote tests alongside the code that satisfied them, and the audit pass checked for coverage gaps before declaring a phase complete.

---

## Patterns That Emerged

### Incremental delivery with single-session PRs

Every feature was delivered as a single squash-merged PR. The AI opened the PR, the developer reviewed and merged. No long-lived feature branches. No rebasing across multiple sessions.

This worked because the PRD scoped each phase tightly enough that it could be completed in one session. When a phase was too large (Phase 7 with its auto-updater), the AI split it: Phase 7 (backend + CLI) and Phase 7.5 (Cursor UI) were separated explicitly during planning.

### Deferred work is tracked, not lost

Whenever something was out of scope for the current session, it was explicitly noted in CONTEXT.md under "Next Session" or "Deferred". This gave the AI a clear backlog to pick up the following session without the developer having to re-explain why something was skipped.

### The audit closes the loop

Without the mandatory audit, AI-generated code has a known failure mode: the implementation passes a quick look but contains subtle bugs (stale imports, wrong argument names, async/sync mismatches, missing edge cases). The 3-pass audit — run by the AI, not the developer — caught these before they landed on `main`. The session logs document at least 30 distinct bugs caught this way across the project lifecycle.

### CONTEXT.md as the project brain

The `CONTEXT.md` file was the most important artifact in the entire project. It was updated at the end of every session with:
- What was built (file list, key changes)
- Design decisions made and the rationale
- Bugs caught in audit and how they were fixed
- Deferred items and why
- Test counts

Because the AI had no cross-session memory, this file was the only thing that allowed 17 sessions of coherent development without regression or repeated work. It also served as a debugging tool: when a bug surfaced, the session log for the phase that introduced it contained the original design intent, which helped narrow down root causes quickly.

---

## Numbers

| Metric | Value |
|--------|-------|
| Total sessions | 17 |
| Elapsed calendar time | ~17 days (2026-03-29 to 2026-04-15) |
| Phases completed | 12 (Phase 1 through Phase 12) |
| PRs merged to main | 14 |
| Tests at project end | 345+ (backend) + 28 (CLI) + 52 (extension) + 29 (admin) |
| Languages written by AI | Python, TypeScript, JavaScript, HTML/CSS |
| Files written by AI | ~80+ source files |
| Bugs caught by audit (approx.) | 30+ across all sessions |

---

## What the Human Did

The developer's role in this workflow was:
- Write or provide PRDs with clear scope and design decisions
- Make architectural calls when the AI presented tradeoffs (e.g., SQLite vs. PostgreSQL, Gemini vs. Anthropic)
- Review and merge PRs
- Confirm or redirect during implementation when the AI surfaced questions
- Maintain `CONTEXT.md` (the AI drafted updates; the developer confirmed them)
- Run commands in the terminal when the AI needed interactive operations (e.g., `ollama pull`, `alembic upgrade head`)
- Validate that the final feature behaved correctly end-to-end

The developer wrote essentially no production code directly. The judgment about *what* to build and *why* was human. The judgment about *how* to build it — architecture, implementation, tests, debugging — was largely AI.

---

## Limitations Encountered

**No cross-session memory.** The AI started each session with zero knowledge of prior sessions. CONTEXT.md mitigated this but required discipline: if the context file was incomplete or stale, the AI would make decisions inconsistent with earlier sessions.

**Dependency on correct error information.** The dimension mismatch bug in session 17 was only diagnosable because the error log contained the exact ChromaDB message. Without that, the AI would have been debugging blind.

**Model size constraints.** The choice of `qwen2.5:3b` as the offline model was driven by hardware constraints (Intel i5 MacBook). The AI accounted for this in context budget sizing (3500 tokens vs. 6000), but the fundamental tradeoff — answer quality vs. hardware feasibility — was a human call.

**Test environment fragility.** Four tests in `test_local_embedder` failed persistently due to a NumPy ABI conflict between torch 2.2.x and NumPy 2.x in the shared virtual environment. The AI identified the root cause correctly but the fix (stabilising the venv) was deferred. The AI was careful not to mark this as a code bug.

---

## Summary

Arcana demonstrates that a single developer with a capable AI agent can produce production-quality, multi-surface software at a pace that would normally require a small engineering team. The key enablers were:

1. **PRD-first:** design decisions made before implementation, not during it
2. **Mandatory self-audit:** AI-generated code reviewed by the same AI before delivery
3. **Persistent context file:** compensates for the AI's lack of cross-session memory
4. **Single-session PRs:** tight scoping so every session ends with a shippable artifact
5. **Explicit deferral:** out-of-scope work is tracked rather than improvised or forgotten

The workflow is not "describe and accept" — it is a tight feedback loop where the human shapes the direction and the AI drives the execution, with the audit step acting as quality control in between.
