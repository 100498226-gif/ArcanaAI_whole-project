"""
Query pipeline: embed → retrieve → build prompt → stream response.

Routes to Gemini (online) or Ollama (offline) based on current settings.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

import structlog

from arcana.config import settings
from arcana.services.context_assembler import assemble_context
from arcana.services.gemini_client import GeminiConfigError, stream_fallback, stream_response
from arcana.services.local_llm_client import OllamaError
from arcana.services.local_llm_client import stream_fallback as local_stream_fallback
from arcana.services.local_llm_client import stream_response as local_stream_response
from arcana.services.prompt_builder import build_prompt
from arcana.services.retrieval import vector_search, vector_search_offline
from arcana.services.settings_store import get_online_mode, load_settings

log = structlog.get_logger()

_KB_FALLBACK_NOTICE = (
    "⚠️ **No relevant information found in the knowledge base.** "
    "The following answer comes from general AI knowledge:\n\n"
)

_IDENTITY_RESPONSE = """\
I'm **Arcana** — a RAG-powered knowledge assistant built for developers.

I index your local documents and files (.md and .txt), \
then let you ask questions in plain language and get answers grounded in your \
actual source material — with source citations so you can verify every claim.

**What I can help with:**
- Understanding how a specific piece of code works
- Finding where something is implemented across repos
- Summarising documentation pages
- Answering follow-up questions with full conversation context

When I can't find relevant information in the knowledge base, I fall back to \
general AI knowledge and clearly flag it as such.

Ask me anything about your codebase or docs.
"""

_IDENTITY_PATTERNS = (
    "who are you", "what are you", "who is arcana", "what is arcana",
    "introduce yourself", "tell me about yourself", "what can you do",
    "what do you do", "help", "how do you work",
)


def _is_identity_question(question: str) -> bool:
    q = question.lower().strip().rstrip("?").strip()
    return any(q == p or q.startswith(p) for p in _IDENTITY_PATTERNS)


async def run_query_stream(
    question: str,
    history: list[dict] | None = None,
) -> AsyncGenerator[dict, None]:
    """
    Run the full RAG pipeline and yield SSE event dicts.

    Online mode  → Gemini embedding + Gemini LLM
    Offline mode → local embedding + Ollama LLM

    Event shapes:
      {"event": "chunk", "data": {"text": "..."}}
      {"event": "done",  "data": {"chunks_used": N}}
      {"event": "error", "data": {"message": "..."}}
    """
    # 0. Identity shortcut — no KB or LLM needed
    if _is_identity_question(question):
        log.info("query_service.identity_response")
        yield {"event": "chunk", "data": {"text": _IDENTITY_RESPONSE}}
        yield {"event": "done", "data": {"chunks_used": 0}}
        return

    online = get_online_mode()
    log.info("query_service.mode", online=online)

    # ── ONLINE PATH (Gemini) ──────────────────────────────────────────────────
    if online:
        # 1. Retrieve
        try:
            chunks = await vector_search(question)
        except Exception as exc:
            log.error("query_service.search_error", error=str(exc))
            yield {"event": "error", "data": {"message": "Search failed."}}
            return

        # 2a. No KB results → direct Gemini fallback
        if not chunks:
            log.info("query_service.kb_miss_fallback")
            yield {"event": "chunk", "data": {"text": _KB_FALLBACK_NOTICE}}
            try:
                async for raw_chunk in stream_fallback(question, history=history):
                    if raw_chunk.startswith("__ERROR__:"):
                        yield {"event": "error", "data": {"message": raw_chunk[len("__ERROR__:"):]}}
                        return
                    yield {"event": "chunk", "data": {"text": raw_chunk}}
            except GeminiConfigError as exc:
                log.error("query_service.gemini_config_error", error=str(exc))
                yield {"event": "error", "data": {"message": "LLM configuration error."}}
                return
            yield {"event": "done", "data": {"chunks_used": 0}}
            return

        # 2b. KB results found → RAG path
        context = assemble_context(chunks)
        prompt_pkg = build_prompt(question, context.chunks, history=history)

        try:
            async for raw_chunk in stream_response(prompt_pkg):
                if raw_chunk.startswith("__ERROR__:"):
                    yield {"event": "error", "data": {"message": raw_chunk[len("__ERROR__:"):]}}
                    return
                yield {"event": "chunk", "data": {"text": raw_chunk}}
        except GeminiConfigError as exc:
            log.error("query_service.gemini_config_error", error=str(exc))
            yield {"event": "error", "data": {"message": "LLM configuration error."}}
            return
        except Exception as exc:
            log.error("query_service.gemini_error", error=str(exc))
            yield {"event": "error", "data": {"message": "Service temporarily unavailable."}}
            return

        yield {"event": "done", "data": {"chunks_used": len(context.chunks)}}
        return

    # ── OFFLINE PATH (Ollama) ─────────────────────────────────────────────────
    ollama_model = settings.ollama_fast_model
    log.info("query_service.offline_model", model=ollama_model)

    # Check whether KB context is enabled for offline mode
    offline_use_context = load_settings().get("offline_use_context", True)

    if not offline_use_context:
        log.info("query_service.offline_no_context")
        try:
            async for raw_chunk in local_stream_fallback(question, history=history, model_name=ollama_model):
                if raw_chunk.startswith("__ERROR__:"):
                    yield {"event": "error", "data": {"message": raw_chunk[len("__ERROR__:"):]}}
                    return
                yield {"event": "chunk", "data": {"text": raw_chunk}}
        except OllamaError as exc:
            log.error("query_service.ollama_error", error=str(exc))
            yield {"event": "error", "data": {"message": str(exc)}}
            return
        except Exception as exc:
            log.error("query_service.offline_error", error=str(exc))
            yield {"event": "error", "data": {"message": "Local model temporarily unavailable."}}
            return
        yield {"event": "done", "data": {"chunks_used": 0}}
        return

    # 1. Retrieve (local embedding)
    try:
        chunks = await vector_search_offline(question)
    except Exception as exc:
        log.error("query_service.offline_search_error", error=str(exc))
        yield {"event": "error", "data": {"message": "Offline search failed."}}
        return

    # 2a. No KB results → prompt user to go online
    if not chunks:
        log.info("query_service.offline_kb_miss_prompt_online")
        yield {"event": "needs_online", "data": {"question": question}}
        return

    # 2b. KB results found → offline RAG path
    context = assemble_context(chunks, token_budget=3500)
    prompt_pkg = build_prompt(question, context.chunks, history=history, offline=True)

    try:
        async for raw_chunk in local_stream_response(prompt_pkg, model_name=ollama_model):
            if raw_chunk.startswith("__ERROR__:"):
                yield {"event": "error", "data": {"message": raw_chunk[len("__ERROR__:"):]}}
                return
            yield {"event": "chunk", "data": {"text": raw_chunk}}
    except OllamaError as exc:
        log.error("query_service.ollama_error", error=str(exc))
        yield {"event": "error", "data": {"message": str(exc)}}
        return
    except Exception as exc:
        log.error("query_service.offline_error", error=str(exc))
        yield {"event": "error", "data": {"message": "Local model temporarily unavailable."}}
        return

    yield {"event": "done", "data": {"chunks_used": len(context.chunks)}}
