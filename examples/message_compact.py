"""
uv run -m dynamic_agent_client.examples.message_compact
"""
import asyncio
import os
from dotenv import load_dotenv

from dynamic_agent_client.examples.test_messages import ssd_chat_cn_79
from dynamic_agent_client import DynamicAgentClient

load_dotenv()


async def main():
    port = os.getenv("PORT", "7777")

    await DynamicAgentClient.connect(server_addr=f"http://localhost:{port}")

    # 100 messages with low compact settings to trigger compaction
    client = await DynamicAgentClient.create(
        setting="You are a knowledgeable hardware advisor.",
        messages=ssd_chat_cn_79,
        compact_limit=10,
        compact_target=5,
    )
    print(f"Session created: {client.session_id}")
    print(f"Initial messages: {len(ssd_chat_cn_79)}")

    def on_stream(chunk: str):
        print(chunk, end="", flush=True)

    def on_compact(compacting: bool):
        print("(compacting start)" if compacting else "(compacting end)", end="", flush=True)

    response = await client.trigger(
        "根据我们之前的对话，用3个要点总结SSD涨价的关键信息。",
        on_stream=on_stream,
        on_compact=on_compact,
    )
    print()

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())