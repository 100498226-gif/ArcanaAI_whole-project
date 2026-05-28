from __future__ import annotations
"""
Notion content extraction — blocks-to-markdown, database rows, recursive traversal.

Converts Notion's block-based content model to clean markdown for downstream
chunking.  All 20+ supported block types are handled; unknown types are silently
skipped.

Rate limiting: every Notion API call is followed by a configurable sleep to
respect the 3 req/s limit (settings.notion_request_delay_ms).
"""

import time
from typing import Any

import structlog
from notion_client import Client  # type: ignore[import]
from notion_client.errors import APIResponseError  # type: ignore[import]

log = structlog.get_logger()

# Block types that carry no extractable text content
_SKIP_TYPES = frozenset({
    "embed", "video", "audio", "file", "pdf",
    "breadcrumb", "table_of_contents", "link_to_page",
})


# ── Rich text ─────────────────────────────────────────────────────────────────

def extract_rich_text(rich_text_list: list[dict]) -> str:
    """Convert a Notion rich_text array to a markdown-formatted string."""
    parts: list[str] = []
    for item in rich_text_list:
        text: str = item.get("plain_text", "")
        if not text:
            continue
        annotations: dict = item.get("annotations", {})
        href: str | None = item.get("href")

        # Apply formatting from inside out
        if annotations.get("code"):
            text = f"`{text}`"
        if annotations.get("bold"):
            text = f"**{text}**"
        if annotations.get("italic"):
            text = f"*{text}*"
        if annotations.get("strikethrough"):
            text = f"~~{text}~~"
        if href:
            text = f"[{text}]({href})"

        parts.append(text)
    return "".join(parts)


# ── Block fetching ────────────────────────────────────────────────────────────

def _fetch_all_blocks(nc: Client, block_id: str, delay: float) -> list[dict]:
    """Paginate through all children blocks for a given block ID."""
    results: list[dict] = []
    cursor: str | None = None

    while True:
        kwargs: dict[str, Any] = {"block_id": block_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        try:
            response = nc.blocks.children.list(**kwargs)
            time.sleep(delay)
        except APIResponseError as exc:
            log.warning("notion_extractor.blocks_fetch_error", block_id=block_id, error=str(exc))
            break

        results.extend(response.get("results", []))
        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")

    return results


# ── Database extraction ───────────────────────────────────────────────────────

def _extract_property_value(prop: dict) -> str:
    """Return a human-readable string for any Notion property value type."""
    prop_type = prop.get("type", "")

    if prop_type == "title":
        return extract_rich_text(prop.get("title", []))
    if prop_type == "rich_text":
        return extract_rich_text(prop.get("rich_text", []))
    if prop_type == "number":
        val = prop.get("number")
        return str(val) if val is not None else ""
    if prop_type == "select":
        sel = prop.get("select")
        return sel.get("name", "") if sel else ""
    if prop_type == "multi_select":
        return ", ".join(s.get("name", "") for s in prop.get("multi_select", []))
    if prop_type == "date":
        date = prop.get("date")
        if date:
            start = date.get("start", "")
            end = date.get("end", "")
            return f"{start} → {end}" if end else start
        return ""
    if prop_type == "url":
        return prop.get("url", "") or ""
    if prop_type == "email":
        return prop.get("email", "") or ""
    if prop_type == "phone_number":
        return prop.get("phone_number", "") or ""
    if prop_type == "checkbox":
        return "✓" if prop.get("checkbox") else "✗"
    if prop_type == "formula":
        formula = prop.get("formula", {})
        result_type = formula.get("type", "")
        return str(formula.get(result_type, "")) if result_type else ""
    if prop_type == "rollup":
        rollup = prop.get("rollup", {})
        result_type = rollup.get("type", "")
        if result_type == "number":
            return str(rollup.get("number", ""))
        if result_type == "array":
            return ", ".join(
                v for item in rollup.get("array", [])
                if (v := _extract_property_value(item))
            )
        return ""
    if prop_type == "relation":
        rels = prop.get("relation", [])
        return f"{len(rels)} relation(s)" if rels else ""
    if prop_type == "people":
        return ", ".join(p.get("name", "") for p in prop.get("people", []))
    return ""


def _extract_database_content(nc: Client, database_id: str, delay: float) -> str:
    """
    Extract a Notion database as structured markdown.

    Short rows (<50 tokens each) are grouped 10–20 per chunk at the caller level;
    here we just produce the full markdown representation.
    """
    try:
        db_meta = nc.databases.retrieve(database_id=database_id)
        time.sleep(delay)
    except APIResponseError as exc:
        log.warning("notion_extractor.db_retrieve_error", db_id=database_id, error=str(exc))
        return ""

    title_rich = db_meta.get("title", [])
    db_title = "".join(t.get("plain_text", "") for t in title_rich) or "Database"

    # Skip meta-only property types
    _meta_types = {"created_by", "last_edited_by", "created_time", "last_edited_time"}

    rows: list[dict] = []
    cursor: str | None = None
    while True:
        kwargs: dict[str, Any] = {"database_id": database_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        try:
            response = nc.databases.query(**kwargs)
            time.sleep(delay)
        except APIResponseError:
            break
        rows.extend(response.get("results", []))
        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")

    if not rows:
        return f"## {db_title}\n\n*Empty database.*\n"

    lines: list[str] = [f"## {db_title}\n"]
    for row in rows:
        parts: list[str] = []
        for prop_name, prop_value in row.get("properties", {}).items():
            if prop_value.get("type", "") in _meta_types:
                continue
            val = _extract_property_value(prop_value)
            if val:
                parts.append(f"{prop_name}: {val}")
        if parts:
            lines.append("- " + " | ".join(parts))

    return "\n".join(lines) + "\n"


# ── Blocks → markdown ─────────────────────────────────────────────────────────

def _blocks_to_markdown(
    blocks: list[dict],
    nc: Client,
    delay: float,
    indent: int = 0,
) -> str:
    """Recursively convert a list of Notion blocks to a markdown string."""
    output: list[str] = []
    prefix = "  " * indent

    for block in blocks:
        block_type: str = block.get("type", "")
        block_id: str = block.get("id", "")
        has_children: bool = block.get("has_children", False)

        if block_type in _SKIP_TYPES:
            continue

        data: dict = block.get(block_type, {})

        if block_type == "paragraph":
            text = extract_rich_text(data.get("rich_text", []))
            output.append(prefix + text if text else "")

        elif block_type in ("heading_1", "heading_2", "heading_3"):
            level = int(block_type[-1])
            text = extract_rich_text(data.get("rich_text", []))
            output.append(f"\n{'#' * level} {text}\n")

        elif block_type == "bulleted_list_item":
            text = extract_rich_text(data.get("rich_text", []))
            output.append(prefix + f"- {text}")
            if has_children:
                children = _fetch_all_blocks(nc, block_id, delay)
                output.append(_blocks_to_markdown(children, nc, delay, indent + 1))

        elif block_type == "numbered_list_item":
            text = extract_rich_text(data.get("rich_text", []))
            output.append(prefix + f"1. {text}")
            if has_children:
                children = _fetch_all_blocks(nc, block_id, delay)
                output.append(_blocks_to_markdown(children, nc, delay, indent + 1))

        elif block_type == "to_do":
            checked = data.get("checked", False)
            text = extract_rich_text(data.get("rich_text", []))
            box = "[x]" if checked else "[ ]"
            output.append(prefix + f"- {box} {text}")

        elif block_type == "toggle":
            text = extract_rich_text(data.get("rich_text", []))
            output.append(f"\n### {text}\n")
            if has_children:
                children = _fetch_all_blocks(nc, block_id, delay)
                output.append(_blocks_to_markdown(children, nc, delay, indent))

        elif block_type == "code":
            language = data.get("language", "")
            text = extract_rich_text(data.get("rich_text", []))
            output.append(f"\n```{language}\n{text}\n```\n")

        elif block_type == "quote":
            text = extract_rich_text(data.get("rich_text", []))
            quoted = "\n".join(f"> {line}" for line in text.splitlines())
            output.append(quoted)

        elif block_type == "callout":
            text = extract_rich_text(data.get("rich_text", []))
            icon_data = data.get("icon", {})
            icon = icon_data.get("emoji", "ℹ") if icon_data.get("type") == "emoji" else "ℹ"
            output.append(f"\n> {icon} {text}\n")

        elif block_type == "divider":
            output.append("\n---\n")

        elif block_type == "table":
            if has_children:
                rows = _fetch_all_blocks(nc, block_id, delay)
                table_lines: list[str] = []
                header_done = False
                for row_block in rows:
                    if row_block.get("type") != "table_row":
                        continue
                    cells = row_block.get("table_row", {}).get("cells", [])
                    row_md = " | ".join(extract_rich_text(cell) for cell in cells)
                    table_lines.append(f"| {row_md} |")
                    if not header_done:
                        sep = " | ".join("---" for _ in cells)
                        table_lines.append(f"| {sep} |")
                        header_done = True
                if table_lines:
                    output.append("\n" + "\n".join(table_lines) + "\n")

        elif block_type == "table_row":
            pass  # handled inside "table" above

        elif block_type == "bookmark":
            url = data.get("url", "")
            caption = extract_rich_text(data.get("caption", []))
            display = caption or url
            output.append(f"[{display}]({url})")

        elif block_type == "image":
            caption = extract_rich_text(data.get("caption", []))
            img_type = data.get("type", "")
            url = data.get(img_type, {}).get("url", "") if img_type else ""
            alt = caption or "image"
            output.append(f"![{alt}]({url})")

        elif block_type == "equation":
            output.append(f"$${data.get('expression', '')}$$")

        elif block_type in ("column_list", "column"):
            if has_children:
                children = _fetch_all_blocks(nc, block_id, delay)
                output.append(_blocks_to_markdown(children, nc, delay, indent))

        elif block_type == "synced_block":
            # Only render the original (synced_from is None); skip mirrors
            if data.get("synced_from") is None and has_children:
                children = _fetch_all_blocks(nc, block_id, delay)
                output.append(_blocks_to_markdown(children, nc, delay, indent))

        elif block_type == "child_page":
            pass  # handled at traversal level

        elif block_type == "child_database":
            try:
                db_md = _extract_database_content(nc, block_id, delay)
                output.append(db_md)
            except Exception as exc:
                log.warning("notion_extractor.inline_db_error", block_id=block_id, error=str(exc))

        # Unknown block types are silently skipped

    return "\n".join(output)


# ── Page traversal ────────────────────────────────────────────────────────────

def traverse_page(
    token: str,
    page_id: str,
    page_title: str,
    page_path: list[str],
    max_depth: int,
    current_depth: int,
    visited: set[str],
    delay: float,
) -> list[dict[str, Any]]:
    """
    Recursively traverse a Notion page and all its child pages/databases.

    Returns a list of dicts:
      {page_id, page_title, page_path, content_markdown, last_edited_time,
       skipped_reason}  ← skipped_reason is set only for skipped entries.
    """
    if page_id in visited:
        log.warning("notion_extractor.circular_ref", page_id=page_id)
        return [{"page_id": page_id, "skipped_reason": "circular_reference"}]

    if current_depth > max_depth:
        log.warning("notion_extractor.depth_exceeded", page_id=page_id, depth=current_depth)
        return [{"page_id": page_id, "page_title": page_title, "skipped_reason": "depth_exceeded"}]

    visited.add(page_id)
    nc = Client(auth=token)  # type: ignore[import]

    # Fetch page metadata
    try:
        page_meta = nc.pages.retrieve(page_id=page_id)
        time.sleep(delay)
        last_edited_time: str = page_meta.get("last_edited_time", "")
    except APIResponseError as exc:
        log.warning("notion_extractor.page_inaccessible", page_id=page_id, error=str(exc))
        return [{"page_id": page_id, "page_title": page_title, "skipped_reason": "not_accessible"}]

    # Fetch all blocks
    blocks = _fetch_all_blocks(nc, page_id, delay)

    # Separate child_page / child_database blocks from inline content blocks
    child_page_blocks: list[dict] = []
    content_blocks: list[dict] = []
    for block in blocks:
        btype = block.get("type", "")
        if btype == "child_page":
            child_page_blocks.append(block)
        elif btype == "child_database":
            child_page_blocks.append(block)
            content_blocks.append(block)   # also rendered inline
        else:
            content_blocks.append(block)

    content_markdown = _blocks_to_markdown(content_blocks, nc, delay)

    results: list[dict[str, Any]] = [{
        "page_id": page_id,
        "page_title": page_title,
        "page_path": list(page_path),
        "content_markdown": content_markdown,
        "last_edited_time": last_edited_time,
    }]

    # Recurse into children
    if current_depth < max_depth:
        for child_block in child_page_blocks:
            child_id = child_block.get("id", "")
            btype = child_block.get("type", "")
            child_title = child_block.get(btype, {}).get("title", "Untitled")
            child_path = page_path + [child_title]
            results.extend(
                traverse_page(
                    token=token,
                    page_id=child_id,
                    page_title=child_title,
                    page_path=child_path,
                    max_depth=max_depth,
                    current_depth=current_depth + 1,
                    visited=visited,
                    delay=delay,
                )
            )

    return results
