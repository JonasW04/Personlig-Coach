"""Direct Anthropic Messages API for tool-less utility calls.

The Claude Agent SDK shells out to the Node `claude` CLI, which is the right tool
when the model needs MCP tools or subagents. But plain text transforms (expanding a
focus goal into a directive, extracting an action plan from a review) need none of
that — spinning up the CLI subprocess for them is pure overhead. Those go straight to
the API here, on a cheap/fast model (see settings.coach_utility_model).

Auth reuses ANTHROPIC_API_KEY, which coach.config force-exports from .env.
"""
from __future__ import annotations

from anthropic import AsyncAnthropic

from coach.config import settings

_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def complete(prompt: str, *, max_tokens: int = 1024, model: str | None = None) -> str:
    """Run a single-turn, tool-less completion and return the text."""
    resp = await _get_client().messages.create(
        model=model or settings.coach_utility_model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()
