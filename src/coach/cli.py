"""Interactive CLI to talk to the coach. Replaced by the web API in a later phase,
but the fastest way to validate the agent + tools end-to-end now.

    coach          # or: python -m coach.cli
"""
import asyncio

from coach.agents.gemini import GeminiCoachSession, TextEvent


async def _run() -> None:
    print("Coach ready. Ask about your training (Ctrl-C to quit).\n")
    client = GeminiCoachSession()
    while True:
        try:
            prompt = (await asyncio.to_thread(input, "you > ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not prompt:
            continue
        print("coach > ", end="", flush=True)
        async for event in client.events(prompt):
            if isinstance(event, TextEvent):
                print(event.text, end="", flush=True)
        print("\n")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
