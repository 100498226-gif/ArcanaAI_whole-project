"""
Gemini API: streaming and non-streaming responses.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

import structlog

from arcana.config import settings

if TYPE_CHECKING:
    from arcana.services.prompt_builder import PromptPackage

log = structlog.get_logger()


class GeminiConfigError(Exception):
    pass


_FALLBACK_SYSTEM = """\
You are Arcana, a helpful AI assistant for developers. The user's knowledge base did
not contain relevant information for this question. Answer from your general knowledge
and clearly state at the start that this comes from general AI knowledge, not the
indexed codebase.
Given that you won't be using any sources, do not prompt any reference, but a text saying
"Knowledge coming from AI agent. There are no references to your question in the knowledge base."

When a diagram would significantly clarify the answer (such as for architecture,
data flow, class relationships, call sequences, or state machines), or a user explicitly asks for:
diagram, graph, view; generate a Mermaid diagram inside a ```mermaid code block. Choose the most appropriate
type: flowchart, sequenceDiagram, classDiagram, erDiagram, stateDiagram-v2, etc.

Never use em-dashes in your answers. Use commas, periods, parentheses, or colons instead.
"""


_CONVERSATIONAL_SYSTEM = """\
You are Arcana, a personal document assistant. The user is making a conversational
remark, asking for your opinion, requesting a follow-up, or seeking brief support.

Rules for this kind of message:
1. Respond warmly and naturally in 1 to 3 sentences. Be brief.
2. Do NOT invent facts about the user's personal documents. You have no access to them in this mode.
3. If the user's message references prior conversation (for example "thoughts?", "elaborate",
   "be honest", "am I overthinking?"), use the conversation history to inform your response.
4. If the user is venting or asks for emotional support, acknowledge their feeling first,
   then gently remind them you are an assistant tool, not a therapist or friend, and that
   you can help them search their documents whenever they want.
5. Never use em-dashes in your answers. Use commas, periods, parentheses, or colons instead.
6. Never include citations or [SOURCE N] tags. This is a conversational response, not a RAG answer.
"""


def _format_history(history: list[dict]) -> str:
    if not history:
        return ""
    lines = ["<conversation_history>"]
    for msg in history:
        role = msg.get("role", "user").capitalize()
        lines.append(f"{role}: {msg.get('content', '')}")
    lines.append("</conversation_history>")
    return "\n".join(lines)


def _build_prompt_text(pkg: "PromptPackage") -> str:
    parts = [pkg.system_prompt]
    if pkg.history:
        parts.append(_format_history(pkg.history))
    parts += [
        pkg.source_context,
        f"<user_question>{pkg.question}</user_question>",
        "If the sources above contain enough information to answer the question, answer directly and concisely. "
        "Do NOT include any [SOURCE N] citations, reference numbers, or a REFERENCES section.\n"
        "If the sources do NOT contain relevant information to answer the question, respond with exactly one word: OUTOFSCOPE",
    ]
    return "\n\n".join(parts)


async def stream_fallback(
    question: str,
    history: list[dict] | None = None,
) -> AsyncGenerator[str, None]:
    """
    Stream a direct Gemini answer with no KB context.
    Used when vector search returns no results.
    """
    from google.genai import types  # type: ignore[import]

    try:
        client = settings.build_google_client()
    except ValueError as exc:
        raise GeminiConfigError(str(exc)) from exc

    history_text = _format_history(history or [])
    history_section = f"\n\n{history_text}" if history_text else ""
    prompt = f"{_FALLBACK_SYSTEM}{history_section}\n\n<user_question>{question}</user_question>"
    config = types.GenerateContentConfig(
        temperature=settings.gemini_temperature,
        max_output_tokens=settings.gemini_max_output_tokens,
    )

    for attempt in range(2):
        try:
            response = await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: list(client.models.generate_content_stream(
                        model=settings.gemini_model,
                        contents=prompt,
                        config=config,
                    )),
                ),
                timeout=30.0,
            )
            for chunk in response:
                try:
                    if chunk.text:
                        yield chunk.text
                except Exception:
                    return
            return
        except TimeoutError:
            if attempt == 0:
                await asyncio.sleep(2)
                continue
            yield "__ERROR__:Request timed out."
            return
        except Exception as exc:
            err = str(exc)
            if "api_key" in err.lower() or "credentials" in err.lower():
                raise GeminiConfigError("Invalid Gemini API key.") from exc
            if attempt == 0:
                await asyncio.sleep(2)
                continue
            yield "__ERROR__:Service error."
            return


async def stream_response(pkg: "PromptPackage") -> AsyncGenerator[str, None]:
    """Stream Gemini response chunk by chunk. Yields '__ERROR__:msg' on failure."""
    from google.genai import types  # type: ignore[import]

    try:
        client = settings.build_google_client()
    except ValueError as exc:
        raise GeminiConfigError(str(exc)) from exc

    prompt = _build_prompt_text(pkg)
    config = types.GenerateContentConfig(
        temperature=settings.gemini_temperature,
        max_output_tokens=settings.gemini_max_output_tokens,
    )

    for attempt in range(2):
        try:
            response = await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: list(client.models.generate_content_stream(
                        model=settings.gemini_model,
                        contents=prompt,
                        config=config,
                    )),
                ),
                timeout=30.0,
            )
            for chunk in response:
                try:
                    if chunk.text:
                        yield chunk.text
                except Exception:
                    yield "\n[Content filtered by safety system.]"
                    return
            return
        except TimeoutError:
            if attempt == 0:
                await asyncio.sleep(2)
                continue
            yield "__ERROR__:Request timed out."
            return
        except Exception as exc:
            err = str(exc)
            if "api_key" in err.lower() or "credentials" in err.lower():
                raise GeminiConfigError("Invalid Gemini API key.") from exc
            if "429" in err or "quota" in err.lower():
                if attempt == 0:
                    await asyncio.sleep(5)
                    continue
                yield "__ERROR__:Rate limit hit. Please retry shortly."
                return
            if attempt == 0:
                await asyncio.sleep(2)
                continue
            yield f"__ERROR__:Service error."
            return


async def stream_conversational(
    question: str,
    history: list[dict] | None = None,
) -> AsyncGenerator[str, None]:
    """
    Stream a brief, warm Gemini reply for conversational follow-ups and
    context-dependent short prompts (Group B2 in query_service). Does NOT use
    document context. Uses conversation history when present so questions like
    "thoughts?" or "elaborate" refer to the immediately preceding exchange.
    """
    from google.genai import types  # type: ignore[import]

    try:
        client = settings.build_google_client()
    except ValueError as exc:
        raise GeminiConfigError(str(exc)) from exc

    history_text = _format_history(history or [])
    history_section = f"\n\n{history_text}" if history_text else ""
    prompt = f"{_CONVERSATIONAL_SYSTEM}{history_section}\n\n<user_message>{question}</user_message>"
    config = types.GenerateContentConfig(
        temperature=settings.gemini_temperature,
        max_output_tokens=settings.gemini_max_output_tokens,
    )

    for attempt in range(2):
        try:
            response = await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: list(client.models.generate_content_stream(
                        model=settings.gemini_model,
                        contents=prompt,
                        config=config,
                    )),
                ),
                timeout=30.0,
            )
            for chunk in response:
                try:
                    if chunk.text:
                        yield chunk.text
                except Exception:
                    return
            return
        except TimeoutError:
            if attempt == 0:
                await asyncio.sleep(2)
                continue
            yield "__ERROR__:Request timed out."
            return
        except Exception as exc:
            err = str(exc)
            if "api_key" in err.lower() or "credentials" in err.lower():
                raise GeminiConfigError("Invalid Gemini API key.") from exc
            if "429" in err or "quota" in err.lower():
                if attempt == 0:
                    await asyncio.sleep(5)
                    continue
                yield "__ERROR__:Rate limit hit. Please retry shortly."
                return
            if attempt == 0:
                await asyncio.sleep(2)
                continue
            yield "__ERROR__:Service error."
            return
