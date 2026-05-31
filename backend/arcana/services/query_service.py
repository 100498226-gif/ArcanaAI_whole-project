"""
Query pipeline: embed → retrieve → build prompt → stream response.

Always uses Gemini (online path). Persists conversations and messages to DB.

SSE event shapes:
  {"event": "chunk",       "data": {"text": "..."}}
  {"event": "done",        "data": {"chunks_used": N, "sources": [...], "conversation_id": N}}
  {"event": "out_of_scope","data": {"question": "...", "search_query": "...", "conversation_id": N}}
  {"event": "error",       "data": {"message": "..."}}
"""
from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path

import structlog
from sqlalchemy import select

from arcana.services.context_assembler import assemble_context
from arcana.services.gemini_client import (
    GeminiConfigError,
    stream_conversational,
    stream_fallback,
    stream_response,
)
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


def _make_search_query(question: str) -> str:
    """Strip personal language to produce a neutral, search-engine-friendly query."""
    q = question.strip().rstrip('?').strip()
    # Remove leading question phrases
    q = re.sub(
        r'^(what is|what are|what was|what were|how do i|how can i|how does|'
        r'who is|who are|where is|when is|why is|tell me about|explain|describe)\s+',
        '', q, flags=re.IGNORECASE,
    )
    # Remove possessives
    q = re.sub(r'\b(my|our|your|their|his|her|its)\b\s*', '', q, flags=re.IGNORECASE)
    # Remove personal pronouns
    q = re.sub(r'\b(i|we|me|us|you)\b\s*', '', q, flags=re.IGNORECASE)
    # Collapse extra whitespace
    q = re.sub(r'\s+', ' ', q).strip()
    return q if q else question.rstrip('?').strip()


def _is_identity_question(question: str) -> bool:
    q = question.lower().strip().rstrip("?").strip()
    return any(q == p or q.startswith(p) for p in _IDENTITY_PATTERNS)


# ── Creator / origin questions ─────────────────────────────────────────────────
_CREATOR_RESPONSE = (
    "I was created by Ignacio Chillón Domínguez as the subject of his Bachelor's "
    "Thesis, defended on May 31, 2026. Ignacio is a Product Manager at "
    "InfiniteWatch (an AI startup, infinitewatch.ai) and holds a Bachelor's "
    "Degree in Management and Technology, with a minor in Mathematics and "
    "Computer Science, from Universidad Carlos III de Madrid, where he "
    "graduated with a 3.9 / 4.0 GPA. He designed and built the entire Arcana "
    "system from scratch, including the frontend, the backend RAG engine, and "
    "the macOS desktop overlay."
)

_CREATOR_PATTERNS = (
    "who created you", "who made you", "who built you", "who developed you",
    "who designed you", "who programmed you", "who is your creator",
    "who is your author", "who is your developer", "who is your designer",
    "who is your maker", "who is behind you", "who is your founder",
    "who wrote you", "who coded you", "who is your dev",
    "where do you come from", "what is your origin", "what's your origin",
    "who owns you", "who built arcana", "who created arcana",
    "who made arcana", "who developed arcana", "who designed arcana",
    "who is arcana built by", "who is arcana made by",
)


def _is_creator_question(question: str) -> bool:
    q = question.lower().strip().rstrip("!.,?").strip()
    return any(q == p or q.startswith(p) for p in _CREATOR_PATTERNS)


# ── Casual / conversational message detection ──────────────────────────────────
_GREETING_PATTERNS = (
    "hey", "hi", "hello", "hola", "howdy", "greetings", "sup", "yo",
    "good morning", "good afternoon", "good evening", "good night",
)
_THANKS_PATTERNS = (
    "thanks", "thank you", "thank you so much", "thx", "ty", "cheers",
    "great", "perfect", "awesome", "nice", "cool", "excellent", "brilliant",
    "good", "ok", "okay", "got it", "understood", "sounds good", "alright",
)
_GOODBYE_PATTERNS = (
    "bye", "goodbye", "see you", "cya", "later", "farewell",
)

def _casual_response(question: str) -> str | None:
    """Return a short friendly reply for greetings, thanks, or farewells.
    Returns None if the message should go through the normal pipeline."""
    q = question.lower().strip().rstrip("!.,?").strip()
    if any(q == p or q.startswith(p + " ") for p in _GREETING_PATTERNS):
        return "Hi! Ready when you are. Ask me anything about your documents."
    if any(q == p or q.startswith(p) for p in _THANKS_PATTERNS):
        return "Happy to help! Let me know if you have any other questions about your documents."
    if any(q == p or q.startswith(p) for p in _GOODBYE_PATTERNS):
        return "Goodbye! Come back whenever you need to search your documents."
    return None


# ── Token-by-token streaming helper for canned responses ───────────────────────
async def _stream_canned(text: str) -> AsyncGenerator[dict, None]:
    """Yield a canned response broken into small word-sized chunks with a
    small delay between each, so the UI sees the same visual effect as a
    real LLM streaming token by token."""
    words = text.split(" ")
    for i, word in enumerate(words):
        piece = word if i == 0 else " " + word
        yield {"event": "chunk", "data": {"text": piece}}
        await asyncio.sleep(0.025)


# ── Group A — questions to redirect to the internet ────────────────────────────
_INTERNET_REDIRECT_MSG = (
    "That's a great question, but it's not something I can answer from your "
    "personal documents. Let me redirect you to the internet, where you'll find "
    "better and more current information on this."
)

_INTERNET_REDIRECT_PATTERNS = (
    # Information & Explanations
    "what is quantum", "how does inflation", "explain black holes", "explain ",
    "what's the difference between machine learning", "what is machine learning",
    "what is ai", "what is artificial intelligence",
    # Writing & Communication
    "write a professional email", "write a cover letter", "draft a cover letter",
    "draft an email", "draft a ", "write an email", "improve this paragraph",
    "make this text", "rewrite this", "proofread",
    # Learning & Education
    "help me solve", "quiz me", "summarize this chapter", "summarize this article",
    "explain photosynthesis", "translate this", "what is the capital of",
    # Coding & Technology
    "write a python", "write a function", "write code", "why is my javascript",
    "why is my code", "debug this", "explain apis", "how do i build a website",
    "how do i build an app", "what is rest", "what is http",
    # Personal Productivity
    "create a study plan", "make a study plan", "help me organize my week",
    "what should i prioritize today", "make a workout schedule",
    # Creative Content
    "write a short story", "write a poem", "give me youtube video ideas",
    "create a d&d", "brainstorm startup ideas", "give me ideas for",
    # Career & Jobs
    "how do i prepare for an interview", "review my resume", "review my résumé",
    "what skills should i learn", "what careers fit",
    # Everyday Decisions
    "what should i cook", "recommend a laptop", "recommend a ",
    "plan a 3-day trip", "plan a trip", "how do i remove a wine stain",
    "how do i remove ",
    # Health & Fitness
    "what's a good beginner workout", "what are the symptoms of",
    "symptoms of ", "is it safe to ",
    # Relationships & Social Situations
    "how do i start a difficult conversation", "what should i text after a first date",
    "how can i resolve a conflict", "give me gift ideas",
)


def _matches_internet_redirect(question: str) -> bool:
    q = question.lower().strip().rstrip("!.,?").strip()
    return any(q == p or q.startswith(p) for p in _INTERNET_REDIRECT_PATTERNS)


# ── Group B1 — tailored STATIC responses (same answer every time) ─────────────
_TAILORED_STATIC = {
    "tell me a joke": (
        "Why did the document cross the road? To get to the other side of the index. "
        "I'll see myself out."
    ),
    "what's the meaning of life": (
        "A bigger question than my scope! But if life's meaning happens to be in your "
        "notes somewhere, I can help you find it."
    ),
    "what is the meaning of life": (
        "A bigger question than my scope! But if life's meaning happens to be in your "
        "notes somewhere, I can help you find it."
    ),
    "tell me something interesting": (
        "Here's something: humans typically lose 9.3 hours a week searching for "
        "information. I'm here to help you get that time back."
    ),
    "i'm bored": (
        "I hear you. Why not try asking me something about your uploaded documents? "
        "You might find something you'd forgotten about."
    ),
    "help.": "Just type a question about your uploaded documents. I'll find the answer and show you the source file.",
    "help": "Just type a question about your uploaded documents. I'll find the answer and show you the source file.",
}


def _match_tailored_static(question: str) -> str | None:
    q = question.lower().strip().rstrip("!.,?").strip()
    return _TAILORED_STATIC.get(q)


# ── Group B2 — contextual responses (Gemini, conversational, history-aware) ───
_TAILORED_CONTEXTUAL_PATTERNS = (
    # Casual starters that benefit from history
    "how are you", "what's up", "whats up", "can we chat", "what are you thinking",
    "surprise me",
    # Opinions
    "what do you think", "is this a good idea", "would you do it differently",
    "what's your take", "whats your take", "pros and cons", "am i missing something",
    # Self-reflection
    "why do i", "how can i be more", "what should i do with my life",
    "how do i find purpose", "what are my strengths", "help me think through",
    # Emotional support
    "i'm stressed", "im stressed", "i'm feeling lonely", "im feeling lonely",
    "i had a bad day", "i'm nervous", "im nervous", "can i vent", "i need advice",
    # Curiosity / philosophical
    "would you rather", "what is consciousness", "do humans have free will",
    "what makes someone happy", "what is reality", "can ai be creative",
    # Relationship
    "how do i know if someone likes me", "should i send this text",
    "was i wrong", "how do i apologize", "what would you say",
    # Common short phrases / follow-ups
    "thoughts", "thoughts?", "why?", "how?", "tell me more", "continue", "continue?",
    "examples", "examples?", "eli5", "explain like i'm 5", "be honest",
    "what would you do", "can you elaborate", "elaborate", "i'm confused",
    "im confused", "am i overthinking", "does this make sense",
    "can you help me figure this out", "can i tell you something",
    "do you have a minute", "what should i do",
)


def _matches_tailored_contextual(question: str) -> bool:
    q = question.lower().strip().rstrip("!.,").strip()
    # Allow exact match or starts-with match
    return any(q == p or q == p.rstrip("?") or q.startswith(p + " ") for p in _TAILORED_CONTEXTUAL_PATTERNS)


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

    # ── Identity shortcut (streamed + persisted) ──────────────────────────────
    if _is_identity_question(question):
        log.info("query_service.identity_response")
        async with AsyncSessionLocal() as db:
            conv_id, _ = await _get_or_create_conversation(db, conversation_id, question, model)
            await _save_message(db, conv_id, "user", question)
            async for ev in _stream_canned(_IDENTITY_RESPONSE):
                yield ev
            await _save_message(db, conv_id, "assistant", _IDENTITY_RESPONSE)
        yield {"event": "done", "data": {"chunks_used": 0, "sources": [], "conversation_id": conv_id}}
        return

    # ── Creator / origin shortcut (streamed + persisted) ──────────────────────
    if _is_creator_question(question):
        log.info("query_service.creator_response")
        async with AsyncSessionLocal() as db:
            conv_id, _ = await _get_or_create_conversation(db, conversation_id, question, model)
            await _save_message(db, conv_id, "user", question)
            async for ev in _stream_canned(_CREATOR_RESPONSE):
                yield ev
            await _save_message(db, conv_id, "assistant", _CREATOR_RESPONSE)
        yield {"event": "done", "data": {"chunks_used": 0, "sources": [], "conversation_id": conv_id}}
        return

    # ── Casual greetings / thanks / farewells (streamed + persisted) ──────────
    casual = _casual_response(question)
    if casual is not None:
        log.info("query_service.casual_response")
        async with AsyncSessionLocal() as db:
            conv_id, _ = await _get_or_create_conversation(db, conversation_id, question, model)
            await _save_message(db, conv_id, "user", question)
            async for ev in _stream_canned(casual):
                yield ev
            await _save_message(db, conv_id, "assistant", casual)
        yield {"event": "done", "data": {"chunks_used": 0, "sources": [], "conversation_id": conv_id}}
        return

    # ── Group A: questions to redirect to the internet ────────────────────────
    if _matches_internet_redirect(question):
        log.info("query_service.internet_redirect_hardcoded")
        async with AsyncSessionLocal() as db:
            conv_id, _ = await _get_or_create_conversation(db, conversation_id, question, model)
            await _save_message(db, conv_id, "user", question)
            async for ev in _stream_canned(_INTERNET_REDIRECT_MSG):
                yield ev
            await _save_message(db, conv_id, "assistant", _INTERNET_REDIRECT_MSG)
            await _mark_out_of_scope(db, conv_id)
        yield {"event": "out_of_scope", "data": {
            "question": question,
            "search_query": _make_search_query(question),
            "conversation_id": conv_id,
        }}
        yield {"event": "done", "data": {"chunks_used": 0, "sources": [], "conversation_id": conv_id}}
        return

    # ── Group B1: tailored STATIC responses ───────────────────────────────────
    static_reply = _match_tailored_static(question)
    if static_reply is not None:
        log.info("query_service.tailored_static_response")
        async with AsyncSessionLocal() as db:
            conv_id, _ = await _get_or_create_conversation(db, conversation_id, question, model)
            await _save_message(db, conv_id, "user", question)
            async for ev in _stream_canned(static_reply):
                yield ev
            await _save_message(db, conv_id, "assistant", static_reply)
        yield {"event": "done", "data": {"chunks_used": 0, "sources": [], "conversation_id": conv_id}}
        return

    # ── Group B2: tailored CONTEXTUAL responses via Gemini (history-aware) ────
    if _matches_tailored_contextual(question):
        log.info("query_service.tailored_contextual_response")
        async with AsyncSessionLocal() as db:
            conv_id, _ = await _get_or_create_conversation(db, conversation_id, question, model)
            await _save_message(db, conv_id, "user", question)
            full_response: list[str] = []
            try:
                async for piece in stream_conversational(question, history):
                    if piece.startswith("__ERROR__:"):
                        yield {"event": "error", "data": {"message": piece[len("__ERROR__:"):]}}
                        return
                    full_response.append(piece)
                    yield {"event": "chunk", "data": {"text": piece}}
            except GeminiConfigError as exc:
                log.error("query_service.conversational_config_error", error=str(exc))
                yield {"event": "error", "data": {"message": "LLM configuration error."}}
                return
            except Exception as exc:
                log.error("query_service.conversational_error", error=str(exc))
                yield {"event": "error", "data": {"message": "Service temporarily unavailable."}}
                return
            await _save_message(db, conv_id, "assistant", "".join(full_response))
        yield {"event": "done", "data": {"chunks_used": 0, "sources": [], "conversation_id": conv_id}}
        return

    # ── Default: full RAG pipeline ────────────────────────────────────────────
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
            yield {"event": "out_of_scope", "data": {"question": question, "search_query": _make_search_query(question), "conversation_id": conv_id}}
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
                            yield {"event": "out_of_scope", "data": {"question": question, "search_query": _make_search_query(question), "conversation_id": conv_id}}
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
                    yield {"event": "out_of_scope", "data": {"question": question, "search_query": _make_search_query(question), "conversation_id": conv_id}}
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
