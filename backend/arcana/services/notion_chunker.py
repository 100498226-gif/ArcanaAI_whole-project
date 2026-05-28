from __future__ import annotations
"""
Notion document chunker.

Splits Notion pages (already converted to markdown by notion_extractor) into
retrieval-ready chunks using heading boundaries.  Every chunk gets:
  - A workspace breadcrumb prepended as context
  - Rich metadata (page_path, section_heading, cross_references, etc.)
  - A deterministic chunk ID

Cross-reference detection scans each chunk for mentions of file paths,
repository names, and GitHub URLs that might link to code in the knowledge base.
"""

import hashlib
import json
import re
from typing import Any

from arcana.services.chunker import Chunk, count_tokens

# ── Constants ─────────────────────────────────────────────────────────────────

MIN_NOTION_TOKENS = 50
MAX_NOTION_TOKENS = 2000
TARGET_SECTION_TOKENS = 1500   # split at H3 if a section exceeds this

# ── Cross-reference patterns ──────────────────────────────────────────────────

# Matches paths like src/auth/middleware.py, /api/routes/users.ts
_FILE_PATH_RE = re.compile(
    r"(?<!\w)"                          # not preceded by word char
    r"(?:[\w./]*/)*"                    # optional directory segments
    r"[\w.-]+"                          # filename base
    r"\.(py|js|ts|tsx|jsx|go|rs|java|rb|php|c|cpp|h|md|yaml|yml|toml|json)"
    r"(?!\w)",
    re.IGNORECASE,
)

# Matches GitHub URLs like github.com/org/repo or full blob URLs
_GITHUB_URL_RE = re.compile(
    r"github\.com/([\w-]+/[\w.-]+)(?:/blob/[^\s)>\"']+)?",
    re.IGNORECASE,
)

# Matches org/repo style references (at least one slash, word chars and hyphens)
_REPO_REF_RE = re.compile(r"(?<!\w)([\w-]+/[\w.-]+)(?!\w)")


def detect_cross_references(text: str) -> list[dict[str, str]]:
    """
    Scan text for references to code files, repositories, and GitHub URLs.

    Returns a list of dicts like:
        {"type": "file_path", "value": "src/auth/middleware.py"}
        {"type": "repo",      "value": "org/backend-api"}
        {"type": "github_url","value": "org/repo"}
    """
    refs: list[dict[str, str]] = []
    seen: set[str] = set()

    for m in _FILE_PATH_RE.finditer(text):
        val = m.group(0)
        key = f"file_path:{val}"
        if key not in seen:
            refs.append({"type": "file_path", "value": val})
            seen.add(key)

    for m in _GITHUB_URL_RE.finditer(text):
        val = m.group(1).rstrip("/")
        key = f"github_url:{val}"
        if key not in seen:
            refs.append({"type": "github_url", "value": val})
            seen.add(key)
            # Also register as a repo reference
            repo_key = f"repo:{val}"
            if repo_key not in seen:
                refs.append({"type": "repo", "value": val})
                seen.add(repo_key)

    return refs


# ── Chunk ID ──────────────────────────────────────────────────────────────────

def _notion_chunk_id(
    workspace: str,
    page_id: str,
    section_heading: str,
    heading_level: int,
    chunk_index: int,
) -> str:
    """Deterministic 32-char hex chunk ID."""
    key = f"{workspace}:{page_id}:{section_heading}:{heading_level}:{chunk_index}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


# ── Breadcrumb header ─────────────────────────────────────────────────────────

def _breadcrumb(workspace_name: str, page_path: list[str], section_heading: str) -> str:
    path_str = " > ".join(page_path) if page_path else ""
    full = f"{workspace_name} > {path_str} > {section_heading}" if path_str else f"{workspace_name} > {section_heading}"
    return f"# Workspace: {full}\n"


# ── Section splitting ─────────────────────────────────────────────────────────

def _split_into_sections(markdown: str) -> list[tuple[str, int, str]]:
    """
    Split markdown into (heading_text, heading_level, body) tuples at H1/H2.

    H3 splits are deferred to oversized-section handling.
    """
    sections: list[tuple[str, int, str]] = []
    current_heading = "Introduction"
    current_level = 1
    current_lines: list[str] = []

    for line in markdown.splitlines(keepends=True):
        m = re.match(r"^(#{1,2})\s+(.+)", line)
        if m:
            if current_lines:
                sections.append((current_heading, current_level, "".join(current_lines)))
            current_heading = m.group(2).strip()
            current_level = len(m.group(1))
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_heading, current_level, "".join(current_lines)))

    return sections


def _split_at_h3(body: str) -> list[tuple[str, int, str]]:
    """Further split an oversized section at H3 headings."""
    sub_sections: list[tuple[str, int, str]] = []
    current_heading = ""
    current_lines: list[str] = []

    for line in body.splitlines(keepends=True):
        m = re.match(r"^###\s+(.+)", line)
        if m:
            if current_lines:
                sub_sections.append((current_heading, 3, "".join(current_lines)))
            current_heading = m.group(1).strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        sub_sections.append((current_heading, 3, "".join(current_lines)))

    return sub_sections


# ── Main chunker ──────────────────────────────────────────────────────────────

def chunk_notion_page(
    page_info: dict[str, Any],
    workspace_name: str,
    access_scope: str,
    ingested_at: str,
) -> list[Chunk]:
    """
    Chunk a single Notion page (already extracted to markdown).

    Args:
        page_info: dict from traverse_page — contains page_id, page_title,
                   page_path (list[str]), content_markdown, last_edited_time.
        workspace_name: displayed in breadcrumb and stored in metadata.
        access_scope: inherited from the DataSource.
        ingested_at: UTC ISO timestamp string.

    Returns:
        list[Chunk] ready for embedding.
    """
    content = page_info.get("content_markdown", "").strip()
    page_id: str = page_info["page_id"]
    page_title: str = page_info.get("page_title", "Untitled")
    page_path: list[str] = page_info.get("page_path", [page_title])
    last_edited_time: str = page_info.get("last_edited_time", "")

    if not content:
        return []

    sections = _split_into_sections(content)
    chunks: list[Chunk] = []
    chunk_index = 0

    base_meta: dict[str, Any] = {
        "source_type": "notion",
        "workspace": workspace_name,
        "page_id": page_id,
        "page_title": page_title,
        "page_path": " > ".join(page_path),
        "access_scope": access_scope,
        "last_edited_time": last_edited_time,
        "ingested_at": ingested_at,
    }

    for heading, level, body in sections:
        tokens = count_tokens(body)

        if tokens <= TARGET_SECTION_TOKENS:
            chunk = _make_chunk(
                body=body,
                heading=heading,
                level=level,
                parent_heading=None,
                chunk_index=chunk_index,
                workspace_name=workspace_name,
                page_path=page_path,
                page_id=page_id,
                base_meta=base_meta,
            )
            if chunk:
                chunks.append(chunk)
                chunk_index += 1
        else:
            # Split at H3 boundaries
            sub_sections = _split_at_h3(body)
            for sub_heading, sub_level, sub_body in sub_sections:
                effective_heading = sub_heading if sub_heading else heading
                effective_level = sub_level if sub_heading else level
                parent = heading if sub_heading else None

                chunk = _make_chunk(
                    body=sub_body,
                    heading=effective_heading,
                    level=effective_level,
                    parent_heading=parent,
                    chunk_index=chunk_index,
                    workspace_name=workspace_name,
                    page_path=page_path,
                    page_id=page_id,
                    base_meta=base_meta,
                )
                if chunk:
                    chunks.append(chunk)
                    chunk_index += 1

    return chunks


def _make_chunk(
    body: str,
    heading: str,
    level: int,
    parent_heading: str | None,
    chunk_index: int,
    workspace_name: str,
    page_path: list[str],
    page_id: str,
    base_meta: dict[str, Any],
) -> Chunk | None:
    """Build a single Chunk, or return None if below minimum token count."""
    body = body.strip()
    if count_tokens(body) < MIN_NOTION_TOKENS:
        return None

    cross_refs = detect_cross_references(body)
    breadcrumb = _breadcrumb(workspace_name, page_path, heading)
    text = breadcrumb + body

    chunk_id = _notion_chunk_id(workspace_name, page_id, heading, level, chunk_index)

    metadata: dict[str, Any] = {
        **base_meta,
        "chunk_type": "doc_section",
        "section_heading": heading,
        "heading_level": level,
        "parent_heading": parent_heading or "",
        "cross_references": json.dumps(cross_refs),
    }

    return Chunk(text=text, metadata=metadata, chunk_id=chunk_id)
