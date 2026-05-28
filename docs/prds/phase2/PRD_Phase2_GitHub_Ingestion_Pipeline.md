# PRD — Phase 2: GitHub Ingestion Pipeline

**Product:** CodeMind — AI-Powered Developer Onboarding Platform
**Phase:** 2 of Tier 1
**Version:** 1.0
**Date:** March 2026

---

## 1. Overview

This document defines the requirements for the GitHub ingestion pipeline — the first data source connector for the CodeMind platform. This phase takes the scaffold established in Phase 1 and gives it the ability to connect to GitHub repositories, clone and analyze their contents, chunk code and documentation intelligently, generate embeddings, and store everything in ChromaDB with the metadata required for RBAC-filtered retrieval.

By the end of this phase, the system will have a populated knowledge base derived from real codebases that subsequent phases (Notion ingestion, RBAC, AI orchestration) can build upon.

---

## 2. Objectives

- Connect to GitHub via OAuth or personal access tokens and list accessible repositories
- Clone and traverse repository file trees, filtering out irrelevant content
- Chunk source code intelligently using AST (Abstract Syntax Tree) parsing, preserving function and class boundaries
- Chunk markdown and README files by section, preserving document hierarchy
- Generate vector embeddings for all chunks and store them in ChromaDB with rich metadata
- Tag every chunk with access scope metadata for future RBAC filtering
- Accept an uploaded architectural overview document and ingest it as high-priority context
- Register all connected repositories as data sources in PostgreSQL with sync status tracking

---

## 3. Scope

### 3.1 In scope

- GitHub authentication (OAuth app + personal access token support)
- Repository listing, selection, and cloning
- File tree traversal with configurable include/exclude filters
- AST-based code chunking for Python, JavaScript, and TypeScript (primary languages)
- Fallback line-based chunking for unsupported languages
- Markdown/README section-aware chunking
- Embedding generation via configurable provider (OpenAI or Voyage)
- ChromaDB storage with per-chunk metadata
- Architectural overview upload endpoint (accepts markdown or plain text)
- Data source registration and sync status tracking in PostgreSQL
- Re-indexing capability (full re-sync of a repository)
- Ingestion progress tracking and error handling

### 3.2 Out of scope

- Notion or any other data source (Phase 3)
- RBAC permission enforcement on queries (Phase 4 — but metadata tags are applied here)
- LLM-powered answers (Phase 5)
- Incremental/differential updates (Phase 7 — weekly updater)
- GitLab or Bitbucket support (Tier 3)

---

## 4. GitHub Authentication

### 4.1 Supported methods

| Method | Use case | Implementation |
|---|---|---|
| Personal access token (PAT) | Thesis MVP, single-user setup | Token set as `GITHUB_PAT` environment variable; never stored in the database |
| GitHub OAuth app | Future multi-user, multi-org | OAuth flow returns access token; refresh handled automatically |

For the thesis MVP, PAT-based authentication is sufficient. The OAuth flow should be designed but can be implemented as a stretch goal.

### 4.2 Required GitHub permissions

- `repo` — full access to private and public repositories
- `read:org` — list organization repositories (if applicable)

### 4.3 Token storage

- Token is stored exclusively in the `.env` file as `GITHUB_PAT=ghp_xxx` and never touches the database
- The `data_sources.config_json` field records only `github_login` and `selected_repos`
- Never logged, never included in API responses
- Read from `settings.github_pat` at ingestion time only, held in memory for the duration of the sync
- Rationale: single-tenant thesis project; environment variables are simpler and equally secure without the overhead of an encryption layer

---

## 5. Repository Connection Flow

### 5.1 API endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | /admin/sources/github | Admin API key | Register a GitHub connection (validates GITHUB_PAT from env, no token in request body) |
| GET | /admin/sources/github/{source_id}/repos | Admin API key | List all accessible repositories for a connected GitHub account |
| POST | /admin/sources/github/{source_id}/repos/select | Admin API key | Select which repositories to index (array of repo full names) |
| POST | /admin/sources/github/{source_id}/sync | Admin API key | Trigger full ingestion for all selected repositories |
| GET | /admin/sources/{source_id}/status | Admin API key | Get current sync status, progress, and error details |

### 5.2 Connection flow

1. Admin sets `GITHUB_PAT=ghp_xxx` in `.env` and calls POST /admin/sources/github with an `access_scope` label (e.g., "backend-team", "all-engineering")
2. System reads `GITHUB_PAT` from environment and validates it against the GitHub API
3. If valid: creates a data_sources record with type=github_repo, stores `github_login` and `selected_repos` in config_json (no token), sets status=pending
4. Admin calls GET .../repos to see all accessible repositories
5. Admin calls POST .../repos/select with the list of repos to index
6. Admin calls POST .../sync to begin ingestion
7. System clones each selected repo, processes files, generates embeddings, stores in ChromaDB
8. On completion: updates data_sources.status to active and sets last_synced_at

---

## 6. File Tree Traversal

### 6.1 Traversal rules

The system walks the cloned repository file tree and applies filters to determine which files to process.

**Default include patterns:**
- `*.py`, `*.js`, `*.ts`, `*.tsx`, `*.jsx` — source code (AST-parsed)
- `*.go`, `*.rs`, `*.java`, `*.rb`, `*.php`, `*.c`, `*.cpp`, `*.h` — source code (line-based chunking)
- `*.md`, `*.mdx`, `*.rst`, `*.txt` — documentation
- `*.yaml`, `*.yml`, `*.toml`, `*.json` — configuration files (chunked as whole files if < 200 lines)

**Default exclude patterns:**
- `node_modules/`, `vendor/`, `dist/`, `build/`, `.next/`, `__pycache__/`
- `*.min.js`, `*.min.css`, `*.map`
- `*.lock`, `package-lock.json`, `yarn.lock`
- Binary files (images, fonts, compiled assets)
- `.git/`, `.github/workflows/` (CI configs are low-value for onboarding)
- Files larger than 500KB (configurable threshold)

**Configurable overrides:**
- Admin can specify additional include/exclude patterns per repository via the config_json field
- A `.codemindignore` file in the repository root (same syntax as .gitignore) can override defaults

### 6.2 File metadata extraction

For every included file, the traversal extracts:
- `file_path` — relative path from repo root (e.g., `src/auth/middleware.py`)
- `language` — detected from extension
- `file_size` — in bytes
- `last_modified` — from git log (last commit that touched this file)

---

## 7. Code Chunking

### 7.1 AST-based chunking (Python, JavaScript, TypeScript)

The primary chunking strategy uses tree-sitter to parse source files into their Abstract Syntax Tree and extract semantically meaningful units.

**Chunk boundaries:**
- Each top-level function becomes one chunk
- Each class becomes one chunk (including all its methods)
- If a class exceeds 150 lines, each method becomes a separate chunk with the class docstring/signature prepended as context
- Module-level code (imports, constants, global variables) between functions/classes becomes one chunk if > 5 lines
- Decorators are included with the function/class they decorate

**Per-chunk content:**
- The raw source code of the function/class
- A context header prepended to every chunk: `# File: {file_path} | Function: {name} | Lines: {start}-{end}`
- The file's import statements (prepended as context, not counted toward chunk size)

**Chunk metadata (stored in ChromaDB):**
- `source_type`: "code"
- `repo`: repository full name (e.g., "org/backend-api")
- `file_path`: relative path
- `language`: "python", "javascript", "typescript"
- `chunk_type`: "function", "class", "method", "module_level"
- `symbol_name`: function/class/method name
- `line_start`: starting line number
- `line_end`: ending line number
- `access_scope`: inherited from the data_source record
- `last_modified`: from git log
- `ingested_at`: UTC timestamp of ingestion

### 7.2 Line-based fallback chunking

For languages without tree-sitter support (Go, Rust, Java, Ruby, PHP, C/C++), the system falls back to line-based chunking.

**Strategy:**
- Split file into chunks of 80–120 lines with 10-line overlap between consecutive chunks
- Prefer splitting at blank lines or lines that look like function/class boundaries (heuristic: lines matching common declaration patterns)
- Prepend the same context header as AST chunks

**Metadata:** Same as AST chunks, but `chunk_type` = "line_block" and `symbol_name` = null.

### 7.3 Chunk size constraints

| Parameter | Value | Rationale |
|---|---|---|
| Minimum chunk size | 5 lines / 50 tokens | Avoid trivially small chunks that waste retrieval slots |
| Maximum chunk size | 200 lines / 2000 tokens | Stay within embedding model context limits |
| Overlap (line-based only) | 10 lines | Preserve context across chunk boundaries |
| Class split threshold | 150 lines | Long classes are better searched by method |

Chunks that fall below the minimum after splitting are merged with their nearest neighbor. Chunks that exceed the maximum are further split at the nearest blank line.

---

## 8. Documentation Chunking

### 8.1 Markdown and README files

Documentation files are chunked by heading hierarchy, preserving the document structure.

**Strategy:**
- Split at H1 (`#`) and H2 (`##`) headings — each section becomes one chunk
- If a section exceeds 1500 tokens, further split at H3 (`###`) boundaries
- If still too large, split at paragraph boundaries
- Prepend a breadcrumb context header: `# Doc: {file_path} > {H1 title} > {H2 title}`

**Per-chunk content:**
- The section text including its heading
- Code blocks within the section are preserved inline
- Links and references are preserved as-is

**Metadata:**
- `source_type`: "documentation"
- `repo`: repository full name
- `file_path`: relative path
- `chunk_type`: "doc_section"
- `section_heading`: the heading text
- `heading_level`: 1, 2, or 3
- `parent_heading`: the parent section's heading (for H2/H3 chunks)
- `access_scope`: inherited from the data_source record
- `last_modified`: from git log
- `ingested_at`: UTC timestamp

### 8.2 Configuration files

YAML, TOML, and JSON config files under 200 lines are stored as single chunks with `chunk_type` = "config". Files over 200 lines are split at top-level keys.

---

## 9. Architectural Overview Upload

### 9.1 Endpoint

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | /admin/sources/overview | Admin API key | Upload a markdown or text file as the architectural overview |
| PUT | /admin/sources/overview | Admin API key | Replace the existing overview |

### 9.2 Behavior

- Accepts a markdown or plain text file (max 50KB)
- Chunked using the same documentation chunking strategy (Section 8.1)
- Stored in the `doc_chunks` collection with `source_type` = "architectural_overview"
- Tagged with `access_scope` = "all" (visible to every user regardless of RBAC)
- These chunks receive a retrieval boost (+0.15 to similarity score) during query time, ensuring architectural context is always prioritized

### 9.3 Priority rationale

The architectural overview is the highest-value document in the knowledge base. It provides the mental model that makes code-level answers meaningful. A developer asking "how does the payment service work" should get both the architectural explanation (from the overview) and the specific code references (from the repo). The retrieval boost ensures the overview is always represented in the context window.

---

## 10. Embedding Pipeline

### 10.1 Embedding generation

| Parameter | Value |
|---|---|
| Default provider | OpenAI |
| Default model | text-embedding-3-small |
| Dimensions | 1536 |
| Alternative provider | Voyage AI (voyage-code-2, optimized for code) |
| Batch size | 100 chunks per API call |
| Rate limiting | Configurable delay between batches (default: 0.5s) |

### 10.2 Embedding text preparation

Before embedding, each chunk's text is preprocessed:

1. The context header is prepended (file path, function name, etc.)
2. Import statements are prepended for code chunks
3. Excessive whitespace is normalized (multiple blank lines collapsed to one)
4. The total text is truncated to the model's context limit (8191 tokens for text-embedding-3-small)

### 10.3 Storage in ChromaDB

Each chunk is stored as a document in the appropriate ChromaDB collection (`code_chunks` or `doc_chunks`) with:
- `id`: deterministic hash of `{repo}:{file_path}:{chunk_type}:{symbol_name}:{line_start}` — ensures re-ingestion updates rather than duplicates
- `document`: the preprocessed text
- `embedding`: the generated vector
- `metadata`: all fields listed in Sections 7 and 8

### 10.4 Cost estimation

| Scenario | Chunks (est.) | Tokens (est.) | Cost (text-embedding-3-small) |
|---|---|---|---|
| Small repo (500 files) | ~2,000 | ~1.5M | ~$0.03 |
| Medium repo (2,000 files) | ~8,000 | ~6M | ~$0.12 |
| Large repo (10,000 files) | ~40,000 | ~30M | ~$0.60 |
| 5 medium repos (typical org) | ~40,000 | ~30M | ~$0.60 |

These costs are per full ingestion. Incremental updates (Phase 7) will be significantly cheaper.

---

## 11. Sync Status and Progress Tracking

### 11.1 Status model

The `data_sources.status` field tracks the overall state:

| Status | Meaning |
|---|---|
| pending | Source registered but never synced |
| syncing | Ingestion currently in progress |
| active | Last sync completed successfully |
| error | Last sync failed (see error details) |
| stale | Active but last sync > 7 days ago (set by weekly updater in Phase 7) |

### 11.2 Progress tracking

During ingestion, the system tracks progress in a `sync_progress` JSON field on the data_sources record:

```
{
  "total_repos": 3,
  "completed_repos": 1,
  "current_repo": "org/backend-api",
  "current_repo_progress": {
    "total_files": 450,
    "processed_files": 230,
    "total_chunks": 890,
    "embedded_chunks": 650,
    "errors": []
  },
  "started_at": "2026-03-15T10:30:00Z"
}
```

The GET /admin/sources/{source_id}/status endpoint returns this progress object alongside the overall status.

### 11.3 Error handling

- File-level errors (parse failure, encoding issues) are logged but don't halt ingestion — the file is skipped and recorded in the errors array
- Repository-level errors (clone failure, auth failure) halt that repo's ingestion and continue with the next
- If all repos fail, status is set to "error" with a summary
- All errors are also recorded in the application log with full stack traces

---

## 12. Data Source Schema Addition

This phase adds a `sync_progress` column to the `data_sources` table defined in Phase 1:

| Column | Type | Constraints | Description |
|---|---|---|---|
| sync_progress | JSON | Nullable | Progress tracking object during active syncs |

This requires an Alembic migration adding the column with a nullable default.

---

## 13. Acceptance Criteria

1. **GitHub connection:** POST /admin/sources/github with `GITHUB_PAT` set in environment returns 201 and creates a data_sources record. An unset or invalid `GITHUB_PAT` returns 400/401 with a clear error message.
2. **Repository listing:** GET .../repos returns all accessible repositories with names, visibility, and default branch.
3. **Repository selection:** POST .../repos/select with an array of repo names stores the selection in config_json.
4. **Ingestion — code:** After sync, Python files are chunked by function/class boundaries using tree-sitter. A file with 5 functions produces 5 code chunks (plus module-level if applicable). Each chunk has all required metadata fields populated.
5. **Ingestion — documentation:** README.md files are chunked by heading. A README with 3 H2 sections produces 3 doc chunks with correct section_heading and parent_heading metadata.
6. **Ingestion — fallback:** A Go file is chunked by line blocks with 10-line overlap. Chunks respect the 80–120 line target range.
7. **Chunk IDs are deterministic:** Re-running sync on the same repository produces the same chunk IDs, updating existing chunks rather than creating duplicates.
8. **Embeddings:** All chunks have non-null embeddings in ChromaDB. The embedding dimension matches the configured model.
9. **Access scope tagging:** Every chunk's metadata contains the access_scope from its parent data_source record.
10. **Architectural overview:** POST /admin/sources/overview with a markdown file stores chunks in doc_chunks with source_type="architectural_overview" and access_scope="all".
11. **Progress tracking:** During sync, GET .../status returns real-time progress including files processed, chunks generated, and any errors.
12. **Error resilience:** A repository with one unparseable file completes ingestion for all other files. The error is recorded in sync_progress.errors.
13. **Cost control:** Embedding API calls are batched (100 per call) with configurable rate limiting.
14. **Tests:** At least 20 tests covering: GitHub auth validation, file tree filtering, AST chunking (Python function, class, long class split), line-based fallback, markdown chunking, chunk ID determinism, embedding pipeline mock, overview upload, and sync status tracking.

---

## 14. Technical Dependencies (additions to Phase 1)

| Package | Version | Purpose |
|---|---|---|
| PyGithub | >=2.0 | GitHub API client for auth, repo listing, and metadata |
| gitpython | >=3.1 | Repository cloning and git log access |
| tree-sitter | >=0.23 | AST parsing framework |
| tree-sitter-python | >=0.23 | Python grammar for tree-sitter |
| tree-sitter-javascript | >=0.23 | JavaScript grammar for tree-sitter |
| tree-sitter-typescript | >=0.23 | TypeScript grammar for tree-sitter |
| tiktoken | >=0.8 | Token counting for chunk size validation |
| python-multipart | >=0.0.9 | File upload support for overview endpoint |

---

## 15. Estimated Effort

| Task | Estimate | Notes |
|---|---|---|
| GitHub auth + repo listing endpoints | 4–6 hours | OAuth app setup, token validation, repo list |
| File tree traversal + filters | 3–4 hours | Walk, filter, .codemindignore parsing |
| AST-based code chunking (Python) | 6–8 hours | tree-sitter setup, function/class extraction, context headers |
| AST-based code chunking (JS/TS) | 4–5 hours | Grammar differences, JSX handling |
| Line-based fallback chunking | 2–3 hours | Simpler logic, overlap handling |
| Markdown documentation chunking | 3–4 hours | Heading hierarchy, breadcrumb context |
| Embedding pipeline | 4–5 hours | Batching, rate limiting, ChromaDB storage, deterministic IDs |
| Architectural overview upload | 2–3 hours | Endpoint, chunking, priority tagging |
| Sync status + progress tracking | 3–4 hours | Progress JSON, status transitions, error handling |
| Alembic migration | 0.5 hours | Add sync_progress column |
| Test suite | 6–8 hours | 20+ tests across all components |

**Total estimated effort: 38–50 hours (approximately 2 weeks at thesis pace)**

---

## 16. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| tree-sitter grammar inconsistencies across languages | Medium | Start with Python only (best supported), add JS/TS after validation |
| Large repositories overwhelming memory during clone | Medium | Use shallow clones (depth=1), process files streaming rather than loading all into memory |
| Embedding API rate limits during large ingestions | Low | Configurable batch delay, exponential backoff on 429 responses |
| Non-UTF-8 file encodings causing parse errors | Low | Detect encoding with chardet, skip files that can't be decoded cleanly |
| Chunk quality varies significantly across codebases | Medium | Log chunk size distribution during ingestion; add a post-ingestion quality report to the status endpoint |

---

*End of document*