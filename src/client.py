"""
This acts as a final wrapper to user
"""
import asyncio
import requests
import websockets

from dynamic_agent_client.src.session_client_structs import ClientInvokeMessage
from dynamic_agent_service.service.session_service_structs import AgentResponseMessage, AgentResponseChunk


class DynamicAgentClient:

    def __init__(self, server_addr: str):
        self.server_addr = server_addr
        self.session_id: str | None = None
        self.websocket = None

    @classmethod
    async def create(cls, setting: str, server_addr: str) -> "DynamicAgentClient":
        instance = cls(server_addr)

        # HTTP call to create session and init AGI
        resp = requests.post(f"{server_addr}/create_session", json={"setting": setting})
        resp.raise_for_status()
        instance.session_id = resp.json()["session_id"]

        # Connect websocket with session_id
        ws_addr = server_addr.replace("http://", "ws://")
        instance.websocket = await websockets.connect(f"{ws_addr}/agent_session?session_id={instance.session_id}")

        asyncio.ensure_future(instance._listen())
        return instance

    async def trigger(self, text: str):
        msg = ClientInvokeMessage(text=text)
        await self.websocket.send(msg.model_dump_json())

    async def _listen(self):
        """Print all incoming websocket messages continuously."""
        async for raw in self.websocket:
            if '"agent_chunk"' in raw:
                chunk = AgentResponseChunk.model_validate_json(raw)
                print(chunk.text, end="", flush=True)
            else:
                msg = AgentResponseMessage.model_validate_json(raw)
                print(f"\n[done] {msg.text}")

    async def close(self):
        if self.websocket:
            await self.websocket.close()
            self.websocket = None

    async def add_operator(self):
        pass