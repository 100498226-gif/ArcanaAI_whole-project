"""
Tests for the local embedder (sentence-transformers BAAI/bge-base-en-v1.5).

The model is lazy-loaded. These tests verify the dimension contract (768-dim),
the asymmetric query-vs-document embedding behaviour, and that the interface
mirrors embedder.py's functions.
"""
import asyncio

import pytest


@pytest.fixture(scope="module")
def embedder_module():
    """Import and warm up the local embedder once per test module."""
    from arcana.services import local_embedder
    # Trigger lazy load so the model is ready before any test runs
    asyncio.run(local_embedder.embed_query_local("warmup"))
    return local_embedder


def test_embed_query_local_returns_768_dims(embedder_module):
    vec = asyncio.run(
        embedder_module.embed_query_local("What does the auth service do?")
    )
    assert isinstance(vec, list)
    assert len(vec) == 768
    assert all(isinstance(v, float) for v in vec)


def test_embed_texts_local_batch(embedder_module):
    texts = ["hello world", "auth service", "database migration"]
    vecs = asyncio.run(
        embedder_module.embed_texts_local(texts)
    )
    assert len(vecs) == 3
    for v in vecs:
        assert len(v) == 768


def test_embed_query_local_deterministic(embedder_module):
    """Same text should produce the same embedding."""
    text = "explain the ingestion pipeline"
    v1 = asyncio.run(embedder_module.embed_query_local(text))
    v2 = asyncio.run(embedder_module.embed_query_local(text))
    assert v1 == v2


def test_embed_texts_local_different_texts_differ(embedder_module):
    v1 = asyncio.run(embedder_module.embed_texts_local(["authentication"]))
    v2 = asyncio.run(embedder_module.embed_texts_local(["database schema"]))
    assert v1[0] != v2[0]


def test_query_embedding_differs_from_document_embedding(embedder_module):
    """Asymmetric check: query prefix must produce a different vector than raw text."""
    text = "authentication service"
    query_vec = asyncio.run(embedder_module.embed_query_local(text))
    doc_vec = asyncio.run(embedder_module.embed_texts_local([text]))
    # BGE query prefix changes the embedding — verify they are not identical
    assert query_vec != doc_vec[0], (
        "embed_query_local should apply the BGE query prefix and produce a "
        "different vector from embed_texts_local for the same text"
    )
