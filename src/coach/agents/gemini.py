from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, AsyncIterator

from coach.agents.coordinator import build_system_prompt, coach_tools
from coach.config import settings
from coach.llm import get_client
from coach.tools.specs import ToolSpec

log = logging.getLogger("coach.agents.gemini")

MAX_TOOL_ROUNDS = 8
FOLLOW_UP_CONTEXT_ONLY_PROMPT = """This is a follow-up in an ongoing coaching chat.

Answer using only the conversation history and prior tool results already present
in the messages. Do not claim to have checked fresh data. If the user asks for
information that is not in the existing context, briefly say what extra data
would be needed."""

MEMORY_WRITE_PATTERN = re.compile(
    r"\b(remember|keep in mind|don't forget|do not forget|save that|note that)\b",
    re.IGNORECASE,
)
FOLLOW_UP_DATA_PATTERN = re.compile(
    r"\b("
    r"today|tonight|yesterday|tomorrow|this week|last week|next week|"
    r"latest|recent|current|now|new|fresh|updated|since|"
    r"cardio|run|running|ride|cycling|strava|pace|distance|"
    r"workout|lifting|hevy|bench|squat|deadlift|press|"
    r"body|weight|weigh|withings|fat|muscle|"
    r"sleep|recovery|readiness|hrv|heart rate|"
    r"volume|tonnage|sets|reps|exercise|session|sessions"
    r")\b",
    re.IGNORECASE,
)
FOLLOW_UP_CONTEXT_PATTERN = re.compile(
    r"\b("
    r"make (that|it)|rewrite|rephrase|summari[sz]e|shorter|more concise|"
    r"bullet|bullets|table|format|explain|what do you mean|"
    r"expand|elaborate|simplify|same|above|previous|last answer|your answer"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TextEvent:
    text: str


@dataclass(frozen=True)
class StepEvent:
    label: str


AgentEvent = TextEvent | StepEvent


def _coerce_history(history: list[tuple[str, str]] | None) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [{"role": "system", "content": build_system_prompt()}]
    for role, content in history or []:
        if role in {"user", "assistant"} and content.strip():
            messages.append({"role": role, "content": content})
    return messages


def _tool_payload(tool: ToolSpec, args: dict[str, Any]) -> str:
    return json.dumps({"tool": tool.name, "args": args}, sort_keys=True)


def _chat_kwargs(
    *,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if settings.coach_reasoning_effort:
        kwargs["reasoning_effort"] = settings.coach_reasoning_effort
    return kwargs


def _has_prior_assistant_text(messages: list[dict[str, Any]]) -> bool:
    return any(
        msg.get("role") == "assistant" and str(msg.get("content") or "").strip()
        for msg in messages[:-1]
    )


def _is_memory_write_request(prompt: str) -> bool:
    return bool(MEMORY_WRITE_PATTERN.search(prompt))


def _is_context_only_follow_up(prompt: str) -> bool:
    text = " ".join(prompt.strip().lower().split())
    if not text or FOLLOW_UP_DATA_PATTERN.search(text):
        return False
    if FOLLOW_UP_CONTEXT_PATTERN.search(text):
        return True
    words = text.split()
    context_starts = (
        "why",
        "how so",
        "what do you mean",
        "can you explain",
        "could you explain",
        "make it",
        "make that",
        "turn that",
        "put that",
        "format that",
        "same",
        "yes",
        "ok",
        "okay",
        "no",
    )
    return len(words) <= 8 and text.startswith(context_starts)


def _should_try_follow_up_fast_path(
    messages: list[dict[str, Any]], prompt: str
) -> bool:
    return (
        _has_prior_assistant_text(messages)
        and not _is_memory_write_request(prompt)
        and _is_context_only_follow_up(prompt)
    )


def _follow_up_fast_path_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not messages or messages[0].get("role") != "system":
        return [{"role": "system", "content": FOLLOW_UP_CONTEXT_ONLY_PROMPT}, *messages]
    system = {
        **messages[0],
        "content": f"{messages[0].get('content', '')}\n\n{FOLLOW_UP_CONTEXT_ONLY_PROMPT}",
    }
    return [system, *messages[1:]]


def _tool_call_extra_content(call: Any) -> dict[str, Any] | None:
    extra_content = getattr(call, "extra_content", None)
    if extra_content is None:
        model_extra = getattr(call, "model_extra", None)
        if isinstance(model_extra, dict):
            extra_content = model_extra.get("extra_content")
    if extra_content is None and isinstance(call, dict):
        extra_content = call.get("extra_content")
    if hasattr(extra_content, "model_dump"):
        extra_content = extra_content.model_dump(exclude_none=True)
    return extra_content if isinstance(extra_content, dict) else None


def _serialize_tool_call(call: Any) -> dict[str, Any]:
    payload = {
        "id": call.id,
        "type": call.type,
        "function": {
            "name": call.function.name,
            "arguments": call.function.arguments or "{}",
        },
    }
    extra_content = _tool_call_extra_content(call)
    if extra_content:
        payload["extra_content"] = extra_content
    return payload


async def _execute_tool(tool: ToolSpec, args: dict[str, Any]) -> str:
    try:
        result = await tool.handler(args)
    except Exception as exc:  # noqa: BLE001 - report tool failure to the model
        log.exception("tool failed: %s", _tool_payload(tool, args))
        result = {"error": f"{tool.name} failed: {exc}"}
    return json.dumps(result, default=str)


class GeminiCoachSession:
    def __init__(
        self,
        *,
        model: str | None = None,
        history: list[tuple[str, str]] | None = None,
    ) -> None:
        self.model = model or settings.coach_model
        self.messages = _coerce_history(history)
        self._tools = coach_tools()
        self._tool_by_name = {tool.name: tool for tool in self._tools}
        self._openai_tools = [tool.as_openai_tool() for tool in self._tools]

    async def close(self) -> None:
        return None

    async def complete(self, prompt: str, *, max_tokens: int | None = None) -> str:
        text = ""
        async for event in self.events(prompt, max_tokens=max_tokens):
            if isinstance(event, TextEvent):
                text += event.text
        return text.strip()

    async def events(
        self, prompt: str, *, max_tokens: int | None = None
    ) -> AsyncIterator[AgentEvent]:
        self.messages.append({"role": "user", "content": prompt})
        seen_steps: set[str] = set()

        if _should_try_follow_up_fast_path(self.messages, prompt):
            response = await get_client().chat.completions.create(
                **_chat_kwargs(
                    model=self.model,
                    messages=_follow_up_fast_path_messages(self.messages),
                    max_tokens=max_tokens,
                )
            )
            content = response.choices[0].message.content or ""
            if content:
                self.messages.append({"role": "assistant", "content": content})
                yield TextEvent(content)
                return

        for _ in range(MAX_TOOL_ROUNDS):
            response = await get_client().chat.completions.create(
                **_chat_kwargs(
                    model=self.model,
                    messages=self.messages,
                    tools=self._openai_tools,
                    max_tokens=max_tokens,
                )
            )
            message = response.choices[0].message
            tool_calls = message.tool_calls or []
            content = message.content or ""

            if not tool_calls:
                if content:
                    self.messages.append({"role": "assistant", "content": content})
                    yield TextEvent(content)
                return

            self.messages.append(
                {
                    "role": "assistant",
                    "content": content or None,
                    "tool_calls": [_serialize_tool_call(call) for call in tool_calls],
                }
            )

            for call in tool_calls:
                name = call.function.name
                tool = self._tool_by_name.get(name)
                try:
                    args = json.loads(call.function.arguments or "{}")
                    if not isinstance(args, dict):
                        args = {}
                except json.JSONDecodeError:
                    args = {}

                if tool is None:
                    result = json.dumps({"error": f"Unknown tool: {name}"})
                else:
                    if tool.step_label not in seen_steps:
                        seen_steps.add(tool.step_label)
                        yield StepEvent(tool.step_label)
                    result = await _execute_tool(tool, args)

                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": result,
                    }
                )

        self.messages.append(
            {
                "role": "user",
                "content": "Answer now using the tool results already available. Do not call more tools.",
            }
        )
        response = await get_client().chat.completions.create(
            **_chat_kwargs(
                model=self.model,
                messages=self.messages,
                max_tokens=max_tokens,
            )
        )
        content = response.choices[0].message.content or ""
        if content:
            self.messages.append({"role": "assistant", "content": content})
            yield TextEvent(content)


async def run_once(prompt: str, *, model: str | None = None, max_tokens: int | None = None) -> str:
    session = GeminiCoachSession(model=model)
    try:
        return await session.complete(prompt, max_tokens=max_tokens)
    finally:
        await session.close()
