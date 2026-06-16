import json
import os
import sys
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from coach.agents.gemini import GeminiCoachSession, StepEvent, TextEvent
from coach.tools.specs import ToolSpec, object_schema


def _text_response(text: str):
    message = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _tool_response(
    name: str,
    args: dict,
    call_id: str = "call_1",
    extra_content: dict | None = None,
):
    call_kwargs = {
        "id": call_id,
        "type": "function",
        "function": SimpleNamespace(name=name, arguments=json.dumps(args)),
    }
    if extra_content is not None:
        call_kwargs["extra_content"] = extra_content
    call = SimpleNamespace(
        **call_kwargs,
    )
    message = SimpleNamespace(content=None, tool_calls=[call])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _tool_response_with_model_extra(name: str, args: dict, call_id: str = "call_1"):
    call = SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
        model_extra={"extra_content": {"google": {"thought_signature": "sig-abc"}}},
    )
    message = SimpleNamespace(content=None, tool_calls=[call])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        return self.responses.pop(0)


class _FakeClient:
    def __init__(self, responses):
        self.completions = _FakeCompletions(responses)
        self.chat = SimpleNamespace(completions=self.completions)


async def _handler(args):
    return {"seen": args["value"]}


async def _memory_handler(args):
    return {"saved": args["note"]}


class TestGeminiCoachSession(unittest.IsolatedAsyncioTestCase):
    async def test_tool_call_loop_emits_steps_and_final_text(self):
        tool = ToolSpec(
            name="fake_tool",
            description="Fake tool",
            parameters=object_schema({"value": {"type": "string"}}, required=["value"]),
            handler=_handler,
            step_label="Using fake data",
        )
        client = _FakeClient(
            [
                _tool_response("fake_tool", {"value": "abc"}),
                _text_response("Final answer"),
            ]
        )

        with (
            patch("coach.agents.gemini.get_client", return_value=client),
            patch("coach.agents.gemini.build_system_prompt", return_value="System"),
            patch("coach.agents.gemini.coach_tools", return_value=[tool]),
        ):
            session = GeminiCoachSession()
            events = [event async for event in session.events("Now")]

        self.assertEqual(events, [StepEvent("Using fake data"), TextEvent("Final answer")])
        self.assertEqual(client.completions.calls[0]["tools"][0]["function"]["name"], "fake_tool")
        self.assertEqual(
            session.messages[-2],
            {"role": "tool", "tool_call_id": "call_1", "content": '{"seen": "abc"}'},
        )
        self.assertEqual(session.messages[-1], {"role": "assistant", "content": "Final answer"})

    async def test_preserves_gemini_thought_signature_on_tool_calls(self):
        tool = ToolSpec(
            name="fake_tool",
            description="Fake tool",
            parameters=object_schema({"value": {"type": "string"}}, required=["value"]),
            handler=_handler,
            step_label="Using fake data",
        )
        client = _FakeClient(
            [
                _tool_response_with_model_extra("fake_tool", {"value": "abc"}),
                _text_response("Final answer"),
            ]
        )

        with (
            patch("coach.agents.gemini.get_client", return_value=client),
            patch("coach.agents.gemini.build_system_prompt", return_value="System"),
            patch("coach.agents.gemini.coach_tools", return_value=[tool]),
        ):
            session = GeminiCoachSession()
            events = [event async for event in session.events("Now")]

        self.assertEqual(events, [StepEvent("Using fake data"), TextEvent("Final answer")])
        assistant_message = client.completions.calls[1]["messages"][-2]
        self.assertEqual(
            assistant_message["tool_calls"][0]["extra_content"],
            {"google": {"thought_signature": "sig-abc"}},
        )

    async def test_follow_up_can_answer_without_tools(self):
        client = _FakeClient([_text_response("Use the same plan, but make it shorter.")])

        with (
            patch("coach.agents.gemini.get_client", return_value=client),
            patch("coach.agents.gemini.build_system_prompt", return_value="System"),
            patch("coach.agents.gemini.coach_tools", return_value=[]),
        ):
            session = GeminiCoachSession(
                history=[
                    ("user", "Plan my week from my latest data."),
                    ("assistant", "Here is the plan based on your recent sessions."),
                ]
            )
            events = [event async for event in session.events("Make that more concise.")]

        self.assertEqual(events, [TextEvent("Use the same plan, but make it shorter.")])
        self.assertEqual(len(client.completions.calls), 1)
        self.assertNotIn("tools", client.completions.calls[0])

    async def test_data_follow_up_goes_directly_to_tool_loop(self):
        tool = ToolSpec(
            name="fake_tool",
            description="Fake tool",
            parameters=object_schema({"value": {"type": "string"}}, required=["value"]),
            handler=_handler,
            step_label="Using fake data",
        )
        client = _FakeClient(
            [
                _tool_response("fake_tool", {"value": "fresh"}),
                _text_response("Fresh answer"),
            ]
        )

        with (
            patch("coach.agents.gemini.get_client", return_value=client),
            patch("coach.agents.gemini.build_system_prompt", return_value="System"),
            patch("coach.agents.gemini.coach_tools", return_value=[tool]),
        ):
            session = GeminiCoachSession(
                history=[
                    ("user", "How was my lifting last week?"),
                    ("assistant", "Your lifting was solid."),
                ]
            )
            events = [event async for event in session.events("What about cardio?")]

        self.assertEqual(events, [StepEvent("Using fake data"), TextEvent("Fresh answer")])
        self.assertEqual(len(client.completions.calls), 2)
        self.assertEqual(client.completions.calls[0]["tools"][0]["function"]["name"], "fake_tool")

    async def test_memory_write_follow_up_keeps_tool_access(self):
        tool = ToolSpec(
            name="remember",
            description="Remember a durable fact",
            parameters=object_schema({"note": {"type": "string"}}, required=["note"]),
            handler=_memory_handler,
            step_label="Updating memory",
        )
        client = _FakeClient(
            [
                _tool_response("remember", {"note": "My left knee is cranky."}),
                _text_response("I'll remember that."),
            ]
        )

        with (
            patch("coach.agents.gemini.get_client", return_value=client),
            patch("coach.agents.gemini.build_system_prompt", return_value="System"),
            patch("coach.agents.gemini.coach_tools", return_value=[tool]),
        ):
            session = GeminiCoachSession(
                history=[
                    ("user", "How should I squat today?"),
                    ("assistant", "Keep it submaximal."),
                ]
            )
            events = [
                event async for event in session.events("Remember that my left knee is cranky.")
            ]

        self.assertEqual(events, [StepEvent("Updating memory"), TextEvent("I'll remember that.")])
        self.assertEqual(client.completions.calls[0]["tools"][0]["function"]["name"], "remember")
