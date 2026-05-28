"""
Unit tests for retrieval._run_search.

Verifies:
  - Score threshold filters out low-similarity chunks.
  - Online path queries the Gemini collections (code_chunks, doc_chunks).
  - Offline path queries the BGE local collections (code_chunks_local, doc_chunks_local).
  - The two paths never share collections (dimension isolation).
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from arcana.services.retrieval import _run_search


def _make_chroma_resp(ids, distances):
    """Build a minimal ChromaDB query response dict."""
    return {
        "ids": [ids],
        "documents": [["doc content"] * len(ids)],
        "metadatas": [[{"source_type": "code", "repo": "r", "file_path": "f.py",
                        "symbol_name": "", "page_title": ""}] * len(ids)],
        "distances": [distances],
    }


def _make_collection(resp):
    col = MagicMock()
    col.query.return_value = resp
    return col


def test_score_threshold_filters_low_quality_chunks():
    """Chunks with score below settings.score_threshold should be discarded."""
    # distances: 0.5 → score 0.5 (kept), 0.8 → score 0.2 (dropped, below 0.3)
    resp = _make_chroma_resp(["c1", "c2"], [0.5, 0.8])
    col = _make_collection(resp)

    chunks = _run_search([col], [0.0] * 768, top_k=10, label="test")

    assert len(chunks) == 1
    assert chunks[0].chunk_id == "c1"
    assert chunks[0].score == pytest.approx(0.5)


def test_run_search_returns_empty_on_no_results():
    """Empty collection response should return empty list without error."""
    resp = _make_chroma_resp([], [])
    col = _make_collection(resp)

    chunks = _run_search([col], [0.0] * 768, top_k=5, label="test")
    assert chunks == []


def test_run_search_tolerates_collection_error():
    """A failing collection should be skipped; other collections still searched."""
    bad_col = MagicMock()
    bad_col.query.side_effect = Exception("DB error")

    good_col = _make_collection(_make_chroma_resp(["c1"], [0.1]))

    chunks = _run_search([bad_col, good_col], [0.0] * 768, top_k=5, label="test")
    assert len(chunks) == 1
    assert chunks[0].chunk_id == "c1"


def test_online_path_uses_gemini_collections():
    """vector_search must query code_chunks and doc_chunks (Gemini collections)."""
    import asyncio
    from unittest.mock import patch, AsyncMock, MagicMock

    mock_col = _make_collection(_make_chroma_resp(["c1"], [0.1]))

    with patch("arcana.services.retrieval.get_code_collection", return_value=mock_col), \
         patch("arcana.services.retrieval.get_doc_collection", return_value=_make_collection(
             _make_chroma_resp([], []))), \
         patch("arcana.services.embedder.embed_query", new_callable=AsyncMock,
               return_value=[0.0] * 3072):

        from arcana.services.retrieval import vector_search
        asyncio.run(vector_search("test question"))

    mock_col.query.assert_called_once()


def test_offline_path_uses_local_collections():
    """vector_search_offline must query code_chunks_local and doc_chunks_local."""
    import asyncio

    mock_col = _make_collection(_make_chroma_resp(["c1"], [0.1]))

    with patch("arcana.services.retrieval.get_code_collection_local", return_value=mock_col), \
         patch("arcana.services.retrieval.get_doc_collection_local", return_value=_make_collection(
             _make_chroma_resp([], []))), \
         patch("arcana.services.local_embedder.embed_query_local", new_callable=AsyncMock,
               return_value=[0.0] * 768):

        from arcana.services.retrieval import vector_search_offline
        asyncio.run(vector_search_offline("test question"))

    mock_col.query.assert_called_once()
