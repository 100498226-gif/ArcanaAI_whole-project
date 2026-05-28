# PRD — Phase 3: Notion Ingestion Pipeline

**Product:** Arcana — AI-Powered Developer Onboarding Platform
**Phase:** 3 of Tier 1
**Version:** 1.1
**Date:** March 2026
**LLM Provider:** Gemini APIs
**Related:** [Arcana Limitations & Design Decisions Log](./Arcana_Limitations_and_Design_Decisions.md) — entries L3.1 through L3.6

---

## 1. Overview

This document defines the requirements for the Notion ingestion pipeline — the second data source connector for Arcana. While Phase 2 gave the system access to codebases, this phase gives it access to the institutional knowledge that lives outside of code: product requirement documents (PRDs), architecture decision records, runbooks, onboarding guides, API documentation, and team wikis.

The combination of code (GitHub) and documentation (Notion) is what makes Arcana's answers genuinely useful. A developer asking "how does the payment service work" should get both the code-level references from Phase 2 and the design rationale, product context, and architectural decisions from Notion. This phase makes that possible.

By the end of this phase, the system will have a two-source knowledge base capable of cross-referencing code and documentation in retrieval.

---

## 2. Objectives

- Connect to a Notion workspace via integration token and list accessible pages and databases
- Traverse Notion's page hierarchy, extracting content from pages, sub-pages, and databases
- Convert Notion's block-based content model into clean markdown for chunking
- Chunk documentation by heading hierarchy, preserving document structure and context
- Generate vector embeddings and store in ChromaDB with rich metadata
- Tag every chunk with access scope metadata for future RBAC filtering
- Detect cross-references between Notion pages and GitHub repositories (file paths, repo names mentioned in docs)
- Register the connected workspace as a data source in PostgreSQL with sync status tracking
- Reuse the ingestion infrastructure (embedding pipeline, progress tracking, error handling) established in Phase 2

---

## 3. Scope

### 3.1 In scope

- Notion integration token authentication
- Workspace page and database listing with hierarchy
- Admin-configurable scope: select which top-level pages or databases to index
- Notion block-to-markdown conversion for all common block types
- Section-aware document chunking (same strategy as Phase 2 markdown chunking, adapted for Notion's structure)
- Embedded database content extraction (tables within pages)
- Embedding generation and ChromaDB storage in the `doc_chunks` collection
- Cross-reference detection between Notion content and GitHub repos
- Data source registration and sync status tracking
- Re-indexing capability (full re-sync of selected pages)

### 3.2 Out of scope (with rationale)

- **Notion comments or discussion threads** — conversational, often ephemeral, low signal-to-noise ratio for onboarding context. See limitation L3.3.
- **Notion database views, filters, or formulas** — views are UI presentation settings, not knowledge content. Raw row data plus computed formula/rollup results are captured. See limitation L3.5.
- **Real-time sync via Notion webhooks** — not available in Notion's API. Daily polling is used instead. See limitation L3.2.
- **Notion file attachments or embedded PDFs** — requires OCR/PDF-specific tooling disproportionate to thesis scope. See limitation L3.4.
- **Any write operations to Notion** — Arcana is read-only
- **Linear/Jira or Slack ingestion** — Tier 3

---

## 4. Notion Authentication

### 4.1 Authentication method

Arcana uses a Notion internal integration token. This is the simplest and most appropriate method for a single-tenant thesis MVP.

| Parameter | Value |
|---|---|
| Auth method | Internal integration token |
| Token storage | `NOTION_TOKEN` environment variable in `.env` (see limitation L3.1) |
| API version | 2022-06-28 (latest stable) |
| Base URL | https://api.notion.com/v1 |

The token is stored as an environment variable (consistent with the GitHub PAT approach from Phase 2, see limitation L2.1). It never touches the database.

### 4.2 Required capabilities

When creating the Notion integration, the following capabilities must be enabled:

- **Read content** — access page and database content
- **Read user information** — optional, used for attributing document authorship in metadata

The integration must be explicitly shared with the pages/databases the admin wants indexed. Notion's permission model means the integration only sees content it has been invited to — this provides a natural access boundary.

### 4.3 Important Notion API constraints

| Constraint | Value | Implication |
|---|---|---|
| Rate limit | 3 requests/second | Must throttle API calls; use configurable delay between requests |
| Block children pagination | 100 blocks per page | Large pages require multiple paginated requests |
| Search endpoint limit | Returns max 100 results per call | Must paginate for large workspaces |
| No webhook support | N/A | Cannot do real-time sync; daily polling used instead (see limitation L3.2) |

---

## 5. Workspace Connection Flow

### 5.1 API endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | /admin/sources/notion | Admin API key | Register a Notion workspace connection (validates token) |
| GET | /admin/sources/notion/{source_id}/pages | Admin API key | List all accessible top-level pages and databases |
| POST | /admin/sources/notion/{source_id}/pages/select | Admin API key | Select which pages/databases to index (array of page IDs) |
| POST | /admin/sources/notion/{source_id}/sync | Admin API key | Trigger full ingestion for all selected pages |
| GET | /admin/sources/{source_id}/status | Admin API key | Get current sync status, progress, and error details (shared endpoint from Phase 2) |

### 5.2 Connection flow

1. Admin calls POST /admin/sources/notion (system reads `NOTION_TOKEN` from env)
2. System validates the token by calling the Notion API `/v1/users/me` endpoint
3. If valid: creates a `data_sources` record with `type=notion_workspace`, sets `status=pending`
4. Admin calls GET .../pages to see all pages and databases the integration has access to
5. Response includes a hierarchical tree: top-level pages with their children (2 levels deep for preview)
6. Admin calls POST .../pages/select with the IDs of pages/databases to index, plus an `access_scope` label
7. Admin calls POST .../sync to begin ingestion
8. System traverses selected pages recursively, extracts content, chunks, embeds, stores
9. On completion: updates `data_sources.status` to `active` and sets `last_synced_at`

---

## 6. Notion Content Extraction

### 6.1 Notion's content model

Notion pages are composed of blocks. Each block has a type and can contain children (nested blocks). Understanding this hierarchy is essential for quality chunking.

**Block types to extract:**

| Block type | Extraction approach |
|---|---|
| paragraph | Direct text extraction with rich text formatting |
| heading_1, heading_2, heading_3 | Extract as markdown headings (used for chunk boundaries) |
| bulleted_list_item, numbered_list_item | Convert to markdown list syntax, preserve nesting |
| to_do | Convert to markdown checklist `- [ ]` / `- [x]` |
| toggle | Extract heading + collapsed content (treat toggle as a section) |
| code | Extract as fenced code block with language annotation |
| quote | Convert to markdown blockquote |
| callout | Extract text with callout type prefix (e.g., "[INFO]", "[WARNING]") |
| divider | Insert markdown `---` (used as a secondary chunk boundary hint) |
| table | Convert to markdown table syntax |
| child_page | Recurse into the child page (new document in the hierarchy) |
| child_database | Extract database rows as structured content (see Section 6.3) |
| bookmark | Extract URL and title as markdown link |
| image | Store alt text and URL in metadata; skip binary content |
| equation | Extract LaTeX source as inline text |

**Block types to skip:**
- embed (external embeds are not extractable)
- video, audio, file (binary content — see limitation L3.4)
- breadcrumb, table_of_contents, link_to_page (navigation elements, no content value)
- synced_block (extract the source content only, avoid duplicates)
- column_list / column (flatten columns into sequential content)

### 6.2 Rich text handling

Notion's rich text objects contain annotations (bold, italic, code, strikethrough, underline, color) and links. The extractor converts these to markdown:

- **Bold** → `**text**`
- **Italic** → `*text*`
- **Code** → `` `text` ``
- **Strikethrough** → `~~text~~`
- **Link** → `[text](url)`
- **Mentions** (user, page, date) → extract the plain text representation
- Colors and underline → stripped (no markdown equivalent, low information value)

### 6.3 Database content extraction

Notion databases (tables with properties) are extracted as structured content. Views and filter configurations are not extracted — only the raw row data and computed values (see limitation L3.5).

1. Extract the database title and description
2. For each row (page in the database):
   - Extract all property values (title, text, number, select, multi-select, date, URL, email, checkbox, relation)
   - Formula and rollup properties: extract the computed result value (the API returns these)
   - Skip created_by/last_edited_by properties (meta, not knowledge content)
   - Convert the row to a readable format: `**{title}**: {property1}: {value1}, {property2}: {value2}, ...`
3. If a database row (page) also has page content (blocks inside it), extract that content using the standard block extraction and associate it with the row
4. For large databases (1000+ rows), group short rows (<50 tokens each) into batches of 10–20 per chunk to avoid producing excessive tiny chunks

**Database metadata:**
- `chunk_type`: "database_row" or "database_page" (if row has content)
- `database_title`: the name of the database
- `row_title`: the title property of the row

### 6.4 Page hierarchy and recursion

The extractor traverses pages recursively:

1. Start with the selected top-level pages
2. For each page, fetch all blocks using paginated `/v1/blocks/{block_id}/children`
3. When a `child_page` block is encountered, recurse into it
4. Track the full path: `Top Level Page > Sub Page > Sub-Sub Page`
5. Maximum recursion depth: 5 levels (configurable). Pages deeper than this are skipped with a warning. See limitation L3.6.
6. Track visited page IDs to avoid infinite loops from circular references

---

## 7. Document Chunking

### 7.1 Chunking strategy

The chunking strategy mirrors Phase 2's markdown documentation chunking, adapted for Notion's richer structure.

**Primary split boundaries:**
- Heading 1 blocks — always start a new chunk
- Heading 2 blocks — start a new chunk
- Divider blocks — start a new chunk if the current chunk exceeds 500 tokens
- Toggle blocks — each toggle becomes its own chunk (heading + collapsed content)

**Secondary split (for oversized sections):**
- If a section exceeds 1500 tokens, split at Heading 3 boundaries
- If still too large, split at paragraph boundaries
- If a single paragraph exceeds 1500 tokens (rare), split at sentence boundaries

**Context preservation:**
Every chunk gets a breadcrumb header prepended:
```
# Workspace: {workspace_name} > {page_title} > {section_heading}
# Source: Notion | Page ID: {page_id} | Last edited: {last_edited_time}
```

For chunks from child pages, the full hierarchy path is included:
```
# Workspace: {workspace_name} > {parent_page} > {child_page} > {section_heading}
```

### 7.2 Chunk metadata (stored in ChromaDB doc_chunks collection)

| Field | Description |
|---|---|
| source_type | "notion" |
| workspace | Workspace name |
| page_id | Notion page ID |
| page_title | Page title |
| page_path | Full hierarchy path (e.g., "Engineering Wiki > Backend > Auth Service") |
| chunk_type | "doc_section", "toggle_section", "database_row", "database_page" |
| section_heading | The heading text of this section |
| heading_level | 1, 2, or 3 |
| parent_heading | The parent section's heading (for H2/H3 chunks) |
| access_scope | Inherited from the data_source record |
| last_edited_time | Notion's last_edited_time for the page |
| last_edited_by | Name of the last editor (if available) |
| ingested_at | UTC timestamp of ingestion |
| cross_references | JSON array of detected references to GitHub files/repos (see Section 8) |

### 7.3 Chunk size constraints

Same constraints as Phase 2 for consistency:

| Parameter | Value |
|---|---|
| Minimum chunk size | 50 tokens |
| Maximum chunk size | 2000 tokens |
| Target chunk size | 500–1000 tokens |

Chunks below the minimum are merged with the nearest sibling section. Chunks above the maximum are split at the next available boundary.

### 7.4 Deterministic chunk IDs

Following the same pattern as Phase 2, chunk IDs are deterministic hashes:
`{workspace}:{page_id}:{section_heading}:{heading_level}:{chunk_index}`

This ensures re-ingestion updates existing chunks rather than creating duplicates.

---

## 8. Cross-Reference Detection

### 8.1 Purpose

One of Arcana's strengths is cross-referencing code and documentation. When a Notion document mentions a file path, repository name, or service name that exists in the GitHub knowledge base, that relationship is captured.

### 8.2 Detection rules

During chunking, the system scans each chunk's text for:

| Pattern | Example | Stored as |
|---|---|---|
| File paths | `src/auth/middleware.py`, `/api/routes/payments.ts` | `{"type": "file_path", "value": "src/auth/middleware.py", "repo": "org/backend"}` |
| Repository references | `backend-api`, `org/frontend` | `{"type": "repo", "value": "org/backend-api"}` |
| GitHub URLs | `github.com/org/repo/blob/main/file.py` | Parsed into file_path + repo reference |
| Code block annotations | ` ```python # from src/utils/helpers.py ``` ` | Extract the file path from the comment |

### 8.3 Matching logic

- File paths are matched against the `file_path` metadata of chunks in the `code_chunks` ChromaDB collection
- Repository names are matched against registered data sources with `type=github_repo`
- Matches are stored in the `cross_references` metadata field on the Notion chunk
- Matching is fuzzy: `middleware.py` matches `src/auth/middleware.py` (suffix match)

### 8.4 Retrieval impact

Cross-references are not used during Phase 3 (retrieval isn't built yet). They are stored as metadata so that Phase 5 (AI orchestration) can use them to boost retrieval — when a developer asks about a topic, chunks that cross-reference each other can be co-retrieved for richer context.

---

## 9. Embedding and Storage

### 9.1 Embedding pipeline

The Notion embedding pipeline reuses the infrastructure built in Phase 2:

- Same configurable provider and model (Gemini embedding or alternatives)
- Same batching (100 chunks per API call) and rate limiting
- Same text preprocessing (context header prepended, whitespace normalized, truncated to model limit)

### 9.2 Storage

Notion chunks are stored in the `doc_chunks` ChromaDB collection (created in Phase 1). This is the same collection used for GitHub documentation (README files) and architectural overviews, but the `source_type` metadata field distinguishes them:

| source_type value | Origin |
|---|---|
| "documentation" | GitHub README and markdown files (Phase 2) |
| "architectural_overview" | Uploaded overview document (Phase 2) |
| "notion" | Notion pages and databases (this phase) |

### 9.3 Cost estimation

| Scenario | Pages (est.) | Chunks (est.) | Tokens (est.) | Cost (Gemini embedding) |
|---|---|---|---|---|
| Small workspace (50 pages) | 50 | ~300 | ~250K | ~$0.01 |
| Medium workspace (200 pages) | 200 | ~1,200 | ~1M | ~$0.04 |
| Large workspace (1,000 pages) | 1,000 | ~6,000 | ~5M | ~$0.15 |

Notion documents tend to produce fewer but larger chunks compared to code, since documentation is more prose-heavy.

---

## 10. Sync and Update Strategy

### 10.1 Initial sync

The initial sync (triggered via POST .../sync) is a full ingestion: every selected page is traversed, extracted, chunked, and embedded from scratch.

### 10.2 Daily polling updates

After the initial sync, Arcana checks for changes on a daily schedule. The daily sync process:

1. For each selected page, call the Notion API to check `last_edited_time`
2. Compare against the `last_synced_at` timestamp stored in `data_sources`
3. Pages where `last_edited_time > last_synced_at` are re-processed (full page re-extraction, re-chunking, re-embedding)
4. Pages that haven't changed are skipped entirely (no API calls beyond the timestamp check)
5. Chunk IDs are deterministic, so re-processing a page updates existing chunks rather than creating duplicates
6. On completion, update `last_synced_at` on the data_source record

This approach is efficient because only changed pages are re-processed. The timestamp check itself is lightweight (one API call per page listing, not per page).

**Schedule:** Configurable via `NOTION_SYNC_INTERVAL_HOURS` environment variable (default: 24 hours). Can be reduced to hourly for production deployments.

Note: This daily polling mechanism is a precursor to the more comprehensive weekly updater in Phase 7, which adds change analysis, update proposals, and human review. The daily sync here is a simpler "detect and re-process" loop without the proposal/review workflow.

### 10.3 Notion-specific error handling

| Error type | Behavior |
|---|---|
| Page not shared with integration | Skip page, log warning, record in errors array |
| Rate limit (429) | Exponential backoff: 1s, 2s, 4s, 8s, max 30s. Retry up to 5 times |
| Block type unsupported | Skip block, log as debug (not an error — expected for embeds, video, etc.) |
| Pagination failure mid-page | Retry once, then skip remaining blocks for that page with a warning |
| Circular reference detected | Skip the revisited page, log warning |
| Page depth exceeds limit | Skip page, log warning, record in skipped_pages.depth_exceeded |

---

## 11. Environment Variables (additions to Phase 2)

| Variable | Type | Default | Description |
|---|---|---|---|
| NOTION_TOKEN | String | — (required) | Notion internal integration token |
| NOTION_SYNC_INTERVAL_HOURS | Integer | 24 | Hours between automated sync runs |
| NOTION_MAX_DEPTH | Integer | 5 | Maximum page hierarchy recursion depth |
| NOTION_REQUEST_DELAY_MS | Integer | 350 | Delay between Notion API requests (to respect 3 req/s limit) |

---

## 12. Acceptance Criteria

1. **Notion connection:** POST /admin/sources/notion validates the token against the Notion API. Valid token returns 201 and creates a data_sources record. Invalid token returns 401 with clear error message.
2. **Page listing:** GET .../pages returns all accessible top-level pages and databases with titles, IDs, and child count (2 levels deep).
3. **Page selection:** POST .../pages/select stores the selected page IDs and access_scope in the data_source config_json.
4. **Block extraction:** A Notion page with paragraphs, headings, code blocks, lists, and a table is converted to clean markdown. Code blocks retain language annotations. Tables render as markdown tables. Lists preserve nesting.
5. **Toggle handling:** Toggle blocks are extracted as self-contained sections with the toggle heading and collapsed content.
6. **Database extraction:** A Notion database with 10 rows produces structured chunks with property values including computed formula results. Rows that contain page content produce additional content chunks.
7. **Hierarchy traversal:** A 3-level page hierarchy (parent > child > grandchild) is fully traversed. Each chunk's page_path reflects the full hierarchy. A 6-level hierarchy stops at level 5 with a warning logged.
8. **Chunking:** A page with 4 H2 sections produces 4 chunks. Each chunk has the breadcrumb context header, correct section_heading, and proper heading_level metadata.
9. **Cross-references:** A Notion page mentioning `src/auth/middleware.py` has that file path stored in its cross_references metadata. A mention of a registered repo name is also captured.
10. **Deterministic IDs:** Re-running sync on the same workspace produces the same chunk IDs, updating existing chunks rather than duplicating.
11. **Daily sync:** After initial ingestion, the daily sync correctly identifies pages with `last_edited_time` newer than `last_synced_at`, re-processes only those pages, and skips unchanged ones.
12. **Rate limiting:** The system respects Notion's 3 req/s limit. A large workspace sync does not trigger 429 errors (or handles them gracefully with backoff).
13. **Progress tracking:** During sync, GET .../status returns real-time progress including pages processed, pages skipped (unchanged), chunks generated, cross-references found, and any errors.
14. **Error resilience:** A workspace with one inaccessible page (not shared with integration) completes ingestion for all other pages. The inaccessible page is recorded in errors.
15. **Tests:** At least 20 tests covering: Notion auth validation, block-to-markdown conversion (paragraph, heading, code, list, table, toggle, callout, database row), hierarchy traversal with depth limit, chunk boundary detection, cross-reference detection, deterministic IDs, daily sync change detection, rate limit handling, and sync status tracking.

---

## 13. Technical Dependencies (additions to Phase 2)

| Package | Version | Purpose |
|---|---|---|
| notion-client | >=2.0 | Official Notion API client for Python |
| apscheduler | >=3.10 | Scheduled job runner for daily sync (if not already added) |

All other infrastructure is reused from Phase 1–2 (SQLAlchemy, ChromaDB, tiktoken, etc.).

---

## 14. Estimated Effort

| Task | Estimate | Notes |
|---|---|---|
| Notion auth + page listing endpoints | 3–4 hours | Token validation, recursive page tree |
| Block-to-markdown converter | 6–8 hours | 15+ block types, rich text handling, edge cases |
| Database content extractor | 3–4 hours | Property type handling, row-with-content pages, row batching |
| Page hierarchy traversal | 3–4 hours | Recursive fetch, depth limit, circular reference detection |
| Document chunking (Notion-adapted) | 3–4 hours | Mostly reuses Phase 2 logic, adds breadcrumb headers |
| Cross-reference detection | 3–4 hours | Pattern matching, fuzzy file path matching against code_chunks |
| Embedding pipeline integration | 1–2 hours | Reuses Phase 2 pipeline, configure for doc_chunks |
| Daily sync scheduler + change detection | 2–3 hours | APScheduler setup, last_edited_time comparison logic |
| Sync status + progress tracking | 1–2 hours | Reuses Phase 2 pattern, add skipped_pages tracking |
| Test suite | 6–8 hours | 20+ tests, mock Notion API responses |

**Total estimated effort: 31–43 hours (approximately 1.5 weeks at thesis pace)**

Note: This is faster than Phase 2 because the embedding pipeline, sync tracking, and chunking patterns are already built. The main new work is Notion-specific: block extraction and the content model conversion.

---

## 15. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Notion API rate limit (3 req/s) makes large workspace sync slow | Medium | Implement configurable request delay; show estimated time in progress tracking; run syncs asynchronously |
| Notion block types change or new types are added | Low | Unknown block types are skipped gracefully with a log; the converter is a type-dispatch dictionary that's easy to extend |
| Rich text edge cases (nested formatting, inline equations, mentions) | Low | Degrade gracefully to plain text if markdown conversion fails for a specific rich text span |
| Deeply nested page hierarchies (>5 levels) causing excessive API calls | Low | Configurable depth limit; pages beyond the limit are skipped with a warning (see limitation L3.6) |
| Large databases (1000+ rows) producing too many small chunks | Medium | Group short rows into batches of 10–20 per chunk |
| Daily sync re-processes entire pages instead of individual blocks | Low | Notion API doesn't expose block-level change timestamps; page-level re-processing is the finest granularity available. The cost is minimal since only changed pages are touched. |

---

## 16. Known Limitations

This phase has six documented limitations (L3.1 through L3.6) in the [Arcana Limitations & Design Decisions Log](./Arcana_Limitations_and_Design_Decisions.md). Each includes the rationale for the decision and a clear production path. Key entries:

- **L3.1** — Notion token as env variable (consistent with GitHub PAT approach)
- **L3.2** — Daily polling instead of real-time webhooks (Notion API limitation)
- **L3.3** — No comment/discussion extraction (low signal-to-noise)
- **L3.4** — No file attachment/PDF extraction (disproportionate complexity)
- **L3.5** — Database views/filters not captured (raw data is the superset)
- **L3.6** — 5-level hierarchy depth limit (configurable, covers vast majority of workspaces)

---

*End of document*