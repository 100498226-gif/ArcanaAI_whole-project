"""
Ingestion orchestrator — no database, writes directly to ChromaDB.

Two entry points:
  ingest_github(repos)      — clone → diff → chunk → embed (skips unchanged files)
  ingest_notion(page_ids)   — traverse Notion API → diff → chunk → embed (skips unchanged pages)

Smart diffing:
  GitHub  — compares each file's last git-commit timestamp against what is stored
             in ChromaDB. Only re-embeds files where the timestamp changed or the
             file is new. Deletes chunks for files that have been removed.
  Notion  — compares each page's last_edited_time from the Notion API against what
             is stored in ChromaDB. Only re-embeds pages that changed or are new.
"""
from __future__ import annotations

import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import structlog

from arcana.config import settings
from arcana.services.chunker import Chunk, chunk_file
from arcana.services.embedder import store_chunks
from arcana.services.github_service import clone_repository, get_file_last_modified
from arcana.services.local_service import get_file_mtime
from arcana.services.notion_chunker import chunk_notion_page
from arcana.services.notion_extractor import traverse_page
from arcana.services.traversal import traverse_repository

log = structlog.get_logger()


# ── Dual-collection storage ───────────────────────────────────────────────────

async def _store_both_collections(chunks: list[Chunk]) -> tuple[int, list[str]]:
    """
    Store chunks in both embedding spaces so the KB is always queryable in
    either online or offline mode.

    Always runs BGE (offline, no external dependency).
    Runs Gemini (online) only when an API key is configured — failures are
    logged and skipped so an absent key never blocks offline-only workflows.
    """
    from arcana.services.local_embedder import store_chunks_local

    all_failed: list[str] = []

    # Offline collections — always available
    embedded_local, failed_local = await store_chunks_local(chunks)
    all_failed.extend(failed_local)

    # Online collections — best-effort; skip if no key
    if settings.gemini_api_key:
        try:
            _, failed_online = await store_chunks(chunks)
            all_failed.extend(failed_online)
        except Exception as exc:
            log.warning("ingestion.store_online_failed", error=str(exc))

    return embedded_local, all_failed


# ── ChromaDB diff helpers ─────────────────────────────────────────────────────

def _get_existing_github_timestamps(repo_name: str) -> dict[str, str]:
    """Return {file_path: last_modified} for all chunks already stored for this repo."""
    from arcana.vector_store import get_code_collection
    try:
        result = get_code_collection().get(
            where={"repo": repo_name},
            include=["metadatas"],
        )
    except Exception:
        return {}
    timestamps: dict[str, str] = {}
    for meta in (result.get("metadatas") or []):
        fp = (meta or {}).get("file_path", "")
        lm = (meta or {}).get("last_modified", "")
        if fp and lm:
            timestamps[fp] = lm
    return timestamps


def _delete_stale_github_chunks(repo_name: str, deleted_paths: set[str]) -> int:
    """Delete chunks for files that no longer exist in the repo. Returns deleted count."""
    from arcana.vector_store import get_code_collection
    col = get_code_collection()
    deleted = 0
    for fp in deleted_paths:
        try:
            result = col.get(
                where={"$and": [{"repo": {"$eq": repo_name}}, {"file_path": {"$eq": fp}}]},
                include=[],
            )
            ids = result.get("ids") or []
            if ids:
                col.delete(ids=ids)
                deleted += len(ids)
        except Exception as exc:
            log.warning("ingestion.github.delete_error", file=fp, error=str(exc))
    return deleted


def _get_existing_notion_timestamps(page_ids: list[str]) -> dict[str, str]:
    """Return {page_id: last_edited_time} for Notion pages already in ChromaDB."""
    from arcana.vector_store import get_doc_collection
    try:
        result = get_doc_collection().get(
            where={"source_type": "notion"},
            include=["metadatas"],
        )
    except Exception:
        return {}
    timestamps: dict[str, str] = {}
    for meta in (result.get("metadatas") or []):
        pid = (meta or {}).get("page_id", "")
        lm = (meta or {}).get("last_edited_time", "")
        if pid and lm:
            timestamps[pid] = lm
    return timestamps


# ── GitHub ingestion ──────────────────────────────────────────────────────────

async def ingest_github(repos: list[str] | None = None) -> dict:
    """
    Clone repos, diff against stored timestamps, embed only changed/new files,
    and clean up chunks for deleted files.
    Falls back to GITHUB_REPOS env var if repos not provided.
    """
    repo_list = repos or [r.strip() for r in settings.github_repos.split(",") if r.strip()]
    token = settings.github_pat

    if not token:
        return {"error": "GITHUB_PAT not set"}
    if not repo_list:
        return {"error": "No repos specified — set GITHUB_REPOS or pass repos list"}

    total_embedded = 0
    total_skipped = 0
    total_deleted = 0
    errors: list[str] = []

    for repo_name in repo_list:
        tmp_dir = Path(tempfile.mkdtemp(prefix="arcana_gh_"))
        try:
            log.info("ingestion.github.cloning", repo=repo_name)
            clone_repository(token, repo_name, tmp_dir)

            files = traverse_repository(tmp_dir)
            ingested_at = datetime.now(timezone.utc).isoformat()

            # Load stored timestamps for this repo — used to skip unchanged files
            existing_timestamps = _get_existing_github_timestamps(repo_name)
            current_paths: set[str] = set()
            chunks = []
            skipped = 0

            for file_info in files:
                fp = file_info["file_path"]
                current_paths.add(fp)
                last_modified = get_file_last_modified(tmp_dir, fp)
                file_info["last_modified"] = last_modified

                # Skip if we have a timestamp and it hasn't changed
                if last_modified and existing_timestamps.get(fp) == last_modified:
                    skipped += 1
                    continue

                try:
                    file_chunks = chunk_file(
                        abs_path=file_info["abs_path"],
                        file_info=file_info,
                        repo_name=repo_name,
                        access_scope="all",
                        ingested_at=ingested_at,
                    )
                    chunks.extend(file_chunks)
                except Exception as exc:
                    errors.append(f"{repo_name}/{fp}: {exc}")

            # Remove chunks for files deleted from the repo
            deleted_paths = set(existing_timestamps.keys()) - current_paths
            deleted_count = 0
            if deleted_paths:
                deleted_count = _delete_stale_github_chunks(repo_name, deleted_paths)
                log.info(
                    "ingestion.github.deleted_stale",
                    repo=repo_name,
                    files=len(deleted_paths),
                    chunks=deleted_count,
                )

            if chunks:
                embedded, failed = await _store_both_collections(chunks)
                total_embedded += embedded
                if failed:
                    errors.append(f"{repo_name}: {len(failed)} chunks failed to embed")

            total_skipped += skipped
            total_deleted += deleted_count

            log.info(
                "ingestion.github.done",
                repo=repo_name,
                new_chunks=len(chunks),
                skipped_files=skipped,
                deleted_files=len(deleted_paths),
            )

        except Exception as exc:
            log.error("ingestion.github.error", repo=repo_name, error=str(exc))
            errors.append(f"{repo_name}: {exc}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return {
        "embedded": total_embedded,
        "skipped_files": total_skipped,
        "deleted_chunks": total_deleted,
        "errors": errors,
    }


# ── Notion ingestion ──────────────────────────────────────────────────────────

async def ingest_notion(page_ids: list[str] | None = None) -> dict:
    """
    Traverse Notion pages, skip those whose last_edited_time hasn't changed,
    chunk and embed the rest.
    Falls back to NOTION_PAGE_IDS env var if page_ids not provided.
    """
    ids = page_ids or [p.strip() for p in settings.notion_page_ids.split(",") if p.strip()]
    token = settings.notion_token

    if not token:
        return {"error": "NOTION_TOKEN not set"}
    if not ids:
        return {"error": "No page IDs specified — set NOTION_PAGE_IDS or pass page_ids list"}

    delay = settings.notion_request_delay_ms / 1000.0
    max_depth = settings.notion_max_depth
    ingested_at = datetime.now(timezone.utc).isoformat()

    # Load stored timestamps — used to skip unchanged pages
    existing_notion = _get_existing_notion_timestamps(ids)

    all_chunks = []
    errors: list[str] = []
    skipped_pages = 0
    visited: set[str] = set()

    for page_id in ids:
        try:
            page_results = traverse_page(
                token=token,
                page_id=page_id,
                page_title=page_id,
                page_path=["Notion"],
                max_depth=max_depth,
                current_depth=0,
                visited=visited,
                delay=delay,
            )
        except Exception as exc:
            log.error("ingestion.notion.traverse_error", page_id=page_id, error=str(exc))
            errors.append(f"page {page_id}: {exc}")
            continue

        for page_info in page_results:
            if page_info.get("skipped_reason"):
                continue

            pid = page_info.get("page_id", "")
            last_edited = page_info.get("last_edited_time", "")

            # Skip if page hasn't been edited since last ingest
            if last_edited and existing_notion.get(pid) == last_edited:
                log.debug("ingestion.notion.skipped_unchanged", page_id=pid)
                skipped_pages += 1
                continue

            try:
                chunks = chunk_notion_page(
                    page_info=page_info,
                    workspace_name="Notion",
                    access_scope="all",
                    ingested_at=ingested_at,
                )
                all_chunks.extend(chunks)
            except Exception as exc:
                errors.append(f"page {page_info.get('page_id', page_id)}: {exc}")

    total_embedded = 0
    if all_chunks:
        total_embedded, failed = await _store_both_collections(all_chunks)
        if failed:
            errors.append(f"{len(failed)} chunks failed to embed")

    log.info(
        "ingestion.notion.done",
        new_chunks=len(all_chunks),
        embedded=total_embedded,
        skipped_pages=skipped_pages,
    )
    return {
        "embedded": total_embedded,
        "skipped_pages": skipped_pages,
        "errors": errors,
    }


# ── Local filesystem ingestion ────────────────────────────────────────────────

def _get_existing_local_timestamps(repo_key: str) -> dict[str, str]:
    """Return {file_path: last_modified} for all chunks stored for this local directory.

    Checks all four collections (online + offline) so the diff stays correct
    regardless of which embedding space was used on the previous ingest.
    """
    from arcana.vector_store import (
        get_code_collection, get_doc_collection,
        get_code_collection_local, get_doc_collection_local,
    )
    timestamps: dict[str, str] = {}
    collections = [
        get_code_collection(), get_doc_collection(),
        get_code_collection_local(), get_doc_collection_local(),
    ]
    for col in collections:
        try:
            result = col.get(where={"repo": repo_key}, include=["metadatas"])
            for meta in (result.get("metadatas") or []):
                fp = (meta or {}).get("file_path", "")
                lm = (meta or {}).get("last_modified", "")
                if fp and lm:
                    timestamps[fp] = lm
        except Exception as exc:
            log.warning("ingestion.local.timestamps_error", repo_key=repo_key, error=str(exc))
    return timestamps


def _delete_stale_local_chunks(repo_key: str, deleted_paths: set[str]) -> int:
    """Delete chunks for files removed from the local directory. Returns deleted count."""
    from arcana.vector_store import get_code_collection, get_doc_collection
    deleted = 0
    for col in [get_code_collection(), get_doc_collection()]:
        for fp in deleted_paths:
            try:
                result = col.get(
                    where={"$and": [{"repo": {"$eq": repo_key}}, {"file_path": {"$eq": fp}}]},
                    include=[],
                )
                ids = result.get("ids") or []
                if ids:
                    col.delete(ids=ids)
                    deleted += len(ids)
            except Exception as exc:
                log.warning("ingestion.local.delete_error", file=fp, error=str(exc))
    return deleted


async def ingest_local(paths: list[str] | None = None) -> dict:
    """
    Traverse local directories, diff against stored mtimes, embed only changed/new files,
    and clean up chunks for deleted files.
    """
    if not paths:
        return {"error": "No paths specified — pass a list of absolute directory paths"}

    total_embedded = 0
    total_skipped = 0
    total_deleted = 0
    errors: list[str] = []

    for local_path_str in paths:
        local_path = Path(local_path_str)
        if not local_path.is_dir():
            errors.append(f"{local_path_str}: not a directory or does not exist")
            continue

        repo_key = f"local:{local_path.resolve()}"
        ingested_at = datetime.now(timezone.utc).isoformat()
        existing_timestamps = _get_existing_local_timestamps(repo_key)

        files = traverse_repository(local_path)
        current_paths: set[str] = set()
        chunks = []
        skipped = 0

        for file_info in files:
            fp = file_info["file_path"]
            current_paths.add(fp)
            last_modified = get_file_mtime(file_info["abs_path"])
            file_info["last_modified"] = last_modified

            if last_modified and existing_timestamps.get(fp) == last_modified:
                skipped += 1
                continue

            try:
                file_chunks = chunk_file(
                    abs_path=file_info["abs_path"],
                    file_info=file_info,
                    repo_name=repo_key,
                    access_scope="all",
                    ingested_at=ingested_at,
                )
                chunks.extend(file_chunks)
            except Exception as exc:
                errors.append(f"{local_path_str}/{fp}: {exc}")

        deleted_paths = set(existing_timestamps.keys()) - current_paths
        deleted_count = 0
        if deleted_paths:
            deleted_count = _delete_stale_local_chunks(repo_key, deleted_paths)
            log.info(
                "ingestion.local.deleted_stale",
                path=local_path_str,
                files=len(deleted_paths),
                chunks=deleted_count,
            )

        if chunks:
            embedded, failed = await _store_both_collections(chunks)
            total_embedded += embedded
            if failed:
                errors.append(f"{local_path_str}: {len(failed)} chunks failed to embed")

        total_skipped += skipped
        total_deleted += deleted_count

        log.info(
            "ingestion.local.done",
            path=local_path_str,
            new_chunks=len(chunks),
            skipped_files=skipped,
            deleted_files=len(deleted_paths),
        )

    return {
        "embedded": total_embedded,
        "skipped_files": total_skipped,
        "deleted_chunks": total_deleted,
        "errors": errors,
    }
