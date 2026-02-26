"""
This acts as a final wrapper to user
"""
import asyncio
import json

import requests
import websockets

from dynamic_agent_client.src.operator.agent_operator_base import AgentOperator
from dynamic_agent_client.src.session_client_structs import ClientInvokeMessage


class DynamicAgentClient:

    def __init__(self, server_addr: str):
        """
        :param server_addr: Full base URL including scheme, e.g. "http://localhost:8000" or "https://example.com"
        """
        # session
        self.server_addr = server_addr.rstrip("/")
        self.session_id: str | None = None
        self.websocket = None

        # agent response
        self._on_stream = None
        self._accumulated_text = ""
        self._response_done = asyncio.Event()
        self._listen_task = None

        # operator
        self.operator_dict = {} # operator_name : operator_instance

    @classmethod
    async def create(cls, setting: str, server_addr: str) -> "DynamicAgentClient":
        instance = cls(server_addr)

        # HTTP call to create session and init AGI
        resp = requests.post(f"{instance.server_addr}/create_session", json={"setting": setting})
        resp.raise_for_status()
        data = resp.json()
        instance.session_id = data["session_id"]
        socket_url = data["socket_url"]

        # Connect websocket using url provided by server
        print(f"Connecting to {socket_url}")
        instance.websocket = await websockets.connect(socket_url)

        instance._listen_task = asyncio.ensure_future(instance._listen())
        return instance

    async def _listen(self):
        """Continuously receive and handle AgentResponseChunk messages from the server."""
        async for message in self.websocket:
            data = json.loads(message)
            if data.get("type") == "agent_chunk":
                self._accumulated_text += data["text"]
                if self._on_stream:
                    self._on_stream(data["text"])

                if data.get("finished"):
                    print("Response finished")
                    self._response_done.set()

    async def trigger(
        self,
        text: str,
        on_stream=None,  # called with each chunk's text
    ):
        self._on_stream = on_stream
        self._accumulated_text = ""
        self._response_done.clear()

        msg = ClientInvokeMessage(text=text)
        await self.websocket.send(msg.model_dump_json())
        await self._response_done.wait()
        result = self._accumulated_text
        self._accumulated_text = ""
        return result

    async def close(self):
        if self._listen_task:
            self._listen_task.cancel()
            self._listen_task = None
        if self.websocket:
            await self.websocket.close()
            self.websocket = None

    async def add_operator(self, operator):
        """
        1. Serialize the operator and store locally by name
        2. POST the serialized JSON to the service's /agent_operator endpoint
        """
        if not isinstance(operator, AgentOperator):
            raise TypeError("operator must be an AgentOperator instance")

        serialized = operator.get_serialized_operator()
        self.operator_dict[serialized.name] = operator

        resp = requests.post(
            f"{self.server_addr}/agent_operator",
            json={
                "session_id": self.session_id,
                "operator": serialized.model_dump(),
            },
        )
        resp.raise_for_status()
        return resp.json()
