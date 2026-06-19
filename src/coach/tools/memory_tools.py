"""Memory write/read tools exposed to the coach runtime.

The coordinator gets these so it can persist things the athlete asks it to remember
("remember that my left knee flares up on heavy squats") and recall them on demand.
Saved memories are also injected into every prompt, so the coach keeps them in mind
without having to call `list_memories` each turn.
"""
from __future__ import annotations

from coach import memory
from coach.tools.specs import ToolSpec, object_schema


async def remember(args) -> dict:
    saved = memory.add_memory((args.get("note") or "").strip(), source="chat")
    if saved is None:
        return {"error": "Nothing to remember — note was empty."}
    return {"saved": True, "memory": saved}


async def list_memories(args) -> dict:
    return memory.list_memories()


MEMORY_TOOLS = [
    ToolSpec(
        name="remember",
        description=(
            "Save a fact about the athlete to long-term memory that should shape future "
            "coaching: health/status (illness, pain, soreness, injuries, fatigue, poor "
            "sleep, stress), life/schedule (travel, time constraints, equipment access), "
            "or preferences/constraints (diet, exercises they love/avoid, target events). "
            "Call this PROACTIVELY the moment such a detail comes up — do not wait for the "
            "athlete to say 'remember this'. When in doubt, save it."
        ),
        parameters=object_schema(
            {"note": {"type": "string"}},
            required=["note"],
        ),
        handler=remember,
        step_label="Updating what I remember about you",
    ),
    ToolSpec(
        name="list_memories",
        description="List everything currently saved about the athlete in long-term memory.",
        parameters=object_schema(),
        handler=list_memories,
        step_label="Checking what I remember about you",
    ),
]

MEMORY_TOOL_NAMES = [tool.name for tool in MEMORY_TOOLS]
