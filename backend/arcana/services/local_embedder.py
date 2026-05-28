"""
Local embedding via sentence-transformers BAAI/bge-base-en-v1.5.

Produces 768-dimensional vectors — the same dimension as gemini-embedding-001 —
so ChromaDB collection schemas are unchanged.

BGE supports asymmetric retrieval:
  - Documents are embedded as-is (no prefix).
  - Queries use the BGE instruction prefix so they are projected into a
    "searching" sub-space, mirroring Gemini's RETRIEVAL_QUERY task type.

The model is lazy-loaded on first call and kept resident in memory for the
session (it is small, ~440 MB). This is the opposite strategy from the local
LLM client (which uses keep_alive=0) because the embedder is used far more
frequently and its memory footprint is negligible compared to the LLM.

Chunks stored with this embedder are tagged embedding_backend="local_bge" so
that retrieval queries never mix them with Gemini vectors in shared collections.
"""
from __future__ import annotations

import asyncio
from functools import lru_cache

import structlog

from arcana.services.chunker import Chunk
from arcana.vector_store import get_code_collection_local, get_doc_collection_local

log = structlog.get_logger()

_MODEL_NAME = "BAAI/bge-base-en-v1.5"
_BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
BATCH_SIZE = 64  # sentence-transformers handles batches efficiently


@lru_cache(maxsize=1)
def _get_model():
    """Lazy-load the sentence-transformers model once per process."""
    from sentence_transformers import SentenceTransformer  # type: ignore[import]

    log.info("local_embedder.loading_model", model=_MODEL_NAME)
    model = SentenceTransformer(_MODEL_NAME)
    log.info("local_embedder.model_ready", model=_MODEL_NAME, dim=model.get_sentence_embedding_dimension())
    return model


def is_model_loaded() -> bool:
    """Return True if the embedding model has already been loaded into memory."""
    return _get_model.cache_info().currsize > 0


async def embed_texts_local(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts using the local model. Runs in executor to avoid blocking."""
    model = _get_model()
    loop = asyncio.get_running_loop()
    embeddings = await loop.run_in_executor(
        None,
        lambda: model.encode(texts, batch_size=BATCH_SIZE, show_progress_bar=False),
    )
    return [emb.tolist() for emb in embeddings]


async def embed_query_local(text: str) -> list[float]:
    """Embed a single query string using the BGE asymmetric query prefix.

    The prefix projects the query into a 'searching' sub-space that aligns
    better with document vectors, mirroring Gemini's RETRIEVAL_QUERY task type.
    """
    result = await embed_texts_local([_BGE_QUERY_PREFIX + text])
    return result[0]


def _clean_meta(metadata: dict) -> dict:
    """ChromaDB requires str/int/float/bool metadata values."""
    return {
        k: (v if isinstance(v, (str, int, float, bool)) else str(v) if v is not None else "")
        for k, v in metadata.items()
    }


async def store_chunks_local(chunks: list[Chunk], batch_delay: float = 0.1) -> tuple[int, list[str]]:
    """
    Embed chunks with the local model and upsert to ChromaDB.
    Mirrors the interface of embedder.store_chunks.
    Returns (embedded_count, failed_chunk_ids).
    """
    if not chunks:
        return 0, []

    code_col = get_code_collection_local()
    doc_col = get_doc_collection_local()
    embedded = 0
    failed: list[str] = []

    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i: i + BATCH_SIZE]
        try:
            embeddings = await embed_texts_local([c.text for c in batch])
        except Exception as exc:
            log.error("local_embedder.batch_error", error=str(exc))
            failed.extend(c.chunk_id for c in batch)
            if i + BATCH_SIZE < len(chunks):
                await asyncio.sleep(batch_delay)
            continue

        code_ids, code_docs, code_embs, code_metas = [], [], [], []
        doc_ids, doc_docs, doc_embs, doc_metas = [], [], [], []

        for chunk, emb in zip(batch, embeddings):
            clean = _clean_meta(chunk.metadata)
            clean["embedding_backend"] = "local_bge"
            if chunk.metadata.get("source_type", "code") == "code":
                code_ids.append(chunk.chunk_id)
                code_docs.append(chunk.text)
                code_embs.append(emb)
                code_metas.append(clean)
            else:
                doc_ids.append(chunk.chunk_id)
                doc_docs.append(chunk.text)
                doc_embs.append(emb)
                doc_metas.append(clean)

        if code_ids:
            code_col.upsert(ids=code_ids, documents=code_docs, embeddings=code_embs, metadatas=code_metas)
            embedded += len(code_ids)
        if doc_ids:
            doc_col.upsert(ids=doc_ids, documents=doc_docs, embeddings=doc_embs, metadatas=doc_metas)
            embedded += len(doc_ids)

        if i + BATCH_SIZE < len(chunks):
            await asyncio.sleep(batch_delay)

    return embedded, failed
