"""
Embedding generation (Google Gemini) and ChromaDB storage.
"""
from __future__ import annotations

import asyncio
import random

import structlog

from arcana.config import settings
from arcana.services.chunker import Chunk
from arcana.vector_store import get_code_collection, get_doc_collection

log = structlog.get_logger()

BATCH_SIZE = 20
_MAX_RETRIES = 6


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts using Gemini with exponential backoff on 429."""
    from google.genai import types  # type: ignore[import]

    client = settings.build_google_client()

    for attempt in range(_MAX_RETRIES):
        try:
            result = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: client.models.embed_content(
                    model=settings.embedding_model,
                    contents=texts,
                    config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
                ),
            )
            return [list(e.values) for e in result.embeddings]
        except Exception as exc:
            msg = str(exc)
            is_rate_limit = "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower()
            if is_rate_limit and attempt < _MAX_RETRIES - 1:
                delay = (2 ** attempt) + random.uniform(0, 1)
                log.warning("embedder.rate_limited", attempt=attempt + 1, delay=round(delay, 1))
                await asyncio.sleep(delay)
            else:
                raise


async def embed_query(text: str) -> list[float]:
    """Embed a single query string (uses RETRIEVAL_QUERY task type for asymmetric retrieval)."""
    from google.genai import types  # type: ignore[import]

    client = settings.build_google_client()
    result = await asyncio.get_running_loop().run_in_executor(
        None,
        lambda: client.models.embed_content(
            model=settings.embedding_model,
            contents=[text],
            config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
        ),
    )
    return list(result.embeddings[0].values)


def _clean_meta(metadata: dict) -> dict:
    """ChromaDB requires str/int/float/bool metadata values."""
    return {
        k: (v if isinstance(v, (str, int, float, bool)) else str(v) if v is not None else "")
        for k, v in metadata.items()
    }


async def store_chunks(chunks: list[Chunk], batch_delay: float = 2.0) -> tuple[int, list[str]]:
    """
    Embed chunks in batches and upsert to ChromaDB.
    Returns (embedded_count, failed_chunk_ids).
    """
    if not chunks:
        return 0, []

    code_col = get_code_collection()
    doc_col = get_doc_collection()
    embedded = 0
    failed: list[str] = []

    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i: i + BATCH_SIZE]
        try:
            embeddings = await embed_texts([c.text for c in batch])
        except Exception:
            failed.extend(c.chunk_id for c in batch)
            if i + BATCH_SIZE < len(chunks):
                await asyncio.sleep(batch_delay)
            continue

        code_ids, code_docs, code_embs, code_metas = [], [], [], []
        doc_ids, doc_docs, doc_embs, doc_metas = [], [], [], []

        for chunk, emb in zip(batch, embeddings):
            clean = _clean_meta(chunk.metadata)
            clean["embedding_backend"] = "gemini"
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
