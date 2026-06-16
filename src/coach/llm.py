"""Gemini calls for tool-less utility transforms."""
from __future__ import annotations

from openai import AsyncOpenAI

from coach.config import settings

_client: AsyncOpenAI | None = None
_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set.")
        _client = AsyncOpenAI(
            api_key=settings.gemini_api_key,
            base_url=_BASE_URL,
        )
    return _client


async def complete(prompt: str, *, max_tokens: int = 1024, model: str | None = None) -> str:
    """Run a single-turn, tool-less completion and return the text."""
    resp = await get_client().chat.completions.create(
        model=model or settings.coach_utility_model,
        reasoning_effort=settings.coach_reasoning_effort or None,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return (resp.choices[0].message.content or "").strip()
