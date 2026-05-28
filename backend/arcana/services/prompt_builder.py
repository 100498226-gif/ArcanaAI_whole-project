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
2. Reference sources by their Source tags (e.g. [SOURCE 1], [SOURCE 3]).
3. Include file names when referencing specific documents.
4. Use code blocks with language annotations for code snippets.
5. When a diagram would significantly clarify the answer — such as for architecture,
   data flow, class relationships, call sequences, or state machines —, or when explicitly
   mentioned in the diagram any of these words: diagram, graph, view; generate a
   Mermaid diagram inside a ```mermaid code block. Choose the most appropriate type:
   flowchart, sequenceDiagram, classDiagram, erDiagram, stateDiagram-v2, etc.
   Keep diagrams focused; only include what is relevant to the question.

Output format:
- Answer directly and concisely.
- Cite sources inline as [SOURCE N] only for claims directly supported by a source you used.
- If you used any sources, end with a REFERENCES section listing only those sources.
- If none of the provided sources were relevant to the question, do NOT include a
  REFERENCES section at all — simply answer and note that the sources didn't cover it.
"""

# Simpler, step-by-step prompt for smaller local models (Qwen2.5:3b etc.).
# Small models follow explicit sequential instructions more reliably than
# abstract multi-rule prompts.
_OFFLINE_SYSTEM_PROMPT = """\
You are Arcana, a developer assistant. Answer using ONLY the numbered sources provided below.

Follow these steps:
1. Read all sources carefully.
2. Answer the question directly and concisely, using only what the sources say.
3. Cite each source you relied on inline as [SOURCE N] right after the relevant claim.
4. End your response with a REFERENCES section that lists only the sources you actually cited.

Additional rules:
- If no source contains relevant information, say so clearly — never invent facts.
- Use fenced code blocks with a language tag for any code (e.g. ```python).
- If a diagram would clarify the answer (architecture, data flow, class relationships,
  call sequences, or state machines), or the user asks for a diagram/graph/view,
  generate a Mermaid diagram inside a ```mermaid block. Choose the best type:
  flowchart, sequenceDiagram, classDiagram, erDiagram, or stateDiagram-v2.
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
    """Build the prompt package for the LLM.

    ``offline=True`` selects the simplified system prompt tuned for smaller
    local models (Qwen2.5:3b etc.).
    """
    system = _OFFLINE_SYSTEM_PROMPT if offline else _SYSTEM_PROMPT
    source_map: dict[int, RetrievedChunk] = {}
    blocks: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        blocks.append(_format_chunk(chunk, i))
        source_map[i] = chunk

    return PromptPackage(
        system_prompt=system,
        source_context="\n\n".join(blocks),
        question=question,
        history=history or [],
        source_map=source_map,
    )
