"""Coach long-term memory: durable facts the athlete asks the coach to remember.

Memories are injected into the coordinator + subagent system prompts (see
coach.agents.coordinator) so every chat reply, daily readiness brief and weekly
review keeps them in mind. The athlete can add them conversationally (the coach
calls the `remember` tool) or manually via the web UI.
"""
from __future__ import annotations

from sqlalchemy import select

from coach.db import SessionLocal
from coach.models import CoachMemory


def list_memories() -> list[dict]:
    with SessionLocal() as s:
        rows = s.execute(
            select(CoachMemory).order_by(CoachMemory.created_at.asc())
        ).scalars().all()
        return [
            {"id": m.id, "content": m.content, "source": m.source,
             "created_at": m.created_at.isoformat() if m.created_at else None}
            for m in rows
        ]


def add_memory(content: str, source: str = "chat") -> dict | None:
    content = (content or "").strip()
    if not content:
        return None
    with SessionLocal() as s:
        row = CoachMemory(content=content[:1000], source=source)
        s.add(row)
        s.commit()
        s.refresh(row)
        return {"id": row.id, "content": row.content, "source": row.source,
                "created_at": row.created_at.isoformat() if row.created_at else None}


def delete_memory(memory_id: int) -> bool:
    with SessionLocal() as s:
        row = s.get(CoachMemory, memory_id)
        if row is None:
            return False
        s.delete(row)
        s.commit()
        return True


def memories_block() -> str:
    """Render saved memories as a prompt section, or '' if there are none."""
    mems = list_memories()
    if not mems:
        return ""
    lines = "\n".join(f"- {m['content']}" for m in mems)
    return (
        "WHAT YOU KNOW ABOUT THIS ATHLETE (things they've asked you to remember — "
        "honour these in every recommendation):\n"
        f"{lines}\n"
    )
