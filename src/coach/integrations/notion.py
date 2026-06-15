"""Notion notifications: add a report as a child page under a shared parent page.

Setup:
1. Create an internal integration at https://www.notion.so/my-integrations and copy
   its "Internal Integration Secret" into NOTION_API_KEY.
2. Open the Notion page you want reports under, and via the "..." menu share/connect it
   to your integration.
3. Copy that page's id (the 32-char hex in its URL) into NOTION_PARENT_PAGE_ID.
"""
from __future__ import annotations

import httpx

from coach.config import settings

API_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
TEXT_LIMIT = 2000  # Notion's per-rich-text-object character cap
BLOCKS_PER_REQUEST = 100  # Notion's per-request children cap


def notion_configured() -> bool:
    return bool(settings.notion_api_key and settings.notion_parent_page_id)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.notion_api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _chunks(text: str) -> list[str]:
    return [text[i : i + TEXT_LIMIT] for i in range(0, len(text), TEXT_LIMIT)] or [""]


def _rich_text(content: str) -> list[dict]:
    return [{"type": "text", "text": {"content": c}} for c in _chunks(content)]


def _block(block_type: str, content: str) -> dict:
    return {
        "object": "block",
        "type": block_type,
        block_type: {"rich_text": _rich_text(content)},
    }


def _markdown_to_blocks(body: str) -> list[dict]:
    """Light markdown -> Notion blocks. Handles headings, bullets, and paragraphs;
    table/other lines fall through as plain paragraphs."""
    blocks: list[dict] = []
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("### "):
            blocks.append(_block("heading_3", s[4:]))
        elif s.startswith("## "):
            blocks.append(_block("heading_2", s[3:]))
        elif s.startswith("# "):
            blocks.append(_block("heading_1", s[2:]))
        elif s.startswith(("- ", "* ")):
            blocks.append(_block("bulleted_list_item", s[2:]))
        else:
            blocks.append(_block("paragraph", s))
    return blocks


def create_page(title: str, body: str) -> None:
    if not notion_configured():
        raise RuntimeError(
            "Notion not configured. Set NOTION_API_KEY and NOTION_PARENT_PAGE_ID in .env."
        )

    blocks = _markdown_to_blocks(body)
    with httpx.Client(base_url=API_URL, headers=_headers(), timeout=30) as c:
        resp = c.post(
            "/pages",
            json={
                "parent": {"page_id": settings.notion_parent_page_id},
                "properties": {"title": {"title": [{"text": {"content": title}}]}},
                "children": blocks[:BLOCKS_PER_REQUEST],
            },
        )
        resp.raise_for_status()
        page_id = resp.json()["id"]

        for i in range(BLOCKS_PER_REQUEST, len(blocks), BLOCKS_PER_REQUEST):
            resp = c.patch(
                f"/blocks/{page_id}/children",
                json={"children": blocks[i : i + BLOCKS_PER_REQUEST]},
            )
            resp.raise_for_status()
