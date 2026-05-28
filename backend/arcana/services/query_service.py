"""
Query pipeline: embed → retrieve → build prompt → stream response.

Always uses Gemini (online path). Persists conversations and messages to DB.

SSE event shapes:
  {"event": "chunk",       "data": {"text": "..."}}
  {"event": "done",        "data": {"chunks_used": N, "sources": [...], "conversation_id": N}}
  {"event": "out_of_scope","data": {"question": "...", "conversation_id": N}}
  {"event": "error",       "data": {"message": "..."}}
"""
from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path

import structlog
from sqlalchemy import select

from arcana.services.context_assembler import assemble_context
from arcana.services.gemini_client import GeminiConfigError, stream_fallback, stream_response
from arcana.services.prompt_builder import build_prompt
from arcana.services.retrieval import RetrievedChunk, vector_search

log = structlog.get_logger()


_IDENTITY_RESPONSE = """\
I'm Arcana, your personal document assistant.

I index your local files (.md and .txt) and let you ask questions in plain language, \
getting answers grounded in your actual documents, with source citations so you can verify every claim.

What I can help with:
- Finding information in your uploaded documents
- Answering questions from contracts, invoices, meeting notes, policies, and more
- Following up with context-aware questions in the same conversation

Upload your files using the 'Sync here' button and ask me anything.
"""

_IDENTITY_PATTERNS = (
    "who are you", "what are you", "who is arcana", "what is arcana",
    "introduce yourself", "tell me about yourself", "what can you do",
    "what do you do", "help", "how do you work",
)


def _is_identity_question(question: str) -> bool:
    q = question.lower().strip().rstrip("?").strip()
    return any(q == p or q.startswith(p) for p in _IDENTITY_PATTERNS)


def _extract_sources(chunks: list[RetrievedChunk]) -> list[dict]:
    """Deduplicate and format source attributions from retrieved chunks."""
    seen: set[str] = set()
    sources: list[dict] = []
    for chunk in chunks:
        fp = chunk.file_path
        if not fp or fp in seen:
            continue
        seen.add(fp)
        abs_path = ""
        if chunk.repo.startswith("local:"):
            abs_path = str(Path(chunk.repo[6:]) / fp)
        sources.append({"file_name": Path(fp).name, "path": fp, "abs_path": abs_path})
    return sources


async def _get_or_create_conversation(
    db,
    conversation_id: int | None,
    question: str,
    model: str,
) -> tuple[int, bool]:
    """Return (conversation_id, is_new). Creates a new DB record if id is None."""
    from arcana.models import Conversation
    if conversation_id is not None:
        result = await db.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        conv = result.scalar_one_or_none()
        if conv is not None:
            return conv.id, False

    conv = Conversation(
        title=question[:200],
        model=model,
        out_of_scope=False,
        created_at=datetime.now(timezone.utc),
    )
    db.add(conv)
    await db.flush()
    return conv.id, True


async def _save_message(
    db,
    conversation_id: int,
    role: str,
    content: str,
    sources: list[dict] | None = None,
) -> None:
    from arcana.models import Message
    msg = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        sources_json=json.dumps(sources or []),
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg)
    await db.commit()


async def _mark_out_of_scope(db, conversation_id: int) -> None:
    from arcana.models import Conversation
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conv = result.scalar_one_or_none()
    if conv:
        conv.out_of_scope = True
        await db.commit()


async def run_query_stream(
    question: str,
    history: list[dict] | None = None,
    model: str = "Gemini 2.5 Flash-Lite",
    conversation_id: int | None = None,
) -> AsyncGenerator[dict, None]:
    """
    Run the full RAG pipeline and yield SSE event dicts.
    Always uses Gemini. Persists to DB.
    """
    from arcana.database import AsyncSessionLocal

    # Identity shortcut — no KB or LLM needed
    if _is_identity_question(question):
        log.info("query_service.identity_response")
        yield {"event": "chunk", "data": {"text": _IDENTITY_RESPONSE}}
        yield {"event": "done", "data": {"chunks_used": 0, "sources": [], "conversation_id": None}}
        return

    # Open DB session for this request
    async with AsyncSessionLocal() as db:
        conv_id, _ = await _get_or_create_conversation(db, conversation_id, question, model)
        await _save_message(db, conv_id, "user", question)

        # 1. Retrieve
        try:
            chunks = await vector_search(question)
        except Exception as exc:
            log.error("query_service.search_error", error=str(exc))
            yield {"event": "error", "data": {"message": "Search failed."}}
            return

        # 2a. No chunks at all → definitely out of scope
        if not chunks:
            log.info("query_service.out_of_scope_no_chunks", question=question)
            await _mark_out_of_scope(db, conv_id)
            yield {"event": "out_of_scope", "data": {"question": question, "conversation_id": conv_id}}
            yield {"event": "done", "data": {"chunks_used": 0, "sources": [], "conversation_id": conv_id}}
            return

        # 2b. Pass chunks to LLM — it signals OUTOFSCOPE if it can't answer
        context = assemble_context(chunks)
        prompt_pkg = build_prompt(question, context.chunks, history=history)
        sources = _extract_sources(chunks)

        _SIGNAL = "OUTOFSCOPE"
        buffer = ""
        signal_checked = False
        full_response: list[str] = []

        try:
            async for raw_chunk in stream_response(prompt_pkg):
                if raw_chunk.startswith("__ERROR__:"):
                    yield {"event": "error", "data": {"message": raw_chunk[len("__ERROR__:"):]}}
                    return

                if not signal_checked:
                    buffer += raw_chunk
                    if len(buffer) >= len(_SIGNAL):
                        signal_checked = True
                        if buffer.strip().upper().startswith(_SIGNAL):
                            # LLM signalled it cannot answer from the sources
                            log.info("query_service.out_of_scope_llm_signal", question=question)
                            await _mark_out_of_scope(db, conv_id)
                            yield {"event": "out_of_scope", "data": {"question": question, "conversation_id": conv_id}}
                            yield {"event": "done", "data": {"chunks_used": 0, "sources": [], "conversation_id": conv_id}}
                            return
                        else:
                            # Normal answer — flush buffered text
                            full_response.append(buffer)
                            yield {"event": "chunk", "data": {"text": buffer}}
                else:
                    full_response.append(raw_chunk)
                    yield {"event": "chunk", "data": {"text": raw_chunk}}

            # Handle very short responses that never filled the buffer
            if not signal_checked and buffer:
                if buffer.strip().upper().startswith(_SIGNAL):
                    await _mark_out_of_scope(db, conv_id)
                    yield {"event": "out_of_scope", "data": {"question": question, "conversation_id": conv_id}}
                    yield {"event": "done", "data": {"chunks_used": 0, "sources": [], "conversation_id": conv_id}}
                    return
                full_response.append(buffer)
                yield {"event": "chunk", "data": {"text": buffer}}

        except GeminiConfigError as exc:
            log.error("query_service.gemini_config_error", error=str(exc))
            yield {"event": "error", "data": {"message": "LLM configuration error."}}
            return
        except Exception as exc:
            log.error("query_service.gemini_error", error=str(exc))
            yield {"event": "error", "data": {"message": "Service temporarily unavailable."}}
            return

        await _save_message(db, conv_id, "assistant", "".join(full_response), sources)
        yield {"event": "done", "data": {
            "chunks_used": len(context.chunks),
            "sources": sources,
            "conversation_id": conv_id,
        }}
