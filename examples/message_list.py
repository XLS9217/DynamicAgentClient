"""
uv run -m dynamic_agent_client.examples.message_list
"""
import asyncio
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

from dynamic_agent_client.examples.test_messages import ssd_chat
from dynamic_agent_client.src.client import DynamicAgentClient

sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv()


async def main():
    port = os.getenv("PORT", "7777")

    await DynamicAgentClient.connect(server_addr=f"http://localhost:{port}")

    client = await DynamicAgentClient.create(
        setting="You are a knowledgeable hardware advisor.",
        messages=ssd_chat,
    )
    print(f"Session created: {client.session_id}")

    def on_stream(chunk: str):
        print(chunk, end="", flush=True)

    response = await client.trigger(
        "Given our conversation, summarize the key takeaways about the SSD price situation in 3 bullet points.",
        on_stream=on_stream,
    )
    print()

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())