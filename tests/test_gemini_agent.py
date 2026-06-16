import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from coach.agents.gemini import GeminiCoachSession, StepEvent, TextEvent
from coach.tools.specs import ToolSpec, object_schema


def _text_response(text: str):
    message = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _tool_response(name: str, args: dict, call_id: str = "call_1"):
    call = SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )
    message = SimpleNamespace(content=None, tool_calls=[call])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class _FakeClient:
    def __init__(self, responses):
        self.completions = _FakeCompletions(responses)
        self.chat = SimpleNamespace(completions=self.completions)


async def _handler(args):
    return {"seen": args["value"]}


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
            session = GeminiCoachSession(history=[("user", "Earlier"), ("assistant", "Reply")])
            events = [event async for event in session.events("Now")]

        self.assertEqual(events, [StepEvent("Using fake data"), TextEvent("Final answer")])
        self.assertEqual(client.completions.calls[0]["tools"][0]["function"]["name"], "fake_tool")
        self.assertEqual(
            session.messages[-2],
            {"role": "tool", "tool_call_id": "call_1", "content": '{"seen": "abc"}'},
        )
        self.assertEqual(session.messages[-1], {"role": "assistant", "content": "Final answer"})
