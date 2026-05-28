"""
Vector search: embed query → search ChromaDB collections → return ranked chunks.

Two public entry points:
  vector_search(question)         — online path (Gemini embeddings, 3072-dim)
  vector_search_offline(question) — offline path (BGE embeddings, 768-dim)

Each path uses its own pair of ChromaDB collections so the two embedding
spaces are never mixed:
  Online  → code_chunks      / doc_chunks        (Gemini, 3072-dim)
  Offline → code_chunks_local / doc_chunks_local  (BGE,    768-dim)
"""
from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from arcana.config import settings
from arcana.vector_store import (
    get_code_collection,
    get_code_collection_local,
    get_doc_collection,
    get_doc_collection_local,
)

log = structlog.get_logger()


@dataclass
class RetrievedChunk:
    chunk_id: str
    content: str
    source_type: str
    repo: str
    file_path: str
    symbol_name: str
    page_title: str
    score: float
    metadata: dict = field(default_factory=dict)


def _parse_collection_resp(
    resp: dict,
    chunks: list[RetrievedChunk],
) -> None:
    """Append RetrievedChunk objects parsed from a ChromaDB query response."""
    ids = (resp.get("ids") or [[]])[0]
    docs = (resp.get("documents") or [[]])[0]
    metas = (resp.get("metadatas") or [[]])[0]
    distances = (resp.get("distances") or [[]])[0]

    for chunk_id, doc, meta, dist in zip(ids, docs, metas, distances):
        meta = meta or {}
        chunks.append(
            RetrievedChunk(
                chunk_id=chunk_id,
                content=doc or "",
                source_type=str(meta.get("source_type", "")),
                repo=str(meta.get("repo", "")),
                file_path=str(meta.get("file_path", "")),
                symbol_name=str(meta.get("symbol_name", "")),
                page_title=str(meta.get("page_title", "")),
                score=1.0 - dist,  # cosine distance → similarity
                metadata=meta,
            )
        )


def _run_search(
    collections: list,
    embedding: list[float],
    top_k: int,
    label: str,
) -> list[RetrievedChunk]:
    """Query a list of ChromaDB collections, sort, threshold, and return top-k."""
    chunks: list[RetrievedChunk] = []

    for collection in collections:
        try:
            resp = collection.query(
                query_embeddings=[embedding],
                n_results=top_k,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            log.warning("retrieval.query_error", error=str(exc))
            continue
        _parse_collection_resp(resp, chunks)

    chunks.sort(key=lambda c: c.score, reverse=True)
    chunks = [c for c in chunks if c.score >= settings.score_threshold]
    log.info(f"retrieval.{label}", hits=len(chunks))
    return chunks[:top_k]


async def vector_search(
    question: str,
    top_k: int | None = None,
) -> list[RetrievedChunk]:
    """Online path: embed with Gemini, search Gemini collections (3072-dim)."""
    from arcana.services.embedder import embed_query

    k = top_k if top_k is not None else settings.retrieval_top_k
    embedding = await embed_query(question)
    return _run_search(
        [get_code_collection(), get_doc_collection()],
        embedding, k, "vector_search",
    )


async def vector_search_offline(
    question: str,
    top_k: int | None = None,
) -> list[RetrievedChunk]:
    """Offline path: embed with BGE, search local BGE collections (768-dim)."""
    from arcana.services.local_embedder import embed_query_local

    k = top_k if top_k is not None else settings.retrieval_top_k
    embedding = await embed_query_local(question)
    return _run_search(
        [get_code_collection_local(), get_doc_collection_local()],
        embedding, k, "vector_search_offline",
    )
