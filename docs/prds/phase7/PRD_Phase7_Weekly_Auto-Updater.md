# PRD — Phase 7: Auto-Updater with Weekly Review

**Product:** Arcana — AI-Powered Developer Onboarding Platform
**Phase:** 7 of Tier 2 (stretch goal)
**Version:** 2.0
**Date:** April 2026
**LLM Provider:** Gemini APIs
**Depends on:** Phases 1–6 (complete)
**Related:** [Arcana Limitations & Design Decisions Log](./Arcana_Limitations_and_Design_Decisions.md) — entries L7.1 through L7.6

---

## 1. Overview

The knowledge base Arcana built in Phases 2–5 is a snapshot. Codebases evolve — functions get renamed, new services are created, PRDs get rewritten, architecture decisions change. If the knowledge base doesn't evolve with them, answers become stale and developers lose trust.

Phase 7 adds a two-part self-maintenance system:

1. **Daily auto-updates:** Every day, the system detects changes across all connected sources (GitHub and Notion), analyzes what changed, and automatically re-indexes the affected chunks. No human approval is needed — the knowledge base stays fresh in real-time.

2. **Weekly review alert:** Every Friday, admins receive a summary of everything that changed during the week. They review the summary and can revert specific changes they disagree with. When reverting, the admin must provide a correction explaining what the knowledge base should say instead — ensuring the system learns from the feedback rather than just rolling back to potentially outdated content.

This model prioritizes freshness (updates are never blocked by a human bottleneck) while preserving quality assurance (admins review retroactively and can course-correct).

---

## 2. Objectives

- Detect changes in GitHub repositories daily (new files, modified files, deleted files)
- Detect changes in Notion workspaces daily (edited pages, new pages, deleted pages)
- Automatically re-index affected chunks without waiting for human approval
- Use the Gemini API to generate human-readable change summaries for each update
- Store a complete history of every auto-update with before/after snapshots
- Send a weekly review alert to admin users every Friday summarizing all changes
- Allow admins to revert specific changes with a mandatory correction
- Apply admin corrections to the knowledge base immediately
- Invalidate semantic cache entries affected by each update

---

## 3. Scope

### 3.1 In scope

- GitHub change detection via git diff between last synced commit and HEAD
- Notion change detection via page `last_edited_time` comparison (extends Phase 3 daily sync)
- Automatic incremental re-indexing (ChromaDB + FTS5 dual-write) without human approval
- Change significance filtering (skip noise like lock files and whitespace changes)
- LLM-generated change summaries stored with each update record
- Before/after chunk snapshots for revert capability
- Weekly review alert system (Friday summary)
- Revert flow with mandatory correction input
- Correction application to the knowledge base
- Semantic cache invalidation after each update
- Configurable schedule via APScheduler
- Manual trigger support
- Update history and metrics

### 3.2 Out of scope

- Real-time webhooks (GitHub webhooks are Tier 3; Notion doesn't support them)
- Pre-approval workflow (deliberately replaced by retroactive review in this design)
- Branch-aware indexing (only default branch — see limitation L7.3)
- Conflict resolution for simultaneous changes across sources
- Automated quality scoring of updates (post-thesis)

---

## 4. Change Detection

### 4.1 GitHub change detection

Runs daily. The system compares the current state of each indexed repository against the last synced state.

**Detection method:**

1. For each registered GitHub data source, retrieve `last_synced_commit` from `data_sources.config_json`.

**First-run baseline:** Phase 2's `run_ingestion()` was implemented without storing a commit hash. For any source where `last_synced_commit` is absent, the auto-updater records the current HEAD as the baseline and skips change detection for that run. No update records are created. The second run onward operates normally. This avoids generating a meaningless "everything is new" event for content already indexed by Phase 2.

**Phase 7 also patches `run_ingestion()`** to store `last_synced_commit` on successful completion, so any re-sync from the admin UI also advances the baseline correctly.

2. Call the **GitHub API compare endpoint** (`GET /repos/{owner}/{repo}/compare/{base}...{head}`) to get the list of changed files and their diffs. This avoids persistent local clones — no disk management or path tracking per source needed.

**Known limitation:** The compare endpoint returns at most 250 commits and 300 files per comparison. If a repo somehow accumulates >250 commits between daily runs (extremely unlikely for any normal team), the updater falls back to a full re-sync for that source and logs a warning.

3. Parse the response to classify each file:

| Status | Meaning | Action |
|---|---|---|
| A (added) | New file | Chunk, embed, and store as new chunks |
| M (modified) | File changed | Re-chunk and re-embed; update existing chunks by deterministic ID |
| D (deleted) | File removed | Delete all chunks from this file in ChromaDB and FTS5 |
| R (renamed) | File moved/renamed | Delete old chunks, create new chunks with updated file path |

5. Apply the same file filters from Phase 2 (include/exclude patterns, .codemindignore)

### 4.2 Notion change detection

Runs daily. Extends Phase 3's existing daily sync with change tracking and summary generation.

**Detection method:**

1. For each registered Notion data source, retrieve `last_synced_at` from `data_sources`
2. Call the Notion API search endpoint filtered by `last_edited_time > last_synced_at`
3. For each changed page, fetch the current block content
4. Compare against stored chunks to determine what changed
5. New pages within the configured scope are detected and indexed

**Classification:**

| Change type | Detection method | Action |
|---|---|---|
| Page content edited | `last_edited_time` > `last_synced_at` | Re-extract, re-chunk, re-embed |
| New page added | Page ID not in existing chunks, within selected scope | Full extraction and indexing |
| Page deleted/archived | Previously indexed page returns 404 or `archived: true` | Delete all chunks |
| Page moved | Page exists but `page_path` differs | Update metadata, re-embed if title changed |

### 4.3 Change significance filtering

Not all changes are worth re-indexing. The system filters before processing:

**Skip entirely (no update, no record):**
- Files/pages where the only change is whitespace or formatting
- Git commits that only modify lock files, CI configs, or generated files
- Notion pages where only `last_edited_by` changed without content edits
- Changes to files/pages in the exclude list

**Process but flag as minor:**
- Changes of fewer than 5 lines in code files
- Notion pages where only a single property value changed

**Flag as significant:**
- New files/pages
- Deleted files/pages
- Changes that modify function signatures, class definitions, or API endpoints
- Changes to the architectural overview document

The significance classification is stored with the update record and surfaced in the weekly review.

---

## 5. Automatic Re-Indexing

### 5.1 Core principle

Changes are applied immediately. The system does not wait for human approval. Freshness is prioritized over gated quality control. Quality assurance happens retroactively via the weekly review.

### 5.2 Re-indexing flow

**For added files/pages:**
1. Run the appropriate ingestion pipeline (Phase 2 for GitHub, Phase 3 for Notion) on new files only
2. Chunk and embed the new content
3. Store in both ChromaDB and FTS5 via the DualStore (Phase 5)
4. Apply access scope tags from the parent data source

**For modified files/pages:**
1. **Snapshot before-state:** For each existing chunk that will be affected, store the current content and metadata in the update record (Section 6) before overwriting
2. Re-run the ingestion pipeline on modified files only
3. Generate new chunks with deterministic IDs
4. For matching IDs: update content and re-embed
5. For new IDs (new function added): insert
6. For IDs that no longer appear (function deleted from file): delete

**For deleted files/pages:**
1. **Snapshot before-state:** Store all chunks from the file/page before deletion
2. Delete all matching chunks from both ChromaDB and FTS5
3. Log the deletion count

**For renamed files:**
1. Snapshot chunks with old path
2. Delete old-path chunks
3. Re-ingest with new path

### 5.3 Cross-reference update

After re-indexing, cross-reference detection (Phase 3) runs on new/modified chunks to update `cross_references` metadata. References to deleted chunks are cleaned up.

### 5.4 Commit and sync tracking

After successful re-indexing of a GitHub source:
- Update `data_sources.config_json.last_synced_commit` to HEAD
- Update `data_sources.last_synced_at` to current timestamp

After successful re-indexing of a Notion source:
- Update `data_sources.last_synced_at` to current timestamp

---

## 6. Update Records

### 6.1 Purpose

Every auto-update produces a detailed record. These records serve three purposes: they power the weekly review summary, they enable the revert flow (before-state snapshots), and they provide an audit trail of knowledge base evolution.

### 6.2 Schema

This phase requires an Alembic migration to create a new `update_records` table:

| Column | Type | Constraints | Description |
|---|---|---|---|
| id | UUID | PK | Unique update record |
| source_id | UUID | FK → data_sources.id, not null | Which source was updated |
| change_type | Enum | Not null | One of: file_added, file_modified, file_deleted, file_renamed, page_edited, page_added, page_deleted, page_moved |
| file_or_page | String(500) | Not null | File path or page title that changed |
| significance | Enum | Not null | One of: significant, minor |
| summary | Text | Not null | LLM-generated human-readable description of what changed |
| chunks_affected | Integer | Not null | Number of chunks added, modified, or deleted |
| snapshot_before | JSON | Nullable | Before-state: array of {chunk_id, content, content_hash, metadata} for affected chunks. Stores full chunk text to enable revert + re-embedding. |
| snapshot_after | JSON | Nullable | After-state: array of {chunk_id, content, content_hash, metadata} for new/updated chunks. Stored for audit trail and diff display. |
| status | Enum | Default: applied | One of: applied, reverted, correction_applied |
| reverted_by | UUID | FK → users.id, nullable | Admin who reverted this update |
| reverted_at | DateTime | Nullable | When the revert happened |
| correction_text | Text | Nullable | Admin's correction explaining what should be there instead |
| created_at | DateTime | Auto, UTC | When the update was applied |
| week_number | Integer | Not null | ISO week number (used for weekly grouping) |
| year | Integer | Not null | Year (used with week_number for grouping) |

**Storage note:** The `snapshot_before` and `snapshot_after` JSON columns store full chunk content (text, not embeddings). For a modified file with 20 functions, each snapshot could contain ~20 JSON objects averaging ~2KB each = ~40KB per update record. At 100 updates/week, this adds ~4MB/week to the SQLite database. This is manageable for the thesis but a retention policy should be added for production (see limitation L7.4).

### 6.3 LLM-generated summary

For each update, the system calls Gemini to generate a concise, human-readable summary:

```
Analyze this change to a codebase/documentation and write a 1-3 sentence summary
explaining what changed and why it matters for developer onboarding.

File: {file_path}
Change type: {change_type}
Diff:
{diff_content}

Keep it concise and focus on impact. Example: "New OAuth2 provider added to the
auth module. Developers asking about authentication will now get information about
both JWT and OAuth flows."
```

The summary is stored in the `summary` field. This is what admins read in the weekly review — they shouldn't need to parse raw diffs.

### 6.4 Snapshot design

The before/after snapshots store full chunk content to enable reverts with re-embedding:

**`snapshot_before`:**
```json
[
  {
    "chunk_id": "abc123",
    "content_hash": "sha256:...",
    "content": "def verify_token(token: str) -> User:\n    ...",
    "metadata": {"repo": "org/backend-api", "file_path": "src/auth/middleware.py", "access_scope": "backend-team"}
  }
]
```

**`snapshot_after`:**
```json
[
  {
    "chunk_id": "abc123",
    "content_hash": "sha256:...",
    "content": "def verify_token(token: str, provider: str = 'jwt') -> User:\n    ...",
    "metadata": {"repo": "org/backend-api", "file_path": "src/auth/middleware.py", "access_scope": "backend-team"}
  }
]
```

Full chunk content is stored in snapshots (not just hashes) because reverts need to restore the actual content and re-embed it.

---

## 7. Weekly Review Alert

### 7.1 Schedule

Every Friday at a configurable time (default: 5:00 PM local, end of work week), the system generates a weekly review summary and alerts admin users.

### 7.2 Weekly summary generation

The system:

1. Collects all `update_records` for the current ISO week
2. Groups them by source (GitHub repos, Notion workspaces)
3. Orders by significance (significant first, then minor)
4. Calls Gemini to generate a weekly narrative summary:

```
You are Arcana's knowledge base maintenance system. Summarize the following
week of automatic updates for an admin review.

UPDATES THIS WEEK:
{grouped_update_summaries}

Provide:
1. A 2-3 paragraph narrative summary of the week's changes
2. Highlight any changes that seem high-risk or potentially incorrect
3. Flag any patterns (e.g., "the auth module had 12 changes this week — 
   consider whether a broader architecture review is needed")
4. List the top 3 changes most likely to need admin review

Return as JSON:
{
  "narrative": "...",
  "high_risk_updates": ["update_id_1", "update_id_2"],
  "patterns": ["..."],
  "recommended_review": [
    {"update_id": "...", "reason": "..."}
  ],
  "total_updates": N,
  "significant_count": N,
  "minor_count": N
}
```

### 7.3 Alert delivery

The weekly summary is delivered through two channels:

**Cursor extension:** *(Deferred — Phase 7.5 follow-up.)* The backend exposes `GET /admin/updater/review/pending` specifically to support a badge check. The Cursor extension changes (review badge, weekly summary component card, revert modal) are built as a separate task after backend + CLI are verified end-to-end.

**CLI:** Running `arcana updater review-week` at any time shows the current week's summary. On Fridays, the next time any `arcana` command is run, a non-blocking banner appears:

```
┌─────────────────────────────────────────────────────┐
│ 📋 Weekly knowledge base review available           │
│ 14 updates this week (3 significant, 11 minor)      │
│ Run: arcana updater review-week                     │
└─────────────────────────────────────────────────────┘
```

### 7.4 Weekly summary storage

The weekly summary is stored in a new `weekly_reviews` table:

| Column | Type | Constraints | Description |
|---|---|---|---|
| id | UUID | PK | Unique review record |
| year | Integer | Not null | Year |
| week_number | Integer | Not null | ISO week number |
| summary_json | JSON | Not null | The Gemini-generated weekly summary |
| total_updates | Integer | Not null | Total update records this week |
| significant_count | Integer | Not null | Count of significant updates |
| minor_count | Integer | Not null | Count of minor updates |
| reverts_count | Integer | Default: 0 | Number of reverts applied after this review |
| reviewed_by | UUID | FK → users.id, nullable | Admin who reviewed |
| reviewed_at | DateTime | Nullable | When the review was acknowledged |
| created_at | DateTime | Auto, UTC | When the summary was generated |

**Unique constraint:** (year, week_number) — one summary per week.

---

## 8. Revert Flow with Mandatory Correction

### 8.1 Core principle

When an admin reverts a change, they don't just undo it — they must explain what the knowledge base should say instead. This transforms every revert into a learning moment: the correction becomes new, admin-validated content in the knowledge base.

### 8.2 Revert flow

1. Admin views the weekly summary (CLI or Cursor)
2. Admin identifies a change they want to revert (e.g., "the summary of the new OAuth module is misleading")
3. Admin initiates revert for that specific update record
4. System requires a correction text — the admin must provide what the knowledge base should say instead
5. System restores the before-state chunks from the snapshot
6. System creates a new "correction chunk" from the admin's correction text
7. The correction chunk is embedded and stored in both ChromaDB and FTS5 with metadata:
   - `source_type`: "admin_correction"
   - `corrected_update_id`: the reverted update record ID
   - `corrected_by`: the admin's user ID
   - `access_scope`: inherited from the original source
8. Update record status changes from `applied` to `correction_applied`
9. Semantic cache is invalidated for the affected access scope

### 8.3 CLI revert commands

All `arcana updater` commands are new additions to the Phase 6 CLI tool. A new file `arcana_cli/commands/updater.py` is added to the CLI package and registered as a Typer sub-app in `main.py`, following the same pattern as the existing `users`, `sources`, `cache`, and `audit` command groups.

```bash
# View the current week's review
arcana updater review-week

# View a specific week's review
arcana updater review-week --week 15 --year 2026

# Revert a specific update (interactive — prompts for correction)
arcana updater revert <update_id>
# Output:
# Update: New OAuth2 provider added to auth module
# Source: org/backend-api | File: src/auth/oauth.py
# This will restore the previous state and apply your correction.
#
# Correction (what should the knowledge base say instead):
# > The OAuth2 module was added but is not yet production-ready.
#   Developers should continue using the JWT flow documented in
#   src/auth/middleware.py until the OAuth migration is announced.
#
# Correction applied. Knowledge base updated.

# Revert with inline correction
arcana updater revert <update_id> --correction "The OAuth2 module is experimental. Use JWT for production auth."

# View revert history
arcana updater reverts                     # List all reverted updates
arcana updater reverts --week 15           # Filter by week
```

### 8.4 Cursor revert flow

*(Deferred — Phase 7.5.)* The Cursor extension changes (review badge, weekly summary component card with per-change Revert buttons, correction modal) are built as a follow-up task after backend + CLI are verified. The backend API fully supports this flow via `POST /admin/updater/revert/{update_id}`.

### 8.5 What happens to the reverted content

After a revert:

- The auto-updated chunks are replaced with the before-state chunks from the snapshot
- The admin's correction is stored as a new chunk with `source_type = "admin_correction"`
- This correction chunk has the same `access_scope` as the original source, so it appears in relevant queries
- The correction chunk receives a retrieval boost (same as architectural overview, +0.15) because admin-validated content is high-trust
- On the next daily auto-update, if the same file/page has changed again, the system detects this and generates a new update record. The admin correction remains as a separate chunk — it's not overwritten by auto-updates

### 8.6 Correction persistence

Admin corrections are persistent, high-trust chunks. They are not affected by daily auto-updates. If the underlying source changes again, both the correction and the new auto-update coexist. Over time, if the source eventually matches the correction (the team fixed the issue), the admin can delete the correction chunk manually.

This design means admin knowledge is never lost to automation — it accumulates as a layer of validated institutional knowledge on top of the auto-indexed content.

---

## 9. Cache Invalidation

### 9.1 After daily auto-updates

After each daily auto-update completes:

1. Identify the `access_scope` of each updated source
2. Invalidate all cache entries whose `access_scopes` overlap with any updated scope
3. Log: "Invalidated {N} cache entries for scopes {scopes} due to daily auto-update"

### 9.2 After reverts

After a revert + correction is applied:

1. Invalidate cache entries for the affected access scope (same logic)
2. The correction chunk is now in the knowledge base, so subsequent queries will incorporate it

### 9.3 Implementation

Uses the existing POST /admin/cache/invalidate endpoint from Phase 5. Called automatically by both the auto-update and revert processes.

---

## 10. Scheduling

### 10.1 Daily auto-update schedule

| Parameter | Default | Description |
|---|---|---|
| UPDATER_INTERVAL_HOURS | 24 | Hours between auto-update runs |
| UPDATER_RUN_HOUR | 2 | Hour of day (0–23) to run the daily update |
| UPDATER_ENABLED | true | Toggle the scheduled job on/off |

The daily auto-update runs at 2:00 AM by default, processing all active sources sequentially.

### 10.2 Weekly review alert schedule

| Parameter | Default | Description |
|---|---|---|
| REVIEW_ALERT_DAY | friday | Day of week for the weekly review alert |
| REVIEW_ALERT_HOUR | 17 | Hour of day (0–23) to generate and send the alert |

The weekly summary is generated every Friday at 5:00 PM by default.

### 10.3 Execution flow — daily auto-update

1. Iterate through all active data sources
2. Run change detection for each (Section 4)
3. Filter insignificant changes (Section 4.3)
4. For each significant or minor change:
   a. Snapshot the before-state of affected chunks
   b. Re-index the changed content (Section 5)
   c. Generate an LLM summary of the change (Section 6.3)
   d. Store the update record with snapshots and summary
5. Invalidate semantic cache for affected scopes
6. Log completion: sources checked, changes detected, chunks updated

### 10.4 Execution flow — weekly review alert

1. Collect all update records for the current ISO week
2. Generate the weekly narrative summary via Gemini (Section 7.2)
3. Store the weekly review record
4. Flag the review as pending for admin notification
5. Cursor extension picks up the flag on next health ping (shows review badge)
6. CLI banner appears on next command execution

---

## 11. Relationship to Phase 3 Daily Sync

Phase 3 implemented a simple daily sync for Notion that automatically re-processes changed pages. Phase 7 extends this model to GitHub and adds change tracking, summaries, snapshots, and the weekly review layer.

**How they merge:**

- Phase 7's daily auto-update **replaces** Phase 3's daily Notion sync. The same change detection logic is used, but now it produces update records with summaries and snapshots instead of silently re-processing.
- For GitHub, Phase 7 is the first automated update mechanism (Phase 2 only had manual re-sync).
- The daily auto-update schedule (Section 10.1) supersedes Phase 3's `NOTION_SYNC_INTERVAL_HOURS`. Both GitHub and Notion sources are processed in the same daily run.

**Migration:** On Phase 7 deployment, Phase 3's standalone Notion sync scheduler is disabled and replaced by Phase 7's unified scheduler. The `NOTION_SYNC_INTERVAL_HOURS` env var is deprecated in favor of `UPDATER_INTERVAL_HOURS`.

---

## 12. Audit Logging

This phase requires extending the Phase 4 `audit_logs.event_type` enum via Alembic migration to include:

| New event type | When logged |
|---|---|
| auto_update_run | Each daily auto-update execution (one entry per run with source count and change count) |
| update_applied | Each individual update record created (one per changed file/page) |
| update_reverted | When an admin reverts an update |
| correction_applied | When an admin's correction is stored in the knowledge base |
| weekly_review_generated | When the Friday weekly summary is generated |
| weekly_review_acknowledged | When an admin views/acknowledges the weekly review |

---

## 13. API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | /admin/updater/run | admin | Manually trigger immediate auto-update for all sources |
| POST | /admin/updater/run/{source_id} | admin | Manually trigger auto-update for a specific source |
| GET | /admin/updater/history | admin, senior_dev | List update records with pagination and filters |
| GET | /admin/updater/history?week={N}&year={Y} | admin, senior_dev | Filter update records by week |
| GET | /admin/updater/history/{id} | admin, senior_dev | Get full update record with snapshots |
| GET | /admin/updater/review | admin, senior_dev | Get the current week's review summary. Supports `?week={N}&year={Y}` for past weeks. |
| GET | /admin/updater/review/pending | admin, senior_dev | Check if a pending review exists (lightweight, for Cursor badge) |
| POST | /admin/updater/review/{id}/acknowledge | admin, senior_dev | Mark the weekly review as acknowledged |
| POST | /admin/updater/revert/{update_id} | admin, senior_dev | Revert an update with mandatory correction |
| GET | /admin/updater/reverts | admin | List all reverted updates with corrections |
| GET | /admin/updater/stats | admin | Update frequency, revert rate, avg changes per week |

### POST /admin/updater/revert/{update_id} — request body

```json
{
  "correction": "The OAuth2 module is experimental and not yet production-ready. Developers should continue using the JWT authentication flow documented in src/auth/middleware.py until the team announces the OAuth migration."
}
```

**Validation:** `correction` must be at least 20 characters. Empty or trivial corrections are rejected with 400: "Please provide a meaningful correction explaining what the knowledge base should say instead."

---

## 14. Environment Variables (additions)

| Variable | Type | Default | Description |
|---|---|---|---|
| UPDATER_INTERVAL_HOURS | Integer | 24 | Hours between daily auto-update runs |
| UPDATER_RUN_HOUR | Integer | 2 | Hour of day (0–23) to run the daily update |
| UPDATER_ENABLED | Boolean | true | Toggle the daily auto-updater on/off |
| REVIEW_ALERT_DAY | String | friday | Day of week for the weekly review alert |
| REVIEW_ALERT_HOUR | Integer | 17 | Hour of day (0–23) to generate the weekly review |
| UPDATER_MAX_DIFF_TOKENS | Integer | 4000 | Max tokens of diff content sent to Gemini per summary |
| CORRECTION_RETRIEVAL_BOOST | Float | 0.15 | Retrieval score boost for admin correction chunks |

Note: Phase 3's `NOTION_SYNC_INTERVAL_HOURS` is deprecated and replaced by `UPDATER_INTERVAL_HOURS`.

---

## 15. Acceptance Criteria

1. **GitHub change detection:** After committing a new file, modifying an existing file, and deleting a third in a connected repo, the daily auto-update correctly identifies all three changes with the right status (A, M, D).

2. **Notion change detection:** After editing a page, creating a new page, and archiving a page, the daily auto-update correctly identifies all three changes.

3. **Automatic re-indexing:** Changes are re-indexed automatically without human intervention. After the daily auto-update runs, a query about the newly added file returns results from that file.

4. **Significance filtering:** A commit that only modifies `package-lock.json` is skipped entirely (no update record). A commit adding a new Python file produces an update record flagged as significant.

5. **Update record storage:** Each change produces an update_record with correct source_id, change_type, file_or_page, significance, LLM-generated summary, chunks_affected count, snapshot_before, snapshot_after, week_number, and year.

6. **LLM summary quality:** The summary for a new OAuth module addition reads as a coherent, human-friendly explanation (not a raw diff). It mentions the impact on developer questions.

7. **Weekly review generation:** On Friday at the configured hour, a weekly_reviews record is created with narrative summary, update counts, high-risk flags, and recommended reviews. The summary is coherent and actionable.

8. **Cursor weekly alert:** *(Deferred — Phase 7.5.)* `GET /admin/updater/review/pending` returns a pending flag after review generation. Cursor UI (badge, summary card, revert modal) is a follow-up task.

9. **CLI weekly alert:** After the weekly review is generated, the next `arcana` command shows a non-blocking banner. `arcana updater review-week` shows the full summary with change list.

10. **Revert — CLI:** `arcana updater revert <id> --correction "..."` restores the before-state chunks from the snapshot and creates a correction chunk. The update record status changes to `correction_applied`.

11. **Revert — Cursor:** Clicking "Revert" on a change card opens a text input. Submitting a correction (≥20 chars) triggers the revert. The card updates to show the correction.

12. **Mandatory correction:** Attempting to revert without a correction returns 400. Attempting to revert with a correction shorter than 20 characters returns 400.

13. **Correction chunk:** After a revert, the admin's correction text exists as a new chunk in ChromaDB and FTS5 with `source_type = "admin_correction"`, correct access_scope, and retrieval boost of +0.15.

14. **Correction persistence:** After a revert, the next daily auto-update does not overwrite or delete the correction chunk. Both the new auto-update and the correction coexist.

15. **Cache invalidation — auto-update:** After daily re-indexing, cache entries for affected scopes are purged. A query hitting a changed topic goes through the full pipeline.

16. **Cache invalidation — revert:** After a revert + correction, cache entries for the affected scope are purged.

17. **Phase 3 migration:** After Phase 7 deployment, Phase 3's standalone Notion sync is disabled. The `NOTION_SYNC_INTERVAL_HOURS` env var is ignored. Both GitHub and Notion are processed by the unified daily updater.

18. **Manual trigger:** POST /admin/updater/run and `arcana updater run` both trigger immediate auto-update with the same change detection, re-indexing, and record creation as the scheduled run.

19. **Review acknowledgment:** POST /admin/updater/review/{id}/acknowledge marks the review as acknowledged by the admin. GET /admin/updater/review/pending returns false after acknowledgment.

20. **Revert history:** `arcana updater reverts` lists all reverted updates with their corrections, who reverted, and when.

21. **Tests:** At least 25 tests covering: GitHub diff parsing (A/M/D/R status), Notion change detection, significance filtering, automatic re-indexing (add/modify/delete), snapshot storage (before/after), LLM summary generation (mocked Gemini), weekly review generation (mocked Gemini), revert flow (with snapshot restoration), correction chunk creation and persistence, mandatory correction validation, cache invalidation (auto-update and revert), cross-reference update, Phase 3 migration (Notion sync disabled), manual trigger, and review acknowledgment.

---

## 16. Technical Dependencies (additions)

| Package | Version | Purpose |
|---|---|---|
| gitpython | >=3.1 | Already from Phase 2 — git diff and commit history access |
| apscheduler | >=3.10 | Already from Phase 3 — scheduled job execution |

No new dependencies. Phase 7 builds entirely on existing infrastructure.

---

## 17. Estimated Effort

| Task | Estimate | Notes |
|---|---|---|
| GitHub change detection (git diff parsing) | 4–5 hours | Diff parsing, file classification, commit tracking |
| Notion change detection (extends daily sync) | 3–4 hours | Edit time comparison, new/deleted page detection |
| Significance filtering | 2–3 hours | Filter rules, classification |
| Automatic re-indexing with snapshots | 6–7 hours | Before/after snapshot capture, DualStore operations, cross-ref update |
| Update record storage + LLM summaries | 4–5 hours | Schema, Gemini prompt, JSON storage |
| Weekly review generation | 4–5 hours | Weekly grouping, Gemini narrative prompt, storage |
| Weekly alert delivery (Cursor + CLI) | 3–4 hours | Badge, banner, component cards, review-week command |
| Revert flow with correction | 5–6 hours | Snapshot restoration, correction chunk creation, validation, re-embedding |
| Cache invalidation integration | 1–2 hours | Auto-update + revert triggers |
| Scheduling (daily + Friday) | 2–3 hours | APScheduler setup, Phase 3 migration |
| API endpoints | 4–5 hours | All endpoints in Section 13 |
| Alembic migrations | 2–3 hours | update_records table, weekly_reviews table, audit event types |
| Test suite | 7–9 hours | 25+ tests across all components |

**Total estimated effort: 47–61 hours (approximately 2–2.5 weeks at thesis pace)**

---

## 18. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Auto-update introduces incorrect content before admin reviews | Medium | Snapshots enable full revert. Weekly review catches issues within 7 days max. Correction mechanism ensures the fix is better than a simple rollback. |
| LLM-generated summaries are inaccurate or unhelpful | Medium | Summaries are informational (for review), not operational (they don't affect indexing). Bad summaries waste admin time but don't corrupt the knowledge base. Prompt iteration improves quality over time. |
| Snapshot storage grows large over time | Medium | Snapshots store chunk content (text, not embeddings). Typical snapshot: ~2KB per chunk. 100 updates/week × 5 chunks average = ~1MB/week. Add a retention policy: delete snapshots older than 90 days (reverts beyond 90 days are unlikely). |
| Admin doesn't review weekly summary | Low | The knowledge base stays fresh regardless (auto-updates are applied). The review is a quality assurance layer, not a bottleneck. Pending reviews accumulate but don't block anything. |
| Correction chunks accumulate and conflict with auto-updated content | Low | Corrections coexist with auto-updates. The retrieval boost ensures corrections rank higher. Admins can delete stale corrections via CLI. Log a quarterly reminder to review outstanding corrections. |
| Gemini API costs for daily summaries | Low | Each summary is one API call (~500 tokens). Daily across 5 sources with ~10 changes = ~10 calls = ~$0.01/day. Weekly narrative adds 1 more call. Negligible. |

---

## 19. Known Limitations

| ID | Limitation | Production path |
|---|---|---|
| L7.1 | Auto-updates run on a daily schedule. Changes between runs are invisible until the next scheduled run. | Add GitHub webhook support for immediate change detection. Increase Notion polling frequency. |
| L7.2 | Admin corrections are text-only. The admin can't provide a corrected code snippet that replaces the auto-indexed one. | Allow corrections to include code blocks. Parse the correction to generate properly structured chunks (with language, line info) instead of a single text chunk. |
| L7.3 | Only the default branch is tracked. Feature branches and PRs are not indexed. | Add branch selection per source. PR-based indexing for architecture reviews. |
| L7.4 | Snapshots store full chunk content, increasing storage. No automatic snapshot cleanup. | Add a retention policy: delete snapshots older than N days. Compress snapshot content. Store only content diffs instead of full before/after. |
| L7.5 | The daily auto-updater sends code diffs to the Gemini API for summary generation, expanding the data privacy surface. | Same mitigations as LX.1. Self-hosted LLM for summaries. Diff redaction filter for sensitive patterns. |
| L7.6 | Weekly review summary quality depends on Gemini's ability to synthesize a week of changes into actionable insights. The narrative may miss subtle issues or over-flag minor ones. | Iterate on the weekly summary prompt based on admin feedback. Add a "summary was helpful/unhelpful" flag to the acknowledgment flow. |

These limitations are documented in the [Arcana Limitations & Design Decisions Log](./Arcana_Limitations_and_Design_Decisions.md).

---

*End of document*