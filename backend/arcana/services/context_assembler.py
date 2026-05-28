"""
Context assembly: takes re-ranked chunks and builds the final LLM context window.

Steps:
  1. Deduplicate (same content from GitHub README + Notion → keep richer version)
  2. Order by source type: architectural_overview → documentation → code
  3. Apply role-aware team bias (soft tiebreaker within each group)
  4. Fill token budget greedily; truncate at paragraph/code-block boundary
  5. Format each chunk as a numbered [SOURCE N] block for the LLM
"""

from __future__ import annotations

import tiktoken

from arcana.config import settings
from arcana.services.retrieval import RetrievedChunk

# Source type priority (lower = higher priority in assembled context)
_SOURCE_ORDER = {
    "architectural_overview": 0,
    "documentation": 1,
    "notion": 1,
    "code": 2,
}

_ARCH_TOKEN_RESERVE = 500  # tokens reserved for architectural overview chunks

_enc = tiktoken.get_encoding("cl100k_base")


def _count_tokens(text: str) -> int:
    return len(_enc.encode(text))


def _source_priority(chunk: RetrievedChunk) -> int:
    st = chunk.source_type.lower()
    for key, priority in _SOURCE_ORDER.items():
        if key in st:
            return priority
    return 2


def _deduplicate(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """
    Remove duplicate content. When two chunks share the same (file_path, page_title)
    key, keep the one with the higher rrf_score.
    """
    seen_ids: set[str] = set()
    content_key_map: dict[tuple[str, str], RetrievedChunk] = {}
    result: list[RetrievedChunk] = []

    for chunk in chunks:
        if chunk.chunk_id in seen_ids:
            continue
        seen_ids.add(chunk.chunk_id)

        key = (chunk.file_path, chunk.page_title)
        if key != ("", "") and key in content_key_map:
            existing = content_key_map[key]
            if chunk.score > existing.score:
                content_key_map[key] = chunk
                result = [c for c in result if (c.file_path, c.page_title) != key]
                result.append(chunk)
        else:
            content_key_map[key] = chunk
            result.append(chunk)

    return result


def _apply_team_bias(
    chunks: list[RetrievedChunk],
    user_team: str | None,
) -> list[RetrievedChunk]:
    """
    Soft tiebreaker: if user's team matches a repo name or page_title keyword,
    apply a tiny score bump to break ties within the same source group.
    """
    if not user_team:
        return chunks
    team = user_team.lower()
    for chunk in chunks:
        if team in chunk.repo.lower() or team in chunk.page_title.lower():
            chunk.score += 0.005
    return chunks


def _truncate_at_boundary(text: str, max_tokens: int) -> str:
    """
    Truncate text to at most `max_tokens`, ending at a paragraph or code-block boundary.
    """
    if _count_tokens(text) <= max_tokens:
        return text

    lines = text.split("\n")
    truncated_lines: list[str] = []
    tokens_used = 0
    in_code_block = False

    for line in lines:
        line_tokens = _count_tokens(line + "\n")
        if tokens_used + line_tokens > max_tokens:
            if in_code_block:
                truncated_lines.append("```")
            break
        truncated_lines.append(line)
        tokens_used += line_tokens
        if line.strip().startswith("```"):
            in_code_block = not in_code_block

    result = "\n".join(truncated_lines)
    if result != text:
        result += "\n... [truncated]"
    return result


def _format_source_block(chunk: RetrievedChunk, index: int) -> str:
    """Format a chunk as a numbered [SOURCE N] block for the LLM prompt."""
    st = chunk.source_type.lower()

    if "architectural" in st:
        meta_parts = ["type: architectural_overview"]
        if chunk.page_title:
            meta_parts.append(f"section: {chunk.page_title}")
    elif "code" in st or (chunk.file_path and not chunk.page_title):
        meta_parts = ["type: code"]
        if chunk.repo:
            meta_parts.append(f"repo: {chunk.repo}")
        if chunk.file_path:
            meta_parts.append(f"file: {chunk.file_path}")
        if chunk.symbol_name:
            meta_parts.append(f"symbol: {chunk.symbol_name}")
    else:
        meta_parts = ["type: documentation"]
        if chunk.page_title:
            meta_parts.append(f"page: {chunk.page_title}")
        if chunk.repo:
            meta_parts.append(f"source: {chunk.repo or 'Notion'}")

    meta = " | ".join(meta_parts)
    return f"[SOURCE {index} | {meta}]\n{chunk.content}\n[END SOURCE {index}]"


class AssembledContext:
    def __init__(
        self,
        chunks: list[RetrievedChunk],
        source_blocks: list[str],
        total_tokens: int,
        source_map: dict[int, RetrievedChunk],
    ) -> None:
        self.chunks = chunks
        self.source_blocks = source_blocks
        self.total_tokens = total_tokens
        self.source_map = source_map  # 1-indexed: source_number → chunk

    @property
    def formatted_context(self) -> str:
        return "\n\n".join(self.source_blocks)


def assemble_context(
    chunks: list[RetrievedChunk],
    *,
    token_budget: int | None = None,
    user_team: str | None = None,
) -> AssembledContext:
    """
    Build the final LLM context from re-ranked chunks.

    Returns an AssembledContext with formatted [SOURCE N] blocks and
    a source_map for citation resolution.
    """
    budget = token_budget if token_budget is not None else settings.context_token_budget

    # 1. Deduplicate
    deduped = _deduplicate(chunks)

    # 2. Apply team bias
    deduped = _apply_team_bias(deduped, user_team)

    # 3. Sort by source type priority, then by score (desc) within each group
    deduped.sort(key=lambda c: (_source_priority(c), -c.score))

    # 4. Separate arch overview chunks (reserved budget slice)
    arch_chunks = [c for c in deduped if _source_priority(c) == 0]
    other_chunks = [c for c in deduped if _source_priority(c) != 0]

    selected: list[RetrievedChunk] = []
    tokens_used = 0
    arch_budget = min(_ARCH_TOKEN_RESERVE, budget // 5)

    for chunk in arch_chunks:
        chunk_tokens = _count_tokens(chunk.content)
        if tokens_used + chunk_tokens <= arch_budget:
            selected.append(chunk)
            tokens_used += chunk_tokens
        else:
            remaining = arch_budget - tokens_used
            if remaining > 50:
                truncated = _truncate_at_boundary(chunk.content, remaining)
                if truncated:
                    chunk.content = truncated
                    selected.append(chunk)
                    tokens_used += _count_tokens(truncated)
            break

    for chunk in other_chunks:
        remaining_budget = budget - tokens_used
        chunk_tokens = _count_tokens(chunk.content)
        if tokens_used + chunk_tokens <= budget:
            selected.append(chunk)
            tokens_used += chunk_tokens
        elif remaining_budget > 100:
            truncated = _truncate_at_boundary(chunk.content, remaining_budget)
            if truncated:
                chunk.content = truncated
                selected.append(chunk)
                tokens_used += _count_tokens(truncated)
            break
        else:
            break

    # 5. Format as [SOURCE N] blocks (1-indexed)
    source_blocks: list[str] = []
    source_map: dict[int, RetrievedChunk] = {}
    for i, chunk in enumerate(selected, start=1):
        block = _format_source_block(chunk, i)
        source_blocks.append(block)
        source_map[i] = chunk

    return AssembledContext(
        chunks=selected,
        source_blocks=source_blocks,
        total_tokens=tokens_used,
        source_map=source_map,
    )
