"""Gemini calls for tool-less utility transforms."""
from __future__ import annotations

from openai import AsyncOpenAI

from coach.config import settings

_client: AsyncOpenAI | None = None
_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


class TruncatedCompletion(RuntimeError):
    """Raised when the model hit the max_tokens limit before finishing."""


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


async def complete(
    prompt: str,
    *,
    max_tokens: int = 1024,
    model: str | None = None,
    raise_on_truncation: bool = False,
) -> str:
    """Run a single-turn, tool-less completion and return the text.

    With raise_on_truncation, a response cut off at max_tokens raises
    TruncatedCompletion instead of returning a partial (often unparseable) body.
    """
    resp = await get_client().chat.completions.create(
        model=model or settings.coach_utility_model,
        reasoning_effort=settings.coach_reasoning_effort or None,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    choice = resp.choices[0]
    if raise_on_truncation and choice.finish_reason == "length":
        raise TruncatedCompletion(
            f"Model output was cut off at the {max_tokens}-token limit before finishing."
        )
    return (choice.message.content or "").strip()
