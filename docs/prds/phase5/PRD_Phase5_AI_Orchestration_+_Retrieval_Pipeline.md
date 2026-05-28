# PRD — Phase 5: AI Orchestration + Retrieval Pipeline

**Product:** Arcana — AI-Powered Developer Onboarding Platform
**Phase:** 5 of Tier 1
**Version:** 1.0
**Date:** April 2026
**LLM Provider:** Gemini APIs
**Depends on:** Phases 1–4 (complete)
**Related:** [Arcana Limitations & Design Decisions Log](./Arcana_Limitations_and_Design_Decisions.md) — entries L5.1 through L5.8

---

## 1. Overview

This is the core intelligence layer of Arcana — the phase where the knowledge base stops being a static store and starts answering questions. Everything built in Phases 1–4 (ingestion, storage, RBAC) converges here into a retrieval pipeline that takes a developer's natural language question and returns an accurate, referenced, role-aware answer.

The pipeline has seven stages: RBAC scope resolution → semantic cache check (using resolved scopes) → hybrid search (vector + keyword) → result fusion → re-ranking → context assembly → LLM generation with streaming citations. Each stage is designed to improve answer quality while respecting access boundaries and minimizing latency and cost.

**Note on ordering:** RBAC scope resolution happens first because the semantic cache check (stage 2) needs the user's scopes to validate a cache match (see Section 12.4). If the cache hits, stages 3–7 are skipped entirely.

By the end of this phase, a developer can ask "how does the authentication middleware work?" through the API and receive a streaming response with specific file references, Notion documentation links, line numbers, and inline code snippets — all scoped to only the sources they're authorized to see.

---

## 2. Objectives

- Build a BM25 keyword index (SQLite FTS5) and backfill all existing chunks from Phases 2–3
- Implement hybrid search combining vector similarity (ChromaDB) and keyword matching (BM25) in parallel
- Fuse results from both search methods using reciprocal rank fusion (RRF)
- Add a re-ranking stage using a cross-encoder model or Cohere Rerank API to re-score results by relevance
- Assemble optimal context from re-ranked results: deduplicate, order by source type, apply cross-reference boosting, and fit within the token budget
- Build the prompt construction layer with role-aware system prompts, structured output formatting, and citation instructions
- Integrate with the Gemini API for streaming response generation
- Format streaming output with file references, Notion links, line numbers, and code snippets (stream + cite)
- Implement semantic caching to serve repeated/similar queries without hitting the LLM
- Add a component renderer for agent-rendered dynamic views (structured JSON output)
- Expose the query API endpoint with streaming support
- Update ingestion hooks so future syncs (daily Notion, re-index) write to both ChromaDB and FTS5

---

## 3. Scope

### 3.1 In scope

- BM25 keyword index creation and backfill of all existing chunks
- Ingestion hook updates for dual-write (ChromaDB + FTS5)
- Hybrid search execution (vector + keyword in parallel)
- Reciprocal rank fusion (RRF) for result merging
- Re-ranking with cross-encoder or Cohere Rerank API
- Context assembly with deduplication, source ordering, and token budget management
- Cross-reference boosting (co-retrieve code+doc chunks that reference each other)
- Architectural overview priority boost
- Role-aware context biasing
- Prompt builder with system prompt, role context, assembled chunks, question, and output format spec
- Gemini API integration with streaming response handling
- Stream + cite response formatter (file refs, Notion links, line numbers, code blocks)
- Semantic cache (embed queries, store results, serve on high similarity match)
- Component renderer for structured JSON output (agent-rendered views)
- POST /query endpoint with streaming SSE (Server-Sent Events) support
- Data privacy handling for LLM API calls (see cross-phase limitation LX.1)

### 3.2 Out of scope

- Cursor extension or CLI client (Phase 6 — this phase builds the API they consume)
- Weekly auto-updater with proposal workflow (Phase 7)
- Agent-rendered view component library design (Phase 8 — this phase builds the renderer, Phase 8 designs the components)
- Fine-tuning or training custom models
- Multi-turn conversation memory (each query is independent for the MVP)
- Function calling / tool use in Gemini (post-thesis)

---

## 4. BM25 Keyword Index

### 4.1 Purpose

Vector search excels at semantic matching ("how does auth work" finds authentication-related chunks even if they never use the word "auth"). But it struggles with exact matches — function names, config keys, error messages, specific variable names. BM25 keyword search fills this gap. Together they form hybrid search.

### 4.2 Implementation: SQLite FTS5

The keyword index uses SQLite's built-in FTS5 (Full-Text Search 5) extension. This avoids adding an external dependency and keeps everything in the same SQLite database used by the rest of the application.

**FTS5 table schema:**

```sql
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    chunk_id UNINDEXED,
    content,
    source_type UNINDEXED,
    access_scope UNINDEXED,
    repo UNINDEXED,
    file_path UNINDEXED,
    symbol_name UNINDEXED,
    page_title UNINDEXED,
    tokenize='porter unicode61'
);
```

The `porter` tokenizer applies Porter stemming (so "authentication" matches "authenticating") and `unicode61` handles Unicode normalization.

**Column design:** Only `content` is full-text indexed and searchable. All other columns are marked `UNINDEXED` — they are stored in the table for filtering and retrieval but are not part of the full-text index. `chunk_id` is used for lookups and deduplication during backfill. The metadata columns (`source_type`, `access_scope`, `repo`, etc.) are used in WHERE clauses for RBAC filtering and result enrichment.

### 4.3 Backfill process

On first run of Phase 5, all existing chunks from ChromaDB must be indexed into FTS5:

1. Iterate through all documents in the `code_chunks` ChromaDB collection
2. For each chunk, insert into `chunks_fts` with the chunk ID, content text, and metadata
3. Repeat for all documents in the `doc_chunks` collection
4. Log progress: total chunks indexed, time elapsed, any errors

**Idempotency:** The backfill checks for existing entries by `chunk_id` before inserting. Running it multiple times is safe.

**Estimated time:** ~30 seconds for 10,000 chunks, ~3 minutes for 50,000 chunks (SQLite FTS5 inserts are fast).

### 4.4 Ingestion hook updates

After backfill, the ingestion pipelines from Phases 2 and 3 must be updated to dual-write:

- When a new chunk is created (GitHub sync, Notion sync, overview upload): insert into ChromaDB AND into `chunks_fts`
- When a chunk is updated (re-ingestion with same deterministic ID): update in ChromaDB AND update in `chunks_fts`
- When a chunk is deleted (source removed): delete from ChromaDB AND from `chunks_fts`

This is implemented as a `DualStore` abstraction that wraps both stores and exposes `add`, `update`, and `delete` methods. All existing ingestion code calls the `DualStore` instead of ChromaDB directly.

---

## 5. Hybrid Search

### 5.1 Execution model

When a query arrives (after cache check and RBAC filtering), two searches run in parallel:

**Vector search (ChromaDB):**
1. Embed the query text using the configured embedding model
2. Query ChromaDB with the embedding, applying the RBAC `where` clause from Phase 4
3. Retrieve top-k results ranked by cosine similarity
4. Return results with similarity scores

**Keyword search (BM25/FTS5):**
1. Tokenize the query text
2. Query `chunks_fts` using FTS5 MATCH syntax, applying the RBAC `access_scope IN (...)` filter
3. Retrieve top-k results ranked by BM25 score
4. Return results with BM25 scores

Both searches run concurrently using Python `asyncio.gather()` to minimize latency.

### 5.2 Search parameters

| Parameter | Default | Configurable via |
|---|---|---|
| Vector top-k | 20 | `RETRIEVAL_VECTOR_TOP_K` env var |
| BM25 top-k | 20 | `RETRIEVAL_BM25_TOP_K` env var |
| Vector similarity threshold | 0.3 (discard below) | `RETRIEVAL_MIN_SIMILARITY` env var |
| BM25 score threshold | 0.0 (no minimum) | `RETRIEVAL_MIN_BM25` env var |

Fetching 20 from each search (40 total) gives the re-ranker a rich candidate set to work with, even after deduplication.

### 5.3 Query preprocessing

Before searching, the query is preprocessed:

1. **Whitespace normalization** — collapse multiple spaces, trim
2. **Query expansion for BM25** — if the query contains a function name in `camelCase` or `snake_case`, split it into component words (e.g., `getUserProfile` → `get user profile getUserProfile`). This helps BM25 match partial terms while preserving the exact name for exact matches.
3. **The raw query is used for vector embedding** — no expansion needed since the embedding model captures semantics

---

## 6. Result Fusion

### 6.1 Reciprocal rank fusion (RRF)

The two result sets (vector and BM25) are merged using reciprocal rank fusion. RRF is a simple, effective method that doesn't require score normalization between different ranking systems.

**Algorithm:**

For each chunk that appears in either result set:
```
RRF_score = Σ (1 / (k + rank_in_list))
```

Where `k` is a constant (default: 60, standard in literature) and `rank_in_list` is the chunk's position in each result list (1-indexed). Chunks appearing in both lists get scores from both; chunks in only one list get a score from that list only.

### 6.2 Deduplication

The same chunk can appear in both vector and BM25 results. During fusion:

1. Chunks are identified by their `chunk_id`
2. Duplicate entries are merged (their RRF scores are summed, which naturally boosts chunks found by both methods)
3. The merged list is sorted by descending RRF score

### 6.3 Output

The fusion stage outputs a single ranked list of unique chunks, each with:
- `chunk_id`
- `content` (the text)
- `metadata` (all fields: source_type, repo, file_path, etc.)
- `rrf_score` (combined score)
- `retrieval_source` — "vector", "keyword", or "both" (useful for debugging and analytics)

---

## 7. Re-Ranking

### 7.1 Purpose

The initial retrieval (vector + BM25) is fast but rough. Re-ranking uses a more powerful model to re-score the candidate chunks against the original query, producing a more accurate relevance ordering.

### 7.2 Implementation options

Arcana supports two re-ranking backends, configurable via environment variable:

| Backend | Model | Latency | Cost | Quality |
|---|---|---|---|---|
| Cross-encoder (local) | `cross-encoder/ms-marco-MiniLM-L-6-v2` | ~50ms for 40 chunks | Free (runs locally) | Good |
| Cohere Rerank API | `rerank-english-v3.0` | ~200ms for 40 chunks | ~$0.001 per query | Excellent |

**Default for thesis:** Cross-encoder (local). No API dependency, no cost, good enough quality. The Cohere option is available for production or if the local model underperforms.

### 7.3 Re-ranking flow

1. Take the top-N chunks from the fusion stage (default: 30, configurable via `RERANK_CANDIDATES` env var)
2. For each chunk, construct a (query, chunk_content) pair
3. Pass all pairs to the re-ranker in a single batch
4. Re-ranker returns a relevance score for each pair
5. Sort by descending relevance score
6. Take the top-M chunks (default: 10, configurable via `RERANK_TOP_K` env var) for context assembly

### 7.4 Architectural overview boost

Before re-ranking, chunks with `source_type = "architectural_overview"` receive a +0.15 bonus to their RRF score. This ensures the architectural overview is consistently represented in the top-M candidates that reach context assembly, regardless of the specific query. The re-ranker may still rank it lower if it's truly irrelevant, but it gets a fair shot.

### 7.5 Cross-reference boost

Chunks whose `cross_references` metadata (set in Phase 3) references a chunk that's already in the candidate set receive a +0.10 bonus to their RRF score. This enables co-retrieval: if a Notion doc about the auth service is in the candidates, and a code chunk from the auth module cross-references it, the code chunk gets boosted.

---

## 8. Context Assembly

### 8.1 Purpose

Context assembly takes the re-ranked chunks and constructs the final context window that will be sent to the LLM. This is where all the pieces come together: relevant code, documentation, architectural context, and metadata — organized for the LLM to produce a coherent, referenced answer.

### 8.2 Assembly process

1. **Token budget allocation:**
   - Total budget: configurable, default 6000 tokens (leaving room for system prompt + question + response within Gemini's context window)
   - Reserve 500 tokens for architectural overview chunks (if present)
   - Remaining budget allocated to code and doc chunks proportionally

2. **Source type ordering:**
   - Architectural overview chunks first (highest-level context)
   - Documentation chunks second (design rationale, PRDs, guides)
   - Code chunks third (implementation details)
   - Within each group, chunks are ordered by re-rank score (descending)

3. **Deduplication:**
   - If the same content appears in both a GitHub README and a Notion page (common for synced docs), keep the version with richer metadata (more cross-references, more recent edit date)

4. **Truncation:**
   - Fill the token budget greedily: add chunks in order until the next chunk would exceed the remaining budget
   - If a chunk is partially over budget, truncate it at the nearest paragraph or code block boundary (never mid-sentence or mid-function)

5. **Context formatting:**
   - Each chunk is wrapped in a tagged block that the LLM can reference:

```
[SOURCE 1 | type: code | repo: org/backend-api | file: src/auth/middleware.py | lines: 45-92]
def verify_token(token: str) -> User:
    """Verify JWT token and return user."""
    ...
[END SOURCE 1]

[SOURCE 2 | type: documentation | source: Notion | page: Auth Service Architecture | section: Token Verification]
The authentication middleware validates incoming JWTs against...
[END SOURCE 2]
```

### 8.3 Role-aware context biasing

The context assembly applies a mild bias based on the querying user's team:

- If the user's `team` field matches a repo name or Notion workspace keyword (e.g., user.team = "backend" and a chunk comes from the "backend-api" repo), that chunk gets a small priority boost during assembly (moved up in the ordering within its source group)
- This is a soft preference, not a hard filter — the user still sees the best results overall, but results from their own team's domain are slightly favored
- Implemented as a simple string-match tiebreaker, not a complex relevance model

---

## 9. Prompt Builder

### 9.1 System prompt

The system prompt establishes Arcana's behavior, output format, and citation rules:

```
You are Arcana, an AI assistant that helps developers understand their company's
codebase and technical documentation. You answer questions accurately using ONLY
the provided source materials.

RULES:
1. Base your answer exclusively on the provided sources. If the sources don't
   contain enough information, say so — never fabricate.
2. Reference sources by their [SOURCE N] tags when you use information from them.
3. Include specific file paths and line numbers when referencing code.
4. Include Notion page names and section headings when referencing documentation.
5. Use code blocks with language annotations when showing code snippets.
6. Adapt your level of detail to the user's role: provide more implementation
   detail for senior developers, more conceptual context for junior developers.
7. When multiple sources provide complementary information (e.g., code + design doc),
   synthesize them into a coherent answer rather than listing them separately.

OUTPUT FORMAT:
- Answer the question directly and concisely.
- Inline references as [1], [2], etc. matching source numbers.
- At the end, include a REFERENCES section listing each source with its full path
  or page title.

USER CONTEXT:
- Role: {user_role}
- Team: {user_team}
```

### 9.2 Prompt structure

The full prompt sent to Gemini is assembled in this order:

1. **System prompt** (Section 9.1)
2. **Source materials** — the assembled context from Section 8, each chunk wrapped in `[SOURCE N]` tags
3. **User question** — the developer's natural language query
4. **Output format reminder** — a short reinforcement of citation format

### 9.3 Token budget verification

Before sending to Gemini, the prompt builder verifies the total token count using Gemini's native `count_tokens()` method (available via the `google-genai` client). This ensures accurate token counts that match Gemini's actual tokenizer, unlike third-party tools (e.g., tiktoken) which use different tokenization schemes.

Token budget breakdown:
- System prompt: ~300 tokens (fixed)
- Source materials: variable (managed by context assembly, default max 6000)
- User question: typically 10–50 tokens
- Output format reminder: ~50 tokens
- Response headroom: at least 2000 tokens reserved for the answer

If the total exceeds Gemini's context window, the prompt builder trims source materials (removing the lowest-ranked chunks) until it fits.

---

## 10. Gemini API Integration

### 10.1 API configuration

| Parameter | Value |
|---|---|
| Model | `gemini-2.0-flash` (default, configurable) |
| Temperature | 0.2 (low creativity, high accuracy) |
| Max output tokens | 2000 |
| Streaming | Enabled (SSE) |
| Safety settings | Default (no override) |

Model selection is configurable via `GEMINI_MODEL` env var, allowing easy upgrades to newer models.

### 10.2 Streaming implementation

Responses are streamed using Gemini's streaming API. The FastAPI endpoint returns a Server-Sent Events (SSE) stream:

1. Client sends POST /query with the question
2. Server resolves RBAC scopes for the authenticated user
3. Server checks the semantic cache using the query embedding + resolved scopes
4. On cache miss: runs the retrieval pipeline (hybrid search → fusion → re-rank → context assembly)
5. Server sends the assembled prompt to Gemini with `stream=True`
6. As Gemini returns response chunks, the server processes each chunk through the citation formatter (Section 11)
7. Formatted chunks are sent to the client as SSE events
8. On stream completion, a final SSE event includes the full references list and metadata
9. The query embedding + response are stored in the semantic cache for future hits

### 10.3 SSE event format

```
event: chunk
data: {"text": "The authentication middleware ", "references": []}

event: chunk
data: {"text": "validates incoming JWTs using the `verify_token` function [1]", "references": [{"id": 1, "type": "code", "file": "src/auth/middleware.py", "lines": "45-92", "repo": "org/backend-api"}]}

event: done
data: {"references": [...], "query_id": "uuid", "latency_ms": 1240, "cache_hit": false, "chunks_used": 7}
```

### 10.4 Error handling

| Error | Behavior |
|---|---|
| Gemini API timeout (30s) | Retry once with exponential backoff. If still fails, return error SSE event with "Service temporarily unavailable." |
| Gemini API rate limit (429) | Queue the request, retry after the Retry-After header duration. |
| Gemini content filter triggered | Return the partial response with a note: "Some content was filtered by the model's safety system." |
| Gemini API key invalid | Return 500 with "LLM service configuration error." Never expose the key in the error. |
| Empty retrieval results | Skip LLM call entirely. Return: "I couldn't find relevant information in the knowledge base for your question. Try rephrasing or check if the relevant sources have been indexed." |

---

## 11. Stream + Cite

### 11.1 Purpose

Raw LLM output contains references like "[1]" and "[SOURCE 2]" but the client needs structured, actionable citation data: clickable file paths, line numbers, Notion URLs, repo links. The stream + cite layer transforms raw text into structured output.

### 11.2 Citation extraction

As each streamed text chunk arrives from Gemini, the formatter:

1. Scans for reference patterns: `[1]`, `[2]`, `[SOURCE 1]`, etc.
2. Maps each reference number to its source material metadata (stored from context assembly)
3. Constructs a structured citation object:

**Code citation:**
```json
{
    "id": 1,
    "type": "code",
    "repo": "org/backend-api",
    "file_path": "src/auth/middleware.py",
    "lines": "45-92",
    "symbol_name": "verify_token",
    "language": "python",
    "url": "https://github.com/org/backend-api/blob/main/src/auth/middleware.py#L45-L92"
}
```

**Documentation citation:**
```json
{
    "id": 2,
    "type": "documentation",
    "source": "notion",
    "page_title": "Auth Service Architecture",
    "section": "Token Verification",
    "page_id": "abc123",
    "url": "https://notion.so/abc123"
}
```

**Architectural overview citation:**
```json
{
    "id": 3,
    "type": "architectural_overview",
    "section": "Authentication Flow",
    "file_name": "architecture-overview.md"
}
```

### 11.3 Code block formatting

When the LLM includes code snippets in its response, the formatter:

1. Detects fenced code blocks (``` markers)
2. Ensures language annotation is present (adds it from the source chunk's `language` metadata if the LLM omitted it)
3. Adds a source attribution header above the code block: `// From: src/auth/middleware.py (lines 45-92)`

### 11.4 Reference section

At the end of the stream, the formatter appends a structured references section:

```
--- References ---
[1] src/auth/middleware.py:45-92 (org/backend-api) — verify_token function
[2] Auth Service Architecture > Token Verification (Notion)
[3] Architecture Overview > Authentication Flow
```

This is sent as part of the final `done` SSE event alongside the full citation objects.

---

## 12. Semantic Cache

### 12.1 Purpose

Many developers ask similar questions. "How does auth work?" and "explain the authentication flow" are semantically identical. Without caching, each query runs the full pipeline (embedding → search → re-rank → LLM call). Semantic caching stores query-response pairs and serves cached responses when a new query is sufficiently similar to a previous one.

### 12.2 How it works

1. When a query arrives, embed it using the same embedding model used for chunk embeddings
2. Search the cache collection for the nearest neighbor
3. If the cosine similarity exceeds the threshold (default: 0.95), return the cached response
4. If no match, run the full pipeline. After generating the response, store the query embedding + response in the cache

### 12.3 Cache storage

A dedicated ChromaDB collection `query_cache`:

| Field | Description |
|---|---|
| id | Hash of the query embedding (deterministic) |
| embedding | The query's vector embedding |
| document | The full response text |
| metadata.query_text | The original query string |
| metadata.references | JSON-serialized citation objects |
| metadata.user_role | The role of the user who triggered the cached response |
| metadata.access_scopes | JSON array of access scopes that were used for this query |
| metadata.created_at | When the cache entry was created |
| metadata.ttl_expires_at | Expiry timestamp (default: 24 hours from creation) |
| metadata.hit_count | Number of times this cache entry has been served |

### 12.4 Cache scoping

Cache entries are scoped by access permissions. A cache hit is only valid if:

1. The cosine similarity exceeds 0.95
2. The cached entry's `access_scopes` are a **subset** of the querying user's permitted scopes (the user has at least as much access as the original querier)
3. The cached entry's `user_role` level is ≤ the querying user's role level (a cached response from a `dev` can serve a `senior_dev`, but not vice versa — the senior_dev might have had access to sensitive content)
4. The TTL has not expired

If any condition fails, the cache is bypassed and the full pipeline runs.

**Important edge case:** A cached response from a `dev` user served to a `senior_dev` is safe (no unauthorized data leaks) but may be *incomplete* — the `senior_dev` might have access to sensitive sources that weren't included in the original response. This is an acceptable trade-off for the MVP: the response is correct within its scope, just potentially missing additional context. The `senior_dev` can re-query with cache disabled (POST /admin/cache/flush or CACHE_ENABLED=false) if they need a comprehensive answer. For production, cache entries could be keyed by the full scope set to avoid this.

### 12.5 Cache invalidation

Cache entries are invalidated when:

- **TTL expires** — entries older than 24 hours (configurable via `CACHE_TTL_HOURS` env var) are purged on next access or by a scheduled cleanup job
- **Knowledge base updates** — when Phase 7's weekly updater re-indexes chunks, all cache entries whose `access_scopes` overlap with the updated source's scope are purged (implemented in Phase 7, the invalidation API is built here)
- **Manual flush** — admin can call POST /admin/cache/flush to clear all entries

### 12.6 Cache metrics

The system tracks:
- Total cache entries
- Hit rate (cached responses / total queries)
- Average latency for cache hits vs. full pipeline
- Estimated API cost savings (hits × average tokens per query × Gemini pricing)

These metrics are exposed via GET /admin/cache/stats.

---

## 13. Component Renderer

### 13.1 Purpose

When a user or admin asks an exploratory question ("show me which repos are most queried", "what areas of the knowledge base have gaps"), the LLM can return a structured JSON response instead of plain text. The component renderer in the client (Phase 6) will turn this JSON into visual charts, tables, and metrics.

### 13.2 Detection

The prompt builder detects "visual" queries using keyword heuristics:
- Keywords: "show me", "visualize", "chart", "graph", "breakdown", "compare", "stats", "metrics", "progress"
- If detected, the prompt includes an additional instruction:

```
The user is requesting a visual representation. Return your response as a JSON
object with the following structure:
{
    "type": "chart" | "table" | "metric_card" | "timeline" | "progress",
    "title": "Short descriptive title",
    "data": { ... component-specific data ... },
    "narrative": "A 1-2 sentence textual summary accompanying the visual"
}
```

### 13.3 Supported component types

| Type | Data structure | Use case |
|---|---|---|
| chart | `{"labels": [...], "datasets": [{"label": "...", "values": [...]}]}` | Bar, line, and pie charts for quantitative data |
| table | `{"headers": [...], "rows": [[...], [...]]}` | Tabular data display |
| metric_card | `{"metrics": [{"label": "...", "value": "...", "change": "..."}]}` | Key metrics with optional delta |
| timeline | `{"events": [{"date": "...", "title": "...", "description": "..."}]}` | Chronological event display |
| progress | `{"items": [{"label": "...", "current": N, "total": N}]}` | Progress bars for onboarding tracking |

### 13.4 Fallback

If the LLM fails to produce valid JSON (parsing error), the system falls back to the `narrative` field as plain text. If that's also missing, it re-runs the query without the visual instruction to get a text-only response.

---

## 14. API Endpoints

### 14.1 Query endpoint

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | /query | API key (viewer+) | Submit a question, receive streaming answer with citations |

**Request body:**
```json
{
    "question": "How does the authentication middleware work?",
    "context_file": "src/api/routes/users.py",
    "prefer_visual": false
}
```

- `question` (required): the natural language query
- `context_file` (optional): the file currently open in the editor, used for contextual relevance boosting. When provided, the retrieval pipeline applies a proximity boost: chunks from the same file receive +0.20 to their RRF score, chunks from the same directory receive +0.10, and chunks from the same repo receive +0.05. This makes answers more relevant to what the developer is currently working on.
- `prefer_visual` (optional): force visual/component response format

**Response:** SSE stream (see Section 10.3 for event format)

### 14.2 Query history

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | /query/history | API key (dev+) | Get the user's query history with timestamps and response metadata |

Returns paginated list of past queries (from audit_logs where event_type=query and user_id matches). Does not include full response text (too large to store) — includes question, sources accessed, response time, and whether it was a cache hit.

### 14.3 Answer feedback

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | /query/{query_id}/feedback | API key (dev+) | Submit feedback on an answer's quality |

**Request body:**
```json
{
    "rating": "helpful" | "unhelpful" | "incorrect",
    "comment": "Optional free-text feedback"
}
```

Feedback is stored in audit_logs as event_type=feedback with the query_id in details. This data is used to evaluate retrieval quality and tune parameters.

**Note:** This requires adding `feedback` to the `event_type` enum in the audit_logs table (Phase 4 schema). An Alembic migration in this phase extends the enum to include this value.

### 14.4 Cache management

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | /admin/cache/stats | admin | Cache metrics: entry count, hit rate, cost savings |
| POST | /admin/cache/flush | admin | Clear all cache entries |
| POST | /admin/cache/invalidate | admin | Invalidate cache entries for a specific access scope |

### 14.5 Reindex endpoint update

The existing POST /admin/reindex from Phase 4 is updated to trigger dual-write to both ChromaDB and FTS5, and to invalidate affected cache entries.

---

## 15. Data Privacy in LLM API Calls

### 15.1 The concern

When a developer asks a question, Arcana sends retrieved code and documentation chunks to the Gemini API as context. This means proprietary source code is transmitted to Google's servers.

### 15.2 Mitigations implemented in this phase

1. **Minimal data transmission:** Only the retrieved chunks (typically 5–10 short fragments, not full files) are sent. The total code sent per query is usually under 3000 tokens (~2000 words).

2. **No persistent storage by Google:** Per Google's Gemini API terms, data sent through the API is not used for model training and is not retained beyond the API call processing window.

3. **RBAC scoping:** The pre-retrieval filter ensures only chunks the user is authorized to see are sent to Gemini. This limits exposure to the user's own access scope.

4. **Audit trail:** Every query is logged with the sources accessed, providing a record of what data was sent to the LLM and when.

5. **Cache reduces exposure:** Cached responses serve repeated queries without any LLM API call, reducing the number of times proprietary code is transmitted.

### 15.3 Documentation for thesis

The thesis should include a dedicated section on data privacy that covers: what data leaves the network (chunk fragments sent to Gemini API), what Google's data handling policies guarantee, what mitigations are in place, and the production path to full data sovereignty (self-hosted LLM). See cross-phase limitation LX.1 in the Limitations Log.

---

## 16. Environment Variables (additions)

| Variable | Type | Default | Description |
|---|---|---|---|
| GEMINI_API_KEY | String | — (required) | Gemini API key for LLM calls |
| GEMINI_MODEL | String | gemini-2.0-flash | Gemini model for response generation |
| GEMINI_TEMPERATURE | Float | 0.2 | Response creativity (0.0–1.0) |
| GEMINI_MAX_OUTPUT_TOKENS | Integer | 2000 | Maximum response length |
| EMBEDDING_PROVIDER | String | gemini | Provider for query embeddings (gemini or openai) |
| EMBEDDING_MODEL | String | text-embedding-004 | Model for embedding generation |
| RETRIEVAL_VECTOR_TOP_K | Integer | 20 | Number of results from vector search |
| RETRIEVAL_BM25_TOP_K | Integer | 20 | Number of results from keyword search |
| RETRIEVAL_MIN_SIMILARITY | Float | 0.3 | Minimum cosine similarity threshold for vector results |
| RETRIEVAL_MIN_BM25 | Float | 0.0 | Minimum BM25 score threshold for keyword results |
| RRF_K | Integer | 60 | Reciprocal rank fusion constant (standard: 60) |
| RERANK_BACKEND | String | cross-encoder | Re-ranker: "cross-encoder" (local) or "cohere" |
| RERANK_CANDIDATES | Integer | 30 | Number of candidates passed to re-ranker |
| RERANK_TOP_K | Integer | 10 | Number of results after re-ranking |
| COHERE_API_KEY | String | — (optional) | Cohere API key (only needed if RERANK_BACKEND=cohere) |
| CONTEXT_TOKEN_BUDGET | Integer | 6000 | Max tokens for source materials in prompt |
| CACHE_SIMILARITY_THRESHOLD | Float | 0.95 | Cosine similarity threshold for cache hits |
| CACHE_TTL_HOURS | Integer | 24 | Cache entry time-to-live in hours |
| CACHE_ENABLED | Boolean | true | Toggle semantic cache on/off |

---

## 17. Acceptance Criteria

1. **BM25 index backfill:** Running the backfill script indexes all existing chunks from ChromaDB into FTS5. The count in FTS5 matches the count in ChromaDB. Searching for a known function name returns the correct chunk.

2. **Dual-write:** After backfill, triggering a Notion daily sync or GitHub re-index writes new/updated chunks to both ChromaDB and FTS5 atomically.

3. **Hybrid search:** A query for "getUserProfile" (exact function name) returns the function via BM25 even if the vector search ranks it lower. A query for "how does user authentication work" (semantic) returns relevant auth chunks via vector search even if they don't contain the exact words. Both result sets are merged.

4. **Reciprocal rank fusion:** Chunks appearing in both vector and BM25 results rank higher than chunks in only one. The fusion output contains no duplicate chunk IDs.

5. **Re-ranking:** The re-ranker re-orders the fused results. A deliberately irrelevant chunk injected into the candidate set (e.g., a config file for a query about auth) is ranked near the bottom after re-ranking.

6. **RBAC enforcement:** User A (scopes: backend-team) and User B (scopes: frontend-team) asking the same question receive entirely different results. No chunk from an unauthorized scope appears in any stage of the pipeline.

7. **Context assembly:** The assembled context respects the token budget. Architectural overview chunks appear first. Code and doc chunks are ordered by re-rank score. No truncation occurs mid-sentence or mid-function.

8. **Cross-reference boost:** A Notion doc about the auth service that references `src/auth/middleware.py` causes the corresponding code chunk to rank higher when the query is about authentication.

9. **Prompt construction:** The system prompt includes the user's role and team. Source materials are wrapped in numbered [SOURCE N] tags. The total prompt fits within Gemini's context window.

10. **Streaming response:** POST /query returns a valid SSE stream. Each chunk event contains text and any inline references. The final done event contains the complete references list and metadata.

11. **Citation accuracy:** Every [N] reference in the response text maps to a valid citation object with the correct file path, line numbers, or Notion page. No orphaned references (references to sources not in the context).

12. **Code block formatting:** Code snippets in the response have correct language annotations and source attribution headers.

13. **Semantic cache — hit:** Sending the same question twice (second time within TTL) returns the cached response. The second request does not call the Gemini API. Response latency for the cache hit is < 200ms.

14. **Semantic cache — similar query:** "How does auth work?" and "explain the authentication flow" both hit the same cache entry (cosine similarity > 0.95).

15. **Semantic cache — scope mismatch:** A cached response from User A (scopes: backend-team) is NOT served to User B (scopes: frontend-team), even if the query is identical.

16. **Semantic cache — TTL:** A cache entry older than CACHE_TTL_HOURS is not served. The stale entry is purged.

17. **Component renderer:** A query containing "show me query stats" returns a valid JSON component (e.g., metric_card type) instead of plain text. If JSON parsing fails, the system falls back to text.

18. **Empty results:** A query about a topic not in the knowledge base returns a helpful "not found" message without calling the Gemini API.

19. **Error handling:** A Gemini API timeout triggers one retry. A persistent failure returns an error SSE event. The client is never left hanging on an open stream.

20. **Cache management:** GET /admin/cache/stats returns hit count, miss count, hit rate, and estimated cost savings. POST /admin/cache/flush clears all entries. POST /admin/cache/invalidate with a scope clears entries matching that scope.

21. **Answer feedback:** POST /query/{id}/feedback stores the rating in audit_logs. GET /query/history shows past queries with timestamps and cache hit status.

22. **Tests:** At least 35 tests covering: FTS5 backfill and search, hybrid search execution, RRF fusion, re-ranking, RBAC filtering at every pipeline stage, context assembly (token budget, source ordering, truncation), prompt construction, Gemini streaming mock, citation extraction, cache hit/miss/scope/TTL, component renderer, empty results, error handling, dual-write, and answer feedback.

---

## 18. Technical Dependencies (additions)

| Package | Version | Purpose |
|---|---|---|
| google-genai | >=1.0 | Gemini API client (or google-generativeai) |
| sentence-transformers | >=3.0 | Cross-encoder re-ranking model (local) |
| cohere | >=5.0 | Cohere Rerank API client (optional, if RERANK_BACKEND=cohere) |
| sse-starlette | >=2.0 | Server-Sent Events support for FastAPI streaming |

Note: `tiktoken` (from Phase 2) is still used for approximate token counting during ingestion (chunk size validation). For prompt budget verification before Gemini API calls, the native `count_tokens()` method from `google-genai` is used instead, as it matches Gemini's actual tokenizer.

---

## 19. Estimated Effort

| Task | Estimate | Notes |
|---|---|---|
| BM25 index creation + backfill script | 4–5 hours | FTS5 table, backfill from ChromaDB, idempotency |
| DualStore abstraction + ingestion hooks | 3–4 hours | Wrap ChromaDB + FTS5, update Phase 2-3 ingestion code |
| Hybrid search (vector + BM25 parallel) | 4–5 hours | Async execution, query preprocessing, result normalization |
| Reciprocal rank fusion | 2–3 hours | RRF algorithm, deduplication, scoring |
| Re-ranker integration | 4–5 hours | Cross-encoder setup, Cohere fallback, candidate scoring |
| Context assembly | 5–6 hours | Token budget, source ordering, cross-ref boost, truncation |
| Prompt builder | 3–4 hours | System prompt, source formatting, role context, budget check |
| Gemini API integration + streaming | 5–6 hours | API client, streaming handler, error handling, retries |
| Stream + cite formatter | 5–6 hours | Citation extraction, code block formatting, reference section |
| Semantic cache | 5–6 hours | Cache collection, similarity check, scope validation, TTL, metrics |
| Component renderer | 3–4 hours | Visual query detection, JSON instruction, fallback handling |
| API endpoints (query, history, feedback, cache) | 4–5 hours | SSE endpoint, pagination, feedback storage |
| Test suite | 8–10 hours | 35+ tests across all pipeline stages |

**Total estimated effort: 55–69 hours (approximately 3–3.5 weeks at thesis pace)**

This is the largest phase by far. The effort is justified — this is the core of the product and the most technically substantive part of the thesis.

---

## 20. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Cross-encoder model too slow on CPU | Medium | Default model (MiniLM-L-6) is small and fast (~50ms for 40 pairs). If still slow, reduce RERANK_CANDIDATES. Cohere API is a faster fallback. |
| Gemini response quality varies with context assembly | Medium | Extensive prompt engineering iteration. Log the full prompts for underperforming queries to diagnose assembly issues. Feedback endpoint provides user signal. |
| BM25 and vector results have minimal overlap, RRF is ineffective | Low | This is actually a good sign — it means hybrid search is finding chunks that neither method alone would find. Monitor retrieval_source distribution in analytics. |
| Semantic cache serves stale answers after knowledge base changes | Medium | TTL of 24 hours limits staleness. Phase 7 adds active invalidation. Cache can be manually flushed via admin endpoint. |
| Token budget miscalculation causes Gemini context overflow | Low | tiktoken provides accurate token counts for the prompt. A hard ceiling check runs before API call — if over budget, the last chunk is removed. |
| Citation numbers in LLM output don't match source tags | Medium | The prompt explicitly numbers sources. Post-processing validates citation numbers against the source list. Orphaned references are stripped rather than shown with wrong links. |
| High Gemini API costs during development/testing | Low | Default model (gemini-2.0-flash) is cost-efficient. Semantic cache reduces API calls. Use mock responses in tests. |

---

## 21. Known Limitations

| ID | Limitation | Production path |
|---|---|---|
| L5.1 | No multi-turn conversation memory — each query is independent. The system doesn't remember previous questions in the session. | Add a conversation context buffer that includes the last 3–5 exchanges in the prompt. Store conversation state per-session (requires session management). |
| L5.2 | BM25 index uses SQLite FTS5 which doesn't scale to millions of chunks. | Migrate to Elasticsearch or Meilisearch for production-scale keyword search. The DualStore abstraction makes this a backend swap. |
| L5.3 | Cross-encoder re-ranker runs on CPU, limiting throughput under concurrent queries. | Deploy re-ranker on GPU instance or switch to Cohere Rerank API for production. Both are configurable today. |
| L5.4 | Semantic cache is per-instance (ChromaDB collection). Multiple server instances don't share cache. | Migrate cache to Redis with vector search support (e.g., Redis Stack) or a shared Pinecone namespace. |
| L5.5 | Component renderer supports only 5 component types. Complex visualizations (network graphs, Sankey diagrams) are not supported. | Extend the component spec incrementally. The renderer is designed as a type-dispatch system — adding new types means adding a new JSON schema and client-side renderer. |
| L5.6 | Citation accuracy depends on the LLM correctly referencing [SOURCE N] tags. It may occasionally hallucinate references or cite the wrong source. | Post-processing validation catches orphaned references. Production: add a citation verification step that checks if the cited content actually supports the claim. |
| L5.7 | The re-ranker and Gemini API both add latency. Total query time is ~2-4 seconds for a full pipeline execution. | Parallel processing where possible (already: vector + BM25). Semantic cache eliminates latency for repeated queries. Production: deploy re-ranker on GPU, use Gemini Flash model. |
| L5.8 | Proprietary code is sent to Google's Gemini API. See cross-phase limitation LX.1 for full discussion and production path. | Self-hosted LLM option (Ollama, vLLM). Google Cloud private endpoints. Enterprise API agreements with data processing addendums. |

These limitations are documented in the [Arcana Limitations & Design Decisions Log](./Arcana_Limitations_and_Design_Decisions.md).

---

*End of document*