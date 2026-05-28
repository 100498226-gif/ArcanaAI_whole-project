"""
Notion authentication and workspace exploration.

Uses the official notion-client library (sync Client).
All API calls respect the 3 req/s rate limit via notion_request_delay_ms.
"""

import time
from typing import Any

import structlog
from notion_client import Client  # type: ignore[import]
from notion_client.errors import APIResponseError  # type: ignore[import]

from arcana.config import settings

log = structlog.get_logger()


class NotionAuthError(Exception):
    pass


def _client(token: str) -> Client:
    return Client(auth=token)


def _delay() -> float:
    return settings.notion_request_delay_ms / 1000.0


# ── Token validation ──────────────────────────────────────────────────────────

def validate_token(token: str) -> dict[str, Any]:
    """
    Validate a Notion integration token by calling /v1/users/me.

    Returns:
        {"bot_id": str, "workspace_name": str}

    Raises:
        NotionAuthError on invalid token or network failure.
    """
    try:
        nc = _client(token)
        me = nc.users.me()
        bot_info = me.get("bot", {})
        return {
            "bot_id": me.get("id", ""),
            "workspace_name": bot_info.get("workspace_name", "Unknown Workspace"),
        }
    except APIResponseError as exc:
        raise NotionAuthError(f"Invalid Notion token: {exc.code}") from exc
    except Exception as exc:
        raise NotionAuthError(f"Failed to validate Notion token: {exc}") from exc


# ── Page listing ──────────────────────────────────────────────────────────────

def list_top_level_pages(token: str) -> list[dict[str, Any]]:
    """
    Return all pages and databases accessible to the integration.
    Includes 2-level preview (immediate children listed by title).
    """
    nc = _client(token)
    delay = _delay()
    items: list[dict[str, Any]] = []

    for obj_type in ("page", "database"):
        cursor = None
        while True:
            kwargs: dict[str, Any] = {
                "filter": {"value": obj_type, "property": "object"},
                "page_size": 100,
            }
            if cursor:
                kwargs["start_cursor"] = cursor

            response = nc.search(**kwargs)
            time.sleep(delay)

            for result in response.get("results", []):
                items.append(_extract_page_info(result))

            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")

    # Enrich each page with 1-level children preview
    for item in items:
        if item["type"] == "page":
            try:
                children_resp = nc.blocks.children.list(
                    block_id=item["page_id"], page_size=100
                )
                time.sleep(delay)
                child_blocks = [
                    b for b in children_resp.get("results", [])
                    if b.get("type") in ("child_page", "child_database")
                ]
                item["children_count"] = len(child_blocks)
                item["children"] = [
                    {
                        "page_id": b["id"],
                        "title": b.get(b["type"], {}).get("title", "Untitled"),
                        "type": "page" if b["type"] == "child_page" else "database",
                    }
                    for b in child_blocks
                ]
            except Exception:
                item["children_count"] = 0
                item["children"] = []

    return items


def _extract_page_info(item: dict) -> dict[str, Any]:
    """Extract standardised page/database info from a Notion search result."""
    obj_type = item.get("object", "page")
    page_id = item.get("id", "")

    title = "Untitled"
    if obj_type == "page":
        for prop in item.get("properties", {}).values():
            if prop.get("type") == "title":
                rich = prop.get("title", [])
                if rich:
                    title = "".join(t.get("plain_text", "") for t in rich)
                break
    elif obj_type == "database":
        rich = item.get("title", [])
        if rich:
            title = "".join(t.get("plain_text", "") for t in rich)

    return {
        "page_id": page_id,
        "title": title or "Untitled",
        "type": obj_type,
        "last_edited_time": item.get("last_edited_time", ""),
        "children_count": 0,
        "children": [],
    }


# ── Change detection ──────────────────────────────────────────────────────────

def get_page_last_edited(token: str, page_id: str) -> str:
    """Return the last_edited_time ISO string for a page, or '' on failure."""
    nc = _client(token)
    try:
        page = nc.pages.retrieve(page_id=page_id)
        return page.get("last_edited_time", "")
    except Exception:
        return ""


def get_page_status(token: str, page_id: str) -> dict:
    """
    Return the status of a Notion page.

    Returns a dict with:
      - exists (bool): False if the page returned 404 or any request error
      - archived (bool): True if archived or trashed in Notion
      - last_edited_time (str): ISO timestamp, or '' if unavailable
    """
    nc = _client(token)
    try:
        page = nc.pages.retrieve(page_id=page_id)
        return {
            "exists": True,
            "archived": page.get("archived", False) or page.get("in_trash", False),
            "last_edited_time": page.get("last_edited_time", ""),
        }
    except Exception:
        # Any exception (404, auth, network) is treated as "page not accessible"
        return {"exists": False, "archived": True, "last_edited_time": ""}
