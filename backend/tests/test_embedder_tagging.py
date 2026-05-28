"""
Tests that store_chunks / store_chunks_local tag every upserted chunk with
the correct embedding_backend metadata value.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from arcana.services.chunker import Chunk


def _make_chunk(chunk_id: str, source_type: str = "code") -> Chunk:
    return Chunk(
        text="some code content",
        metadata={
            "repo": "test_repo",
            "file_path": "src/main.py",
            "language": "python",
            "source_type": source_type,
            "access_scope": "public",
            "ingested_at": "2026-01-01T00:00:00",
        },
        chunk_id=chunk_id,
    )


def test_store_chunks_tags_gemini_backend():
    """store_chunks must set embedding_backend='gemini' on every upserted chunk."""
    chunks = [_make_chunk("c1"), _make_chunk("c2", source_type="documentation")]
    embeddings = [[0.1] * 768, [0.2] * 768]

    mock_code_col = MagicMock()
    mock_doc_col = MagicMock()

    with patch("arcana.services.embedder.embed_texts", new_callable=AsyncMock,
               return_value=embeddings), \
         patch("arcana.services.embedder.get_code_collection", return_value=mock_code_col), \
         patch("arcana.services.embedder.get_doc_collection", return_value=mock_doc_col):

        from arcana.services.embedder import store_chunks
        asyncio.run(store_chunks(chunks, batch_delay=0.0))

    # Code chunk → code collection
    code_call_kwargs = mock_code_col.upsert.call_args.kwargs
    for meta in code_call_kwargs["metadatas"]:
        assert meta.get("embedding_backend") == "gemini", (
            f"Code chunk missing/wrong embedding_backend tag: {meta}"
        )

    # Doc chunk → doc collection
    doc_call_kwargs = mock_doc_col.upsert.call_args.kwargs
    for meta in doc_call_kwargs["metadatas"]:
        assert meta.get("embedding_backend") == "gemini", (
            f"Doc chunk missing/wrong embedding_backend tag: {meta}"
        )


def test_store_chunks_local_tags_local_bge_backend():
    """store_chunks_local must set embedding_backend='local_bge' on every upserted chunk."""
    chunks = [_make_chunk("c1"), _make_chunk("c2", source_type="documentation")]
    embeddings = [[0.3] * 768, [0.4] * 768]

    mock_code_col = MagicMock()
    mock_doc_col = MagicMock()

    with patch("arcana.services.local_embedder.embed_texts_local", new_callable=AsyncMock,
               return_value=embeddings), \
         patch("arcana.services.local_embedder.get_code_collection_local", return_value=mock_code_col), \
         patch("arcana.services.local_embedder.get_doc_collection_local", return_value=mock_doc_col):

        from arcana.services.local_embedder import store_chunks_local
        asyncio.run(store_chunks_local(chunks, batch_delay=0.0))

    code_call_kwargs = mock_code_col.upsert.call_args.kwargs
    for meta in code_call_kwargs["metadatas"]:
        assert meta.get("embedding_backend") == "local_bge", (
            f"Code chunk missing/wrong embedding_backend tag: {meta}"
        )

    doc_call_kwargs = mock_doc_col.upsert.call_args.kwargs
    for meta in doc_call_kwargs["metadatas"]:
        assert meta.get("embedding_backend") == "local_bge", (
            f"Doc chunk missing/wrong embedding_backend tag: {meta}"
        )
