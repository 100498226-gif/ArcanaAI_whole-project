"""
Ingestion — local .md and .txt files only.

Entry point:
  ingest_local(paths)  — traverse directories → diff → chunk → embed (Gemini)
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import structlog

from arcana.services.chunker import Chunk, chunk_file
from arcana.services.embedder import store_chunks
from arcana.services.local_service import get_file_mtime
from arcana.services.traversal import traverse_repository

log = structlog.get_logger()


# ── ChromaDB diff helpers ─────────────────────────────────────────────────────

def _get_existing_local_timestamps(repo_key: str) -> dict[str, str]:
    """Return {file_path: last_modified} for all chunks stored for this directory."""
    from arcana.vector_store import get_code_collection, get_doc_collection
    timestamps: dict[str, str] = {}
    for col in [get_code_collection(), get_doc_collection()]:
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


# ── Local filesystem ingestion ────────────────────────────────────────────────

async def ingest_local(paths: list[str] | None = None) -> dict:
    """
    Traverse local directories, diff against stored mtimes, embed only changed/new
    .md and .txt files, and clean up chunks for deleted files.
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
        chunks: list[Chunk] = []
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
            _, failed = await store_chunks(chunks)
            total_embedded += len(chunks) - len(failed)
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
