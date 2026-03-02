"""
This acts as a final wrapper to user
"""
import asyncio
import json
from typing import Callable

import websockets

from .operator.agent_operator_base import AgentOperator
from .session_client_structs import ClientInvokeMessage
from .service_handler import ServiceHandler


class DynamicAgentClient:

    def __init__(self):
        self.session_id: str | None = None
        self.websocket = None

        self._on_stream: Callable[[str], None] | None = None
        self._on_invoke: Callable[[str], None] | None = None
        self._on_compact: Callable[[bool], None] | None = None
        self._accumulated_text = ""
        self._invoke_text = ""
        self._response_done = asyncio.Event()
        self._listen_task = None

        self.tool_map = {}  # {prefixed_tool_name: callable}

    @classmethod
    async def connect(cls, server_addr: str):
        """Start the shared webhook server and store the service address."""
        await ServiceHandler.connect(server_addr)

    @classmethod
    async def create(cls, setting: str, messages: list = None, compact_limit: int = 40, compact_target: int = 20) -> "DynamicAgentClient":
        instance = cls()
        instance.session_id, instance.websocket = await ServiceHandler.create_session(
            setting, instance, messages=messages or [], compact_limit=compact_limit, compact_target=compact_target
        )
        instance._listen_task = asyncio.ensure_future(instance._listen())
        return instance

    async def _listen(self):
        """Continuously receive and handle messages from the server."""
        try:
            async for message in self.websocket:
                data = json.loads(message)
                if data.get("type") == "agent_chunk":
                    text = data["text"]

                    if text:
                        self._accumulated_text += text
                        self._invoke_text += text
                        if self._on_stream:
                            self._on_stream(text)

                    if data.get("invoked"):
                        if self._on_invoke:
                            self._on_invoke(self._invoke_text)
                        self._invoke_text = ""

                    if data.get("compacting") is not None:
                        if self._on_compact:
                            self._on_compact(data["compacting"])

                    if data.get("finished"):
                        self._response_done.set()
        except websockets.exceptions.ConnectionClosed:
            pass
        except asyncio.CancelledError:
            pass

    async def trigger(
        self,
        text: str,
        on_stream: Callable[[str], None] = None,
        on_invoke: Callable[[str], None] = None,
        on_compact: Callable[[bool], None] = None,
    ):
        self._on_stream = on_stream
        self._on_invoke = on_invoke
        self._on_compact = on_compact
        self._accumulated_text = ""
        self._invoke_text = ""
        self._response_done.clear()

        msg = ClientInvokeMessage(text=text)
        await self.websocket.send(msg.model_dump_json())
        await self._response_done.wait()
        result = self._accumulated_text
        self._accumulated_text = ""
        return result

    async def add_operator(self, operator):
        if not isinstance(operator, AgentOperator):
            raise TypeError("operator must be an AgentOperator instance")
        return await ServiceHandler.add_operator(self.session_id, self, operator)

    async def close(self):
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

        if self.websocket:
            await self.websocket.close()
            self.websocket = None

        if self.session_id:
            ServiceHandler.unregister_client(self.session_id)
            self.session_id = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    def __del__(self):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.close())
        except Exception:
            pass