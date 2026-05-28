"""
Vector search: embed query → search ChromaDB collections → return ranked chunks.

Uses Gemini embeddings (3072-dim) against the online collections.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from arcana.config import settings
from arcana.vector_store import get_code_collection, get_doc_collection

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


async def vector_search(
    question: str,
    top_k: int | None = None,
) -> list[RetrievedChunk]:
    """Embed with Gemini, search online collections (3072-dim)."""
    from arcana.services.embedder import embed_query

    k = top_k if top_k is not None else settings.retrieval_top_k
    embedding = await embed_query(question)

    chunks: list[RetrievedChunk] = []
    for collection in [get_code_collection(), get_doc_collection()]:
        try:
            resp = collection.query(
                query_embeddings=[embedding],
                n_results=k,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            log.warning("retrieval.query_error", error=str(exc))
            continue
        _parse_collection_resp(resp, chunks)

    chunks.sort(key=lambda c: c.score, reverse=True)
    chunks = [c for c in chunks if c.score >= settings.score_threshold]
    log.info("retrieval.vector_search", hits=len(chunks))
    return chunks[:k]
