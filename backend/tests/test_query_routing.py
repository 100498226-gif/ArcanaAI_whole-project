"""
Tests for query_service routing: verifies Gemini vs Ollama path selection
based on online_mode.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


async def _collect(gen):
    """Drain an async generator into a list."""
    return [item async for item in gen]


@pytest.mark.asyncio
async def test_online_mode_uses_gemini_stream():
    """In online mode, run_query_stream should call Gemini stream_response."""
    async def fake_stream(*_a, **_kw):
        for c in ["hello"]:
            yield c

    with patch("arcana.services.query_service.get_online_mode", return_value=True), \
         patch("arcana.services.query_service.vector_search", new_callable=AsyncMock,
               return_value=[MagicMock()]), \
         patch("arcana.services.query_service.assemble_context",
               return_value=MagicMock(chunks=[MagicMock()])), \
         patch("arcana.services.query_service.build_prompt", return_value=MagicMock()), \
         patch("arcana.services.query_service.stream_response", side_effect=fake_stream) as mock_gemini, \
         patch("arcana.services.query_service.vector_search_offline") as mock_offline_search:

        from arcana.services.query_service import run_query_stream
        events = await _collect(run_query_stream("test question"))

    mock_gemini.assert_called_once()
    mock_offline_search.assert_not_called()
    event_types = [e["event"] for e in events]
    assert "chunk" in event_types
    assert "done" in event_types


@pytest.mark.asyncio
async def test_offline_mode_uses_ollama_stream():
    """In offline mode, run_query_stream should call local_stream_response."""
    async def fake_local_stream(*_a, **_kw):
        yield "local answer"

    with patch("arcana.services.query_service.get_online_mode", return_value=False), \
         patch("arcana.services.query_service.vector_search_offline", new_callable=AsyncMock,
               return_value=[MagicMock()]), \
         patch("arcana.services.query_service.assemble_context",
               return_value=MagicMock(chunks=[MagicMock()])), \
         patch("arcana.services.query_service.build_prompt", return_value=MagicMock()), \
         patch("arcana.services.local_llm_client.stream_response",
               side_effect=fake_local_stream) as mock_local, \
         patch("arcana.services.query_service.vector_search") as mock_online_search:

        import importlib
        import arcana.services.query_service as qs
        importlib.reload(qs)
        events = await _collect(qs.run_query_stream("test question"))

    mock_online_search.assert_not_called()



@pytest.mark.asyncio
async def test_offline_path_uses_reduced_token_budget():
    """Offline RAG path must call assemble_context with token_budget=3500."""
    async def fake_local_stream(*_a, **_kw):
        yield "answer"

    mock_assemble = MagicMock(return_value=MagicMock(chunks=[MagicMock()]))

    with patch("arcana.services.query_service.get_online_mode", return_value=False), \
         patch("arcana.services.query_service.load_settings", return_value={"offline_use_context": True}), \
         patch("arcana.services.query_service.vector_search_offline", new_callable=AsyncMock,
               return_value=[MagicMock()]), \
         patch("arcana.services.query_service.assemble_context", mock_assemble), \
         patch("arcana.services.query_service.build_prompt", return_value=MagicMock()), \
         patch("arcana.services.query_service.local_stream_response", side_effect=fake_local_stream):

        from arcana.services.query_service import run_query_stream
        await _collect(run_query_stream("what is the auth service?"))

    mock_assemble.assert_called_once()
    _, kwargs = mock_assemble.call_args
    assert kwargs.get("token_budget") == 3500, (
        f"Expected token_budget=3500 for offline path, got {kwargs.get('token_budget')}"
    )


@pytest.mark.asyncio
async def test_offline_path_uses_offline_prompt():
    """Offline RAG path must call build_prompt with offline=True."""
    async def fake_local_stream(*_a, **_kw):
        yield "answer"

    mock_build = MagicMock(return_value=MagicMock())

    with patch("arcana.services.query_service.get_online_mode", return_value=False), \
         patch("arcana.services.query_service.load_settings", return_value={"offline_use_context": True}), \
         patch("arcana.services.query_service.vector_search_offline", new_callable=AsyncMock,
               return_value=[MagicMock()]), \
         patch("arcana.services.query_service.assemble_context",
               return_value=MagicMock(chunks=[MagicMock()])), \
         patch("arcana.services.query_service.build_prompt", mock_build), \
         patch("arcana.services.query_service.local_stream_response", side_effect=fake_local_stream):

        from arcana.services.query_service import run_query_stream
        await _collect(run_query_stream("what is the auth service?"))

    mock_build.assert_called_once()
    _, kwargs = mock_build.call_args
    assert kwargs.get("offline") is True, (
        f"Expected offline=True for offline prompt path, got {kwargs.get('offline')}"
    )


@pytest.mark.asyncio
async def test_online_path_does_not_use_offline_prompt():
    """Online RAG path must NOT pass offline=True to build_prompt."""
    async def fake_stream(*_a, **_kw):
        yield "answer"

    mock_build = MagicMock(return_value=MagicMock())

    with patch("arcana.services.query_service.get_online_mode", return_value=True), \
         patch("arcana.services.query_service.vector_search", new_callable=AsyncMock,
               return_value=[MagicMock()]), \
         patch("arcana.services.query_service.assemble_context",
               return_value=MagicMock(chunks=[MagicMock()])), \
         patch("arcana.services.query_service.build_prompt", mock_build), \
         patch("arcana.services.query_service.stream_response", side_effect=fake_stream):

        from arcana.services.query_service import run_query_stream
        await _collect(run_query_stream("what is the auth service?"))

    mock_build.assert_called_once()
    _, kwargs = mock_build.call_args
    assert kwargs.get("offline") is not True


def test_identity_question_bypasses_mode():
    """Identity questions always return hardcoded response without touching LLM or mode."""
    from arcana.services.query_service import run_query_stream

    with patch("arcana.services.query_service.get_online_mode", return_value=False), \
         patch("arcana.services.query_service.vector_search_offline") as mock_search:
        events = asyncio.run(_collect(run_query_stream("who are you")))

    mock_search.assert_not_called()
    assert any(e["event"] == "chunk" for e in events)
    assert any(e["event"] == "done" for e in events)


@pytest.mark.asyncio
async def test_offline_kb_miss_yields_needs_online():
    """Offline mode with no KB results must yield 'needs_online' event, not fallback to LLM."""
    with patch("arcana.services.query_service.get_online_mode", return_value=False), \
         patch("arcana.services.query_service.load_settings", return_value={"offline_use_context": True}), \
         patch("arcana.services.query_service.vector_search_offline", new_callable=AsyncMock,
               return_value=[]), \
         patch("arcana.services.query_service.local_stream_response") as mock_local:

        from arcana.services.query_service import run_query_stream
        events = await _collect(run_query_stream("unknown topic"))

    mock_local.assert_not_called()
    assert len(events) == 1
    assert events[0]["event"] == "needs_online"
    assert events[0]["data"]["question"] == "unknown topic"
