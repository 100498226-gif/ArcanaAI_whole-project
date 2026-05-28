# Arcana — Limitations & Design Decisions Log

**Purpose:** This document tracks all known limitations, conscious tradeoffs, and deferred capabilities across every phase of the Arcana MVP. These are not bugs or oversights — they are deliberate scoping decisions made for the thesis timeline, with clear paths to production-grade solutions documented for each.

**Last updated:** March 2026

---

## Phase 1: Project Scaffold

### L1.1 — SQLite instead of PostgreSQL

**Decision:** Use SQLite for the thesis MVP instead of PostgreSQL.

**Why:** Single-tenant, single-user context. SQLite requires zero infrastructure (no server, no Docker dependency for the DB). Reduces setup complexity for thesis reviewers who want to run the system locally.

**Limitation:** SQLite doesn't support concurrent writes well. Under load (multiple users querying simultaneously), writes to audit_logs could queue or fail.

**Production path:** SQLAlchemy abstracts the database engine. Swapping to PostgreSQL is a one-line change in the `DATABASE_URL` environment variable. The schema is designed to be fully PostgreSQL-compatible. No code changes required.

---

### L1.2 — ChromaDB instead of a production vector database

**Decision:** Use ChromaDB as a local embedded vector store.

**Why:** Zero infrastructure, easy to set up, sufficient for thesis-scale data (tens of thousands of chunks). Good Python integration and active community.

**Limitation:** ChromaDB is not designed for production-scale concurrent queries, doesn't support horizontal scaling, and has limited filtering performance on large datasets.

**Production path:** Migrate to Pinecone, Weaviate, or Qdrant. The vector store is accessed through an abstraction layer, so the swap requires implementing a new adapter, not rewriting retrieval logic.

---

## Phase 2: GitHub Ingestion

### L2.1 — GitHub PAT stored as environment variable, not encrypted in database

**Decision:** Store the GitHub Personal Access Token as `GITHUB_PAT` in the `.env` file rather than encrypting it in the database.

**Why:** Single-tenant MVP means only one GitHub connection is needed. Environment variables are the standard way to handle secrets in single-tenant deployments. Adding Fernet encryption would protect against database file leaks but not against server compromise (attacker would have access to both the DB and the env vars). The added complexity isn't justified for the thesis scope.

**Limitation:** Cannot support multiple GitHub connections with different tokens (multi-tenant). The token has no rotation mechanism built in — if compromised, the admin must manually update the .env and restart the server.

**Production path:** For multi-tenant: encrypt tokens with Fernet (or AWS KMS / GCP Secret Manager) and store per-tenant in the database. Better yet, migrate to GitHub App installation tokens, which are short-lived, auto-rotating, and scoped per-organization. GitHub Apps are the industry standard for production integrations.

---

### L2.2 — AST parsing limited to Python, JavaScript, and TypeScript

**Decision:** Use tree-sitter AST parsing only for Python, JS, and TS. All other languages fall back to line-based chunking.

**Why:** These three languages cover the majority of modern tech company codebases and have the most mature tree-sitter grammars. Adding every language would multiply testing and edge-case handling.

**Limitation:** Go, Rust, Java, Ruby, PHP, C/C++ files are chunked by line blocks (80–120 lines with overlap) rather than by function/class boundaries. This produces lower-quality chunks with less precise retrieval.

**Production path:** Add tree-sitter grammars for additional languages incrementally. The chunker is designed as a language-dispatch system — adding a new language means writing one new chunking function and registering the grammar, not modifying the pipeline.

---

### L2.3 — No incremental/differential GitHub updates

**Decision:** Phase 2 only supports full re-sync (re-clone and re-process the entire repository).

**Why:** Incremental updates require diffing the current repo state against the last indexed snapshot, determining which chunks are affected, and selectively re-embedding. This is complex and is scoped for Phase 7 (weekly updater).

**Limitation:** Updating the knowledge base after code changes requires a full re-sync, which is slower and uses more embedding API calls than necessary.

**Production path:** Phase 7 implements change detection using `git diff` between the last synced commit and HEAD. Only modified, added, or deleted files are re-processed. Chunk IDs are deterministic, so unchanged chunks are naturally preserved.

---

### L2.4 — No GitLab or Bitbucket support

**Decision:** Only GitHub is supported as a code source.

**Why:** GitHub has the largest market share and the best-documented API. Supporting multiple git platforms multiplies the integration surface without adding thesis value.

**Limitation:** Companies using GitLab or Bitbucket cannot use Arcana without migrating or mirroring to GitHub.

**Production path:** The ingestion pipeline is source-agnostic after the cloning step. Adding GitLab/Bitbucket means implementing a new connector that clones repos and extracts metadata — the chunking, embedding, and storage layers are reused entirely.

---

## Phase 3: Notion Ingestion

### L3.1 — Notion token stored as environment variable

**Decision:** Store the Notion integration token as `NOTION_TOKEN` in `.env`, same approach as GitHub PAT (L2.1).

**Why:** Same rationale as L2.1 — single-tenant, single-workspace MVP.

**Limitation:** Same as L2.1 — no multi-workspace support, no rotation mechanism.

**Production path:** Same as L2.1 — encrypted per-tenant storage or OAuth-based token management.

---

### L3.2 — Polling-based sync instead of real-time webhooks

**Decision:** Notion content is synced via daily scheduled polling, not real-time.

**Why:** Notion's API does not currently offer webhook support. There is no way to receive push notifications when a page is edited. The only option is polling — checking `last_edited_time` on pages and re-processing those that changed.

**Limitation:** Content updates in Notion are not reflected in Arcana's knowledge base until the next daily sync runs. A document edited at 2pm won't be available until the next sync cycle. For the thesis MVP, the sync runs daily.

**Why this is acceptable:** Onboarding knowledge (PRDs, architecture docs, runbooks) changes infrequently — typically days or weeks between edits, not hours. A daily sync captures the vast majority of changes within an acceptable window. No competitor in this space offers real-time Notion sync either, because the API limitation is universal.

**Production path:** Increase polling frequency to hourly or even every 15 minutes (it's a cron interval change). The sync only re-processes pages whose `last_edited_time` exceeds `last_synced_at`, so frequent polling is cheap. If Notion ships webhooks in the future, the re-processing logic is identical — only the trigger mechanism changes from poll to push.

---

### L3.3 — No Notion comments or discussion threads

**Decision:** Skip extraction of page comments and discussions.

**Why:** Comments are conversational and often ephemeral ("can you update this section?", "looks good to me"). They add noise to the knowledge base without adding onboarding value. The signal-to-noise ratio is too low.

**Limitation:** Occasionally, important context lives in comments (design rationale, rejected alternatives). This context is lost.

**Production path:** Optionally extract comments and store them as low-priority metadata on the parent chunk. Apply a relevance filter (skip short comments, keep comments over N tokens that contain substantive content). Flag as a user-configurable option.

---

### L3.4 — No Notion file attachments or embedded PDFs

**Decision:** Skip extraction of files, PDFs, and other binary content embedded in Notion pages.

**Why:** Extracting and parsing PDFs requires OCR or PDF-specific tooling (a separate skill entirely). Images and other binary content can't be meaningfully embedded as text vectors. The complexity is disproportionate to the onboarding value for the thesis.

**Limitation:** If a team stores critical documentation as PDF attachments in Notion rather than as page content, that knowledge is invisible to Arcana.

**Production path:** Add PDF extraction using a library like PyMuPDF or pdfplumber. Parse text content, chunk it, and associate it with the parent Notion page. For images, use a vision model to generate text descriptions if the image contains diagrams or architecture visuals.

---

### L3.5 — Database views, filters, and formulas — raw data only

**Decision:** Extract raw database row data and computed formula/rollup results, but not view configurations or filter definitions.

**Why:** Views are UI presentation settings (sorting, filtering, column visibility), not knowledge content. The raw rows contain the complete dataset that all views are built from. Formula and rollup columns return their computed values via the API, so the results are captured even though the formula logic itself is not stored.

**Limitation:** If a team relies heavily on specific view names as organizational concepts (e.g., "Sprint Board" view vs "Backlog" view), that organizational context is lost.

**Production path:** Optionally store view names and filter definitions as metadata on database chunks, allowing the AI to reference them when answering questions about project structure.

---

### L3.6 — Maximum page hierarchy depth of 5 levels

**Decision:** Stop recursive traversal at 5 levels of page nesting.

**Why:** Deeply nested Notion hierarchies are rare and often indicate disorganized content. Each level of recursion multiplies API calls (3 req/s rate limit), making deep traversal slow. 5 levels covers the vast majority of real-world Notion workspaces.

**Limitation:** Content nested beyond 5 levels is not indexed. If a workspace has 7 levels of nesting, the bottom 2 are invisible.

**Production path:** Make the depth limit configurable per data source. Add a warning in the sync status when pages are skipped due to depth limits, so admins can restructure or increase the limit.

---

## Phase 4: RBAC + Permission System

### L4.1 — Permissions at data source level, not per-file

**Decision:** Access control is scoped to entire data sources (a whole GitHub repo, a whole Notion workspace), not individual files, functions, or pages within a source.

**Why:** Per-file permissions would require mapping every developer's access to every file in every repo — a matrix that grows exponentially and is painful to manage. Data source-level scoping covers the majority of real-world access patterns (e.g., "the payments team can access the payments repo") with minimal admin overhead.

**Limitation:** A developer with access to a repo can query all files in that repo, even if they only work on a subset. There's no way to say "access src/auth/ but not src/payments/" within the same repo.

**Production path:** Add optional per-directory or per-file access rules using pattern matching on the `file_path` metadata. The pre-retrieval filter would add an additional regex/glob check against permitted path patterns. This is an additive change — the source-level filter remains the first gate.

---

### L4.2 — No permission sync from upstream platforms

**Decision:** Arcana's permissions are managed independently. If a developer loses access to a GitHub repo or Notion workspace, their Arcana permissions are not automatically revoked.

**Why:** Syncing permissions from GitHub and Notion requires polling their APIs for each user's access levels, handling different permission models (GitHub has org roles, repo roles, team memberships; Notion has workspace sharing), and reconciling them into Arcana's simpler scope model. This is a significant integration effort that doesn't add thesis value.

**Limitation:** Permission drift — a developer who leaves a team might retain Arcana access to that team's knowledge until an admin manually revokes it.

**Production path:** Build a periodic permission sync job that checks each user's actual access in GitHub/Notion and automatically revokes Arcana permissions when upstream access is removed. Alternatively, integrate with the company's identity provider (Okta, Google Workspace) which is typically the source of truth for access decisions.

---

### L4.3 — API key authentication only, no OAuth/SSO

**Decision:** Users authenticate with API keys only. There is no OAuth flow, no SSO, no "log in with GitHub/Google."

**Why:** API key auth is simple, stateless, and works perfectly for CLI and Cursor extension use cases (where the key is stored in config). OAuth adds session management, token refresh, redirect flows, and identity provider integration — all of which are significant implementation effort for a single-tenant thesis MVP.

**Limitation:** Users must manually manage API keys. There's no single sign-on experience, and keys don't expire automatically (they must be manually rotated).

**Production path:** Add OAuth2 with GitHub and Google as identity providers. Map the OAuth identity to the Arcana user record. Keep API keys as a parallel authentication method for CLI and programmatic access. Add key expiry and automatic rotation policies.

---

### L4.4 — Hard-coded role hierarchy

**Decision:** The four roles (viewer, dev, senior_dev, admin) and their capabilities are defined in application code, not in a configurable database table.

**Why:** Four roles cover the vast majority of engineering team structures. Making roles configurable adds schema complexity (roles table, capabilities table, role-capability mapping) that is unnecessary for a single-company thesis deployment.

**Limitation:** Companies with non-standard role structures (e.g., a "team lead" role between senior_dev and admin, or a "security auditor" role with read-all but modify-nothing) cannot customize the hierarchy.

**Production path:** Move role definitions to a database table with a capabilities JSON field. Add role management endpoints. The existing middleware checks `user.role.level >= required_level` — this pattern works with database-driven roles as well as hard-coded ones.

---

### L4.5 — Binary sensitive content tagging

**Decision:** Sensitive content tagging is all-or-nothing at the data source level. If a repo is marked sensitive, all chunks from that repo are restricted to senior_dev+ users.

**Why:** Chunk-level sensitivity would require admins to specify patterns (file paths, page titles) for what's sensitive within a source. The UI for managing this is complex, and the filter logic adds significant query overhead for the MVP.

**Limitation:** If one file in a 500-file repo contains secrets or sensitive logic, the entire repo must be marked sensitive (blocking lower-role users from all 500 files) or left unmarked (exposing the sensitive file).

**Production path:** Add chunk-level sensitivity metadata. Allow admins to define sensitivity patterns (e.g., "files matching **/secrets/** are sensitive") that are applied during ingestion. The pre-retrieval filter checks both source-level and chunk-level sensitivity flags.

---

## Phase 5: AI Orchestration + Retrieval Pipeline

### L5.1 — No multi-turn conversation memory

**Decision:** Each query is independent. The system does not remember previous questions in the session.

**Why:** Multi-turn conversation requires session management, context window allocation for history, and prompt engineering to handle follow-up questions ("what about the error handling?" where "the" refers to a previous answer). This adds significant complexity for a thesis MVP where single-shot Q&A already demonstrates the full retrieval pipeline.

**Limitation:** Developers cannot have follow-up conversations. Each question must be self-contained. "Tell me more about that function" won't work because the system doesn't know what "that" refers to.

**Production path:** Add a conversation context buffer that includes the last 3–5 exchanges in the prompt. Store conversation state per-session using a session ID. The prompt builder prepends conversation history before the current question. Token budget management must account for the history allocation.

---

### L5.2 — BM25 index uses SQLite FTS5, limited scalability

**Decision:** The keyword index is built on SQLite FTS5, the same SQLite database used for relational data.

**Why:** FTS5 is built into SQLite, requires no additional infrastructure, and performs well for thesis-scale data (tens of thousands of chunks). It keeps the stack simple and avoids introducing another service dependency.

**Limitation:** SQLite FTS5 doesn't scale to millions of chunks or handle high-concurrency keyword search well. At production scale, query latency would degrade.

**Production path:** Migrate to Elasticsearch or Meilisearch for keyword search. The DualStore abstraction means the keyword backend is swappable — implement a new adapter for the chosen search engine without modifying retrieval logic.

---

### L5.3 — Cross-encoder re-ranker runs on CPU

**Decision:** The default re-ranker (cross-encoder/ms-marco-MiniLM-L-6-v2) runs on CPU.

**Why:** The MiniLM model is small enough to run on CPU with acceptable latency (~50ms for 40 candidates). Requiring a GPU for the thesis would add significant infrastructure complexity and cost.

**Limitation:** Under concurrent queries (5+ simultaneous), re-ranking becomes a bottleneck. CPU-bound inference doesn't parallelize well.

**Production path:** Deploy re-ranker on a GPU instance (reduces latency to ~5ms). Alternatively, switch to Cohere Rerank API which handles scale externally. Both options are configurable via the `RERANK_BACKEND` environment variable today.

---

### L5.4 — Semantic cache is per-instance, not shared, and has scope edge cases

**Decision:** The semantic cache uses a local ChromaDB collection. Each server instance has its own cache. Cache entries are scoped by access permissions to prevent information leakage.

**Why:** Single-instance deployment for the thesis. A shared cache would require Redis with vector search or a dedicated cache service — additional infrastructure for no thesis benefit.

**Limitation:** Two limitations: (1) If Arcana were deployed behind a load balancer with multiple instances, cache hits would be inconsistent (query might hit an instance without the cached entry). (2) A cached response from a lower-role user (e.g., `dev`) can be served to a higher-role user (e.g., `senior_dev`) since it's safe (no unauthorized data leaks), but the response may be *incomplete* — missing content from sensitive sources the higher-role user would have access to.

**Production path:** For multi-instance: migrate cache to Redis Stack (vector similarity search) or a shared Pinecone namespace. For scope completeness: key cache entries by the exact scope set rather than using subset matching, so users with different scope sets always get fresh results tailored to their access.

---

### L5.5 — Component renderer limited to 5 component types

**Decision:** The visual component renderer supports chart, table, metric_card, timeline, and progress types only.

**Why:** These five cover the most common exploratory query patterns (quantitative data, tabular results, key metrics, chronological events, progress tracking). Adding more types requires both backend JSON schemas and client-side renderers.

**Limitation:** Complex visualizations (network graphs, Sankey diagrams, dependency trees, interactive maps) are not supported.

**Production path:** Extend the component spec incrementally. The renderer is a type-dispatch system — adding a new type means defining a JSON schema and building a client-side renderer. The LLM prompt is updated to include the new type in its options.

---

### L5.6 — Citation accuracy depends on LLM behavior

**Decision:** Citations rely on the LLM correctly referencing [SOURCE N] tags in its output. Post-processing validates but cannot guarantee accuracy.

**Why:** The LLM is instructed to cite sources, and sources are clearly numbered in the prompt. Post-processing strips orphaned references and validates citation numbers. But the LLM can still occasionally cite the wrong source for a claim.

**Limitation:** A small percentage of citations may be inaccurate — the LLM might attribute information to Source 2 when it actually came from Source 3.

**Production path:** Add a citation verification step that checks whether the cited source's content actually supports the claim in the surrounding text (using a lightweight NLI model or embedding similarity). Flag low-confidence citations for the user.

---

### L5.7 — Full pipeline latency of 2–4 seconds

**Decision:** Accept 2–4 second total query time for a full pipeline execution (no cache hit).

**Why:** Each stage adds latency: RBAC scope resolution (~5ms), query embedding (~100ms), cache check (~50ms on miss), dual search (~200ms), fusion (~10ms), re-ranking (~50–200ms), context assembly (~10ms), Gemini streaming (~1–3s). Streaming mitigates perceived latency since the user sees tokens arriving progressively.

**Limitation:** The first token takes 1–2 seconds to appear. For rapid-fire questions, this feels slow compared to a chat interface.

**Production path:** GPU re-ranker reduces re-ranking to ~5ms. Gemini Flash model is already the fastest option. Pre-computed embeddings for common query patterns could skip the embedding step. Ultimately, latency is dominated by the LLM call, which streaming already handles well.

---

### L5.8 — Proprietary code sent to Gemini API

**Status:** This is the same concern as cross-phase limitation LX.1, now directly relevant in the implementation.

**Mitigations implemented in Phase 5:** Minimal data transmission (only retrieved chunks, not full files), Gemini API terms prohibit training on API data, RBAC scoping limits what's sent, audit trail records what was transmitted, semantic cache reduces API call frequency.

**See LX.1 for the full discussion and production path.**

---

---

## Phase 6: Cursor Extension + CLI

### L6.1 — Extension is sideloaded, not marketplace-published

**Decision:** The Cursor extension is distributed as a `.vsix` file that developers install manually, not through the VS Code/Cursor marketplace.

**Why:** Publishing to the marketplace requires a publisher account, a review process, and meeting listing requirements (icons, descriptions, screenshots). For a single-tenant thesis MVP being used by one company, sideloading is faster and sufficient.

**Limitation:** Developers must manually install the extension. There's no auto-discovery, no marketplace search, and no one-click install.

**Production path:** Publish to the VS Code Marketplace (Cursor uses the same marketplace). Set up a publisher account, prepare listing assets, and submit for review. Alternatively, distribute via a private extension registry for enterprise customers.

---

### L6.2 — No conversation history persistence

**Decision:** The sidebar chat is ephemeral. Closing the sidebar or reloading Cursor clears all previous exchanges.

**Why:** Persisting conversation history requires either extension-side storage (VS Code globalState, which has size limits) or backend-side storage (a new conversations table, session management). This adds complexity without thesis value, especially since Phase 5's limitation L5.1 means there's no multi-turn memory anyway — each question is independent.

**Limitation:** Developers can't refer back to previous answers from earlier in the day. If they close the sidebar and reopen it, the chat is empty.

**Production path:** Store conversation history in the extension's `context.globalState` for local persistence (limited but fast). For full persistence, add a conversations table in the backend and a GET /conversations endpoint. The sidebar loads recent conversations on open.

---

### L6.3 — No inline code annotations or hover hints

**Decision:** Arcana only provides information when explicitly asked via the sidebar or CLI. It does not proactively annotate code in the editor.

**Why:** CodeLens providers (showing "Arcana: explain" above functions) and hover providers (showing context on mouse hover) require background indexing of the open file, latency-sensitive API calls, and careful UX to avoid being intrusive. This is a significant feature that deserves its own design cycle.

**Limitation:** Developers must actively switch context to the sidebar or terminal to ask questions. There's no ambient intelligence while reading code.

**Production path:** Add a CodeLens provider that shows "Arcana: explain" above function/class definitions. Clicking it opens the sidebar with the function pre-loaded as context. Add a hover provider that shows a brief one-line summary when hovering over unfamiliar symbols (with a "Learn more" link to the sidebar). Both call the backend lazily with aggressive caching.

---

### L6.4 — CLI charts are text-based approximations

**Decision:** Charts in the CLI are rendered as text-based bar charts and tables. Complex visualizations (pie charts, scatter plots, multi-series line charts) don't render well in the terminal.

**Why:** Terminal environments have fundamental rendering constraints (monospace text, limited colors, no mouse interaction). Rich and plotext provide reasonable text-based charts, but they're inherently limited compared to HTML canvas rendering.

**Limitation:** Admin users who want detailed visual analytics get a degraded experience in the CLI compared to the Cursor extension.

**Production path:** The CLI could generate a temporary HTML file with full Chart.js rendering and open it in the default browser. Or direct users to the Streamlit admin panel (Phase 9) for comprehensive analytics.

---

### L6.5 — No auto-update mechanism

**Decision:** Neither the Cursor extension nor the CLI check for or install updates automatically.

**Why:** Auto-update for VS Code extensions requires marketplace publishing (see L6.1). Auto-update for Python CLI tools requires a custom update checker or reliance on pip. Both add complexity for a thesis MVP.

**Limitation:** When a new version is released, every developer must manually update. There's no notification that a newer version is available.

**Production path:** Extension: marketplace publishing enables automatic updates via VS Code's built-in extension updater. CLI: add an `arcana version --check` command that queries a version endpoint on the backend and notifies if an update is available. Add a startup check that prints a non-blocking warning if outdated.

---

### L6.6 — English only, no internationalization

**Decision:** All UI text, error messages, and prompts are in English. There is no i18n framework.

**Why:** The target audience (software developers) overwhelmingly uses English for code, documentation, and tooling. Internationalization adds string management overhead and testing complexity across languages.

**Limitation:** Non-English-speaking developers get an English-only experience. The system prompt is in English, so responses are in English even if the codebase contains comments in other languages.

**Production path:** Add i18n support using standard frameworks (VS Code's built-in localization for the extension, Python gettext for CLI). The system prompt would need language detection and multilingual variants. Low priority for most engineering teams.

---

---

## Phase 7: Auto-Updater with Weekly Review

### L7.1 — Daily schedule, not real-time triggers

**Decision:** Auto-updates run on a daily schedule. There are no real-time triggers like GitHub webhooks.

**Why:** GitHub webhooks require a publicly accessible endpoint (the backend is running locally for the thesis). Notion doesn't offer webhooks at all. Daily polling is simple, works for both sources, and catches changes within 24 hours — sufficient for onboarding knowledge.

**Limitation:** Changes are invisible to Arcana between daily runs. A critical architecture change pushed at 3 PM isn't reflected until 2 AM the next day.

**Production path:** Add GitHub webhook support for immediate change detection on push. Deploy with a public URL or use a webhook relay service. For Notion, increase polling frequency to hourly.

---

### L7.2 — Admin corrections are text-only

**Decision:** When reverting an auto-update, the admin provides a free-text correction. The correction is stored as a single text chunk, not a structured code chunk.

**Why:** Parsing admin corrections into properly structured chunks (with language annotation, function boundaries, line numbers) would require a secondary ingestion pipeline for human-authored content. A text chunk with a retrieval boost is simpler and sufficient for the MVP.

**Limitation:** If the admin wants to provide a corrected code snippet that replaces the auto-indexed one, the correction chunk won't have the same rich metadata (language, symbol_name, line_start/end) as AST-parsed code chunks. It's treated as documentation-quality content.

**Production path:** Allow corrections to include fenced code blocks. Parse the correction to detect code content and generate properly structured chunks with language annotation and metadata. Support multi-chunk corrections for complex fixes.

---

### L7.3 — Only the default branch is tracked

**Decision:** The auto-updater only monitors the default branch (usually `main` or `master`). Feature branches, pull requests, and other branches are not indexed.

**Why:** Branch-aware indexing multiplies complexity — each branch would need its own chunk set, and merges would require reconciliation. For onboarding, the default branch represents the production codebase.

**Limitation:** In-progress work (feature branches, open PRs) is not available. A developer asking about upcoming features won't get answers about code still in a PR.

**Production path:** Add branch selection per data source. PR-based indexing could preview how a PR changes the knowledge base before merging.

---

### L7.4 — Snapshot storage grows over time

**Decision:** Every auto-update stores full before/after chunk content in the update record for revert capability. No automatic cleanup.

**Why:** Full content snapshots are needed because reverts must restore actual chunk text and re-embed it. Content hashes alone wouldn't be sufficient.

**Limitation:** Storage grows linearly with update frequency. Estimated ~1MB/week for a moderately active codebase. After a year, ~52MB of snapshots — manageable but not negligible.

**Production path:** Add a retention policy: delete snapshots older than 90 days (reverts beyond that window are unlikely). Compress snapshot content. Or store only content diffs instead of full before/after states.

---

### L7.5 — Code diffs sent to Gemini API for summary generation

**Decision:** The auto-updater sends code diffs to the Gemini API to generate human-readable summaries. This expands the data privacy surface beyond query-time transmission.

**Why:** Summaries need to understand what changed and why it matters. This requires sending diff content to the LLM. Same mitigations as LX.1 apply: diffs are fragments, Gemini terms prohibit training on API data, audit trail logs transmissions.

**Limitation:** Sensitive code changes (security modules, accidentally committed credentials) could be sent to Gemini during summary generation.

**Production path:** Same as LX.1: self-hosted LLM. Additionally, add a diff redaction filter that strips known sensitive patterns (API keys, passwords, tokens) before sending.

---

### L7.6 — Weekly review quality depends on Gemini narrative generation

**Decision:** The Friday weekly summary is LLM-generated. Its ability to identify high-risk changes, spot patterns, and recommend reviews depends on Gemini's reasoning quality.

**Why:** Manual weekly summaries would require admin effort — the whole point is to automate the synthesis. LLM-generated narratives are good enough for a thesis demonstration.

**Limitation:** The narrative may miss subtle issues (a security-relevant change buried in a large diff), over-flag minor changes, or produce generic summaries that don't help the admin prioritize.

**Production path:** Iterate on the weekly summary prompt based on admin feedback. Add a "summary was helpful/unhelpful" flag to the acknowledgment flow. Track which reverts correlated with "recommended review" flags to measure prediction accuracy.

---

---

## Phase 8: Analytics Data Layer + Admin Dashboards

### L8.1 — Point-in-time snapshots, not real-time streaming

**Decision:** Analytics dashboards show data as of the last query, not a live-updating view. Refreshing requires clicking a button or re-running the CLI command.

**Why:** Real-time streaming dashboards require WebSocket connections, a pub/sub mechanism, and continuous query execution — significant infrastructure for a thesis MVP where the admin checks the dashboard occasionally, not continuously.

**Limitation:** The dashboard doesn't update automatically while being viewed. If a developer makes 10 queries while the admin is looking at the dashboard, the numbers don't change until refresh.

**Production path:** Add WebSocket-based live updates. Push new data points to connected dashboard clients as queries arrive. Use Redis pub/sub or SSE long-polling to broadcast updates.

---

### L8.2 — Popular topics uses source frequency, not semantic clustering

**Decision:** The "popular topics" metric counts which sources are queried most often, rather than clustering queries by semantic similarity to identify true topic groups.

**Why:** Semantic clustering requires embedding all recent queries, running k-means, and labeling clusters — more compute and complexity than source-frequency counting. Source frequency is a reasonable proxy for a thesis MVP ("backend-api is queried most" tells the admin where interest is concentrated).

**Limitation:** Two semantically identical questions about different sources are counted separately. "How does auth work?" hitting backend-api and "how does the login flow work?" hitting the same source count as one topic, but the same questions about different sources count as two.

**Production path:** Implement embedding-based clustering using scikit-learn k-means on query embeddings. Label clusters using the medoid query. This produces genuine topic groups ("authentication" as a topic regardless of which source answered it).

---

### L8.3 — No export or sharing capability

**Decision:** Dashboards exist only in the Cursor sidebar and CLI terminal. They can't be saved as PDF, shared via link, or emailed as reports.

**Why:** Export requires either headless browser rendering (for PDF) or a separate report generation pipeline. Sharing requires URL-based dashboard access, which implies a web UI. Both are outside the thesis scope.

**Limitation:** An admin who wants to share analytics with a non-technical stakeholder (VP of Engineering, CTO) must screenshot the terminal or Cursor sidebar.

**Production path:** Add export endpoints that render components to PDF (headless browser like Playwright) or CSV. Add scheduled email reports using the same analytics functions. Long-term: build a lightweight web dashboard for read-only analytics sharing.

---

### L8.4 — Admin-scoped only, no personal developer analytics

**Decision:** All analytics endpoints require admin or senior_dev role. Individual developers cannot see their own usage patterns.

**Why:** Developer-facing analytics (personal query history, frequently asked topics, onboarding progress tracker) are a distinct feature with different privacy considerations (should a developer see that they asked more questions than their peers?). Scoping analytics to admin keeps the feature focused for the thesis.

**Limitation:** Developers can't track their own onboarding progress or see what topics they've been exploring. This would be a valuable self-service feature.

**Production path:** Add GET /analytics/me scoped to the authenticated user's own audit_logs. Return personal query count, most-asked topics, last active timestamp, and an "onboarding coverage" metric (percentage of key knowledge areas the developer has queried about).

---

### L8.5 — response_schema upgrade limited to visual queries

**Decision:** The Gemini `response_schema` upgrade only applies to visual queries (where the keyword heuristic triggers component mode). Normal text queries still use unstructured text output.

**Why:** Structured output for text responses would require a complex schema that combines free-form text with structured citation objects. This is a different problem than visual component rendering. The current citation extraction via post-processing (Phase 5 stream + cite) works well enough for text responses.

**Production path:** Design a hybrid schema that accommodates both free text and structured citations (e.g., `{"text_blocks": [{"content": "...", "references": [1, 2]}], "references": [{"id": 1, ...}]}`). This would guarantee citation structure while allowing free-form answer text. Requires careful prompt engineering to maintain answer quality within the schema constraint.

---

---

## Phase 9: Internal Admin Panel (Streamlit)

### L9.1 — Streamlit is functional but not visually polished

**Decision:** The admin panel uses Streamlit, which produces a data-tool aesthetic, not a product-quality UI.

**Why:** Streamlit is Python-only (no HTML/CSS/JS), renders a functional interface in hours, and is the standard for data-centric admin tools. The admin panel is internal tooling — it doesn't need to impress customers. It needs to work.

**Limitation:** The panel looks like a Jupyter notebook with widgets, not like a professional admin dashboard. Stakeholders shown the panel during demos might underestimate the product's polish.

**Production path:** Migrate to a React-based admin framework (Retool, AdminJS, or custom React). The backend API is already complete — only the frontend rendering layer changes.

---

### L9.2 — No role-based page visibility within the panel

**Decision:** All pages (users, sources, analytics, audit, etc.) are visible to anyone with admin access. There's no page-level access control within the panel.

**Why:** The panel requires admin role to access at all (API key validation on login). Within the panel, all admins see everything. Adding per-page role gating (e.g., senior_devs can see analytics but not user management) adds complexity for a single-admin thesis deployment.

**Limitation:** If senior_devs are given panel access (by sharing the admin key or implementing role-based login), they see all pages including user management, which they shouldn't be able to modify.

**Production path:** Store the logged-in user's role in session_state during login. Add a role check at the top of each page that hides or disables pages requiring higher privileges. The backend already enforces RBAC on the API level — this would add a matching UI layer.

---

### L9.3 — No concurrent admin support or real-time updates

**Decision:** Each Streamlit session is independent. Two admins using the panel simultaneously don't see each other's actions in real-time.

**Why:** Streamlit uses a per-session state model. There's no built-in mechanism for cross-session communication. Real-time updates would require WebSocket integration, which Streamlit supports only experimentally.

**Limitation:** If Admin A creates a user while Admin B is viewing the user list, Admin B doesn't see the new user until they refresh. Not a practical issue for a single-admin thesis deployment.

**Production path:** Migrate to a React frontend with WebSocket-based real-time updates. Or add Streamlit's experimental callback mechanism to push updates between sessions.

---

### L9.4 — Panel cannot be embedded in Cursor

**Decision:** The admin panel runs as a standalone web app in a browser tab. It cannot be loaded inside the Cursor extension.

**Why:** Streamlit apps are full web pages with their own JavaScript runtime. Embedding them in a VS Code/Cursor webview panel would require iframe support with proper CORS configuration, which Streamlit doesn't enable by default.

**Limitation:** Admins must switch between Cursor (for developer queries) and a browser tab (for admin tasks). There's no unified interface.

**Production path:** Serve the admin panel over HTTP with permissive CORS headers and load it in Cursor's webview via an iframe. Or migrate to a React-based panel that can be served as a VS Code webview natively.

---

### L9.5 — No panel-level analytics or usage tracking

**Decision:** The panel itself doesn't track which pages the admin visits, how long they spend reviewing, or which actions they consider but don't take.

**Why:** All state-changing actions (user creation, cache flush, reverts) are logged by the backend API's audit system. The panel is a thin UI layer — adding client-side analytics adds complexity for minimal thesis value.

**Limitation:** There's no data on admin behavior patterns ("the admin checks analytics every Monday but never reviews the weekly summary until Friday"). This data could improve the alert system.

**Production path:** Add page-view events from the Streamlit app to the backend audit log. Track navigation patterns and time-on-page. Use this data to optimize the alert schedule and dashboard layout.

---

## Cross-Phase Limitations

### LX.1 — Proprietary code sent to external LLM API

**Status:** Addressed in Phase 5 PRD (Section 15) with concrete mitigations.

**The issue:** When a developer asks a question, Arcana retrieves relevant code and documentation chunks and sends them to the Gemini API as context. This means proprietary source code leaves the customer's infrastructure and is transmitted to Google's servers.

**Mitigations implemented (Phase 5):**
1. Minimal data transmission — only 5–10 short chunk fragments per query, not full files (~3000 tokens / ~2000 words)
2. Google's Gemini API terms: data is not used for model training and is not retained beyond processing
3. RBAC scoping limits exposure to the querying user's authorized content only
4. Audit trail records which sources were sent to the LLM and when
5. Semantic cache serves repeated queries without any LLM API call, reducing transmission frequency

**Why this is acceptable for the thesis:** The combination of mitigations above, Google's data handling guarantees, and the fact that only fragments (not complete repositories) are transmitted makes this an acceptable trade-off. The thesis documents this as a known constraint with a clear production path.

**Production path:** Offer self-hosted LLM options (e.g., running an open-source model locally via Ollama or vLLM). For enterprise customers, deploy within their VPC using Google Cloud's private endpoints or a self-hosted alternative. This is a deployment architecture change, not a code change — the LLM call is behind an abstraction layer.

---

### LX.2 — Single-tenant architecture

**Status:** Deliberate MVP scope. Multi-tenant is Tier 3.

**The issue:** Arcana serves one company at a time. There is no tenant isolation, no per-company database separation, no multi-org billing or access management.

**Production path:** Add a `tenant_id` foreign key to all tables. Scope every database query and ChromaDB filter by tenant. Isolate vector collections per tenant (separate ChromaDB collections or filtered namespaces in Pinecone). Add an onboarding/provisioning flow for new tenants.

---

### LX.3 — No user-facing web UI

**Status:** Deliberate architectural decision (see project strategy discussion).

**The issue:** Arcana has no customer-facing web interface. All developer interaction happens through the Cursor extension and CLI. Admin management happens through API endpoints and a Streamlit internal panel.

**Why this is a feature, not a limitation:** Developers don't want another tool to learn. Meeting them in the editor reduces adoption friction. The backend-first architecture means a web UI can be added later without any backend changes.

**Production path:** Build a React/Next.js frontend consuming the existing FastAPI endpoints. The API is already designed to support this — all CRUD, query, and admin operations are exposed as REST endpoints.

---

*This document will be updated as new phases are developed and new limitations are identified.*