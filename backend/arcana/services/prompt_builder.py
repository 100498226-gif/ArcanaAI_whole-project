"""
Builds the prompt sent to Gemini from the user question and retrieved chunks.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from arcana.services.retrieval import RetrievedChunk


_SYSTEM_PROMPT = """\
You are Arcana, a personal AI assistant. Answer questions accurately using ONLY the provided
source materials from the user's knowledge base.

Rules:
1. Base your answer exclusively on the provided sources. If they don't contain
   enough information, say so — never fabricate.
2. Include file names when referencing specific documents.
3. Use code blocks with language annotations for code snippets.

Output format:
- Answer directly and concisely.
"""


@dataclass
class PromptPackage:
    system_prompt: str
    source_context: str
    question: str
    history: list[dict] = field(default_factory=list)
    source_map: dict[int, RetrievedChunk] = field(default_factory=dict)


def _format_chunk(chunk: RetrievedChunk, index: int) -> str:
    file_name = chunk.file_path or chunk.page_title or "unknown"
    meta = f"file: {file_name}"
    if chunk.symbol_name:
        meta += f" | section: {chunk.symbol_name}"
    return f"[SOURCE {index} | {meta}]\n{chunk.content}\n[END SOURCE {index}]"


def build_prompt(
    question: str,
    chunks: list[RetrievedChunk],
    history: list[dict] | None = None,
    offline: bool = False,
) -> PromptPackage:
    source_map: dict[int, RetrievedChunk] = {}
    blocks: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        blocks.append(_format_chunk(chunk, i))
        source_map[i] = chunk

    return PromptPackage(
        system_prompt=_SYSTEM_PROMPT,
        source_context="\n\n".join(blocks),
        question=question,
        history=history or [],
        source_map=source_map,
    )
