"""Memory write/read tools, exposed as an in-process MCP server.

The coordinator gets these so it can persist things the athlete asks it to remember
("remember that my left knee flares up on heavy squats") and recall them on demand.
Saved memories are also injected into every prompt, so the coach keeps them in mind
without having to call `list_memories` each turn.
"""
from __future__ import annotations

import json

from claude_agent_sdk import create_sdk_mcp_server, tool

from coach import memory


def _text(payload) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload, default=str)}]}


@tool(
    "remember",
    "Save a durable fact about the athlete to long-term memory (an injury, a dietary "
    "preference, a target event/date, equipment limits, a standing constraint). Use this "
    "whenever they tell you something worth keeping in mind for future coaching.",
    {"note": str},
)
async def remember(args) -> dict:
    saved = memory.add_memory((args.get("note") or "").strip(), source="chat")
    if saved is None:
        return _text({"error": "Nothing to remember — note was empty."})
    return _text({"saved": True, "memory": saved})


@tool(
    "list_memories",
    "List everything currently saved about the athlete in long-term memory.",
    {},
)
async def list_memories(args) -> dict:
    return _text(memory.list_memories())


memory_server = create_sdk_mcp_server(
    name="memory",
    version="0.1.0",
    tools=[remember, list_memories],
)

MEMORY_TOOL_NAMES = [
    "mcp__memory__remember",
    "mcp__memory__list_memories",
]
