"""Training focus: the athlete's goal in plain language, plus a model-ready
coaching directive generated from it.

The directive is injected into the coordinator + subagent prompts (see
coach.agents.coordinator) so every chat reply and generated report reflects the
*current* focus. Changing the focus regenerates the standing reports so they
immediately represent the new goal.
"""
from __future__ import annotations

from claude_agent_sdk import AssistantMessage, ClaudeSDKClient, TextBlock, ClaudeAgentOptions

from coach.config import settings
from coach.db import SessionLocal
from coach.models import CoachProfile

# Shipped default — mirrors the old hardcoded "strength & hypertrophy" stance so
# behaviour is unchanged until the user sets their own focus.
DEFAULT_FOCUS_RAW = "Build strength and hypertrophy, with cardio for conditioning."
DEFAULT_DIRECTIVE = (
    "The athlete trains primarily for strength and hypertrophy, with cardio used "
    "for conditioning and recovery support rather than as the main focus. Prioritise "
    "progressive overload and muscle retention; treat rising weight with stable or "
    "falling body fat and rising muscle mass as good progress."
)

_META_PROMPT = """You turn a person's training goal, written in their own words, into a
concise coaching directive that other AI coaches will follow.

Their goal: "{raw}"

Write 2-4 sentences, in the third person ("The athlete..."), that a strength coach, a
cardio coach and a body-composition coach can all use to frame their advice. Make the
priorities and trade-offs explicit (e.g. what to maximise, what to merely maintain, what
to accept). Do not add greetings, headers, markdown, or quotes — output only the directive
text.
"""


def _profile_dict(row: CoachProfile | None) -> dict:
    if row is None:
        return {
            "focus_raw": DEFAULT_FOCUS_RAW,
            "directive": DEFAULT_DIRECTIVE,
            "updated_at": None,
            "is_default": True,
        }
    return {
        "focus_raw": row.focus_raw,
        "directive": row.directive,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "is_default": False,
    }


def get_profile() -> dict:
    with SessionLocal() as s:
        return _profile_dict(s.get(CoachProfile, 1))


def current_directive() -> str:
    """The directive to inject into prompts (falls back to the default)."""
    with SessionLocal() as s:
        row = s.get(CoachProfile, 1)
    return row.directive if row and row.directive else DEFAULT_DIRECTIVE


async def generate_directive(raw: str) -> str:
    """Use a lightweight model call (no tools) to expand a plain-text goal into a
    coaching directive."""
    options = ClaudeAgentOptions(model=settings.coach_model)
    parts: list[str] = []
    async with ClaudeSDKClient(options=options) as client:
        await client.query(_META_PROMPT.format(raw=raw.strip()))
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        parts.append(block.text)
    return "".join(parts).strip() or DEFAULT_DIRECTIVE


def save_profile(focus_raw: str, directive: str) -> dict:
    with SessionLocal() as s:
        row = s.get(CoachProfile, 1)
        if row is None:
            row = CoachProfile(id=1, focus_raw=focus_raw, directive=directive)
            s.add(row)
        else:
            row.focus_raw = focus_raw
            row.directive = directive
        s.commit()
        s.refresh(row)
        return _profile_dict(row)


async def set_focus(focus_raw: str) -> dict:
    """Generate a directive from the plain-text goal and persist it. Returns the
    saved profile. Does NOT regenerate reports — callers schedule that."""
    directive = await generate_directive(focus_raw)
    return save_profile(focus_raw.strip(), directive)
