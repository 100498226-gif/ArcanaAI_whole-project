"""
Ollama local LLM client — mirrors the interface of gemini_client.py.

Uses Ollama's OpenAI-compatible /v1/chat/completions endpoint with streaming.
keep_alive=300 keeps the model resident in RAM for 5 minutes between queries,
eliminating cold-start latency on follow-up questions.
"""
from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

import httpx
import structlog

from arcana.config import settings

if TYPE_CHECKING:
    from arcana.services.prompt_builder import PromptPackage

log = structlog.get_logger()

_TIMEOUT = httpx.Timeout(connect=5.0, read=180.0, write=10.0, pool=5.0)

_FALLBACK_SYSTEM = """\
You are Arcana, a helpful AI assistant for developers. The user's knowledge base did
not contain relevant information for this question. Answer from your general knowledge
and clearly state at the start that this comes from general AI knowledge, not the
indexed codebase.
Given that you won't be using any sources, do not prompt any reference, but a text saying
"Knowledge coming from AI agent. There are no references to your question in the knowledge base."

When a diagram would significantly clarify the answer — such as for architecture,
data flow, class relationships, call sequences, or state machines —, or a user explicitly asks for:
diagram, graph, view; generate a Mermaid diagram inside a ```mermaid code block. Choose the most appropriate
type: flowchart, sequenceDiagram, classDiagram, erDiagram, stateDiagram-v2, etc.
"""


class OllamaError(Exception):
    """Raised when Ollama is unreachable or returns an unexpected error."""


def _format_history(history: list[dict]) -> str:
    if not history:
        return ""
    lines = ["<conversation_history>"]
    for msg in history:
        role = msg.get("role", "user").capitalize()
        lines.append(f"{role}: {msg.get('content', '')}")
    lines.append("</conversation_history>")
    return "\n".join(lines)


def _build_messages(system: str, user_content: str) -> list[dict]:
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]


def _pkg_to_user_content(pkg: "PromptPackage") -> str:
    parts = []
    if pkg.history:
        parts.append(_format_history(pkg.history))
    parts += [
        pkg.source_context,
        f"<user_question>{pkg.question}</user_question>",
        "Cite sources inline as [SOURCE N] only for claims directly supported by a source you used. "
        "Include a REFERENCES section only if you actually cited sources — omit it entirely if none were relevant.",
    ]
    return "\n\n".join(parts)


async def stream_response(
    pkg: "PromptPackage",
    model_name: str,
) -> AsyncGenerator[str, None]:
    """
    Stream a response from the local Ollama model.
    Yields text chunks; prefixes errors with '__ERROR__:'.
    """
    url = f"{settings.ollama_base_url}/v1/chat/completions"
    messages = _build_messages(pkg.system_prompt, _pkg_to_user_content(pkg))
    payload = {
        "model": model_name,
        "messages": messages,
        "stream": True,
        "keep_alive": 300,  # keep model loaded for 5 min between queries
        "options": {"num_ctx": 4096, "num_predict": 512},
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            async with client.stream("POST", url, json=payload) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    log.error("local_llm.bad_status", status=resp.status_code, body=body[:200])
                    yield f"__ERROR__:Ollama returned status {resp.status_code}."
                    return

                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    raw = line[6:]
                    if raw.strip() == "[DONE]":
                        break
                    try:
                        obj = json.loads(raw)
                        delta = obj.get("choices", [{}])[0].get("delta", {})
                        text = delta.get("content", "")
                        if text:
                            yield text
                    except (json.JSONDecodeError, IndexError, KeyError):
                        continue

    except httpx.ConnectError:
        raise OllamaError(
            "Cannot connect to Ollama. Make sure it is running: ollama serve"
        )
    except httpx.TimeoutException:
        yield "__ERROR__:Local model timed out. The model may be loading — try again in a moment."
    except OllamaError:
        raise
    except Exception as exc:
        log.error("local_llm.unexpected_error", error=str(exc))
        yield "__ERROR__:Local model error."


async def stream_fallback(
    question: str,
    history: list[dict] | None = None,
    model_name: str = "",
) -> AsyncGenerator[str, None]:
    """
    Stream a direct local LLM answer with no KB context.
    Used when vector search returns no results in offline mode.
    """
    history_text = _format_history(history or [])
    history_section = f"\n\n{history_text}" if history_text else ""
    user_content = f"{history_section}\n\n<user_question>{question}</user_question>".strip()

    url = f"{settings.ollama_base_url}/v1/chat/completions"
    messages = _build_messages(_FALLBACK_SYSTEM, user_content)
    payload = {
        "model": model_name,
        "messages": messages,
        "stream": True,
        "keep_alive": 300,
        "options": {"num_ctx": 4096, "num_predict": 512},
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            async with client.stream("POST", url, json=payload) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    log.error("local_llm.fallback_bad_status", status=resp.status_code)
                    yield f"__ERROR__:Ollama returned status {resp.status_code}."
                    return

                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    raw = line[6:]
                    if raw.strip() == "[DONE]":
                        break
                    try:
                        obj = json.loads(raw)
                        delta = obj.get("choices", [{}])[0].get("delta", {})
                        text = delta.get("content", "")
                        if text:
                            yield text
                    except (json.JSONDecodeError, IndexError, KeyError):
                        continue

    except httpx.ConnectError:
        raise OllamaError(
            "Cannot connect to Ollama. Make sure it is running: ollama serve"
        )
    except httpx.TimeoutException:
        yield "__ERROR__:Local model timed out."
    except OllamaError:
        raise
    except Exception as exc:
        log.error("local_llm.fallback_error", error=str(exc))
        yield "__ERROR__:Local model error."
