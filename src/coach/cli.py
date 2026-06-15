"""Interactive CLI to talk to the coach. Replaced by the web API in a later phase,
but the fastest way to validate the agent + tools end-to-end now.

    coach          # or: python -m coach.cli
"""
import asyncio

from claude_agent_sdk import AssistantMessage, ClaudeSDKClient, TextBlock

from coach.agents.coordinator import build_options


async def _run() -> None:
    options = build_options()
    print("Coach ready. Ask about your training (Ctrl-C to quit).\n")
    async with ClaudeSDKClient(options=options) as client:
        while True:
            try:
                # Run blocking input() off the event loop so the SDK's background
                # subprocess reader keeps running while we wait for the user.
                prompt = (await asyncio.to_thread(input, "you > ")).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if not prompt:
                continue
            await client.query(prompt)
            print("coach > ", end="", flush=True)
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            print(block.text, end="", flush=True)
            print("\n")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
