"""
This acts as a final wrapper to user
"""
import asyncio
import json
from typing import Callable

import websockets

from .operator.agent_operator_base import AgentOperator
from .service_handler import ServiceHandler


class DynamicAgentClient:

    def __init__(self):
        self.session_id: str | None = None
        self.websocket = None
        self.messages: list = []

        self._on_stream: Callable[[str], None] | None = None
        self._on_invoke: Callable[[str], None] | None = None
        self._accumulated_text = ""
        self._invoke_text = ""
        self._response_done = asyncio.Event()
        self._listen_task = None
        self._connected = True
        self._needs_reconnect = True

        self.tool_map = {}  # {prefixed_tool_name: callable}

    @classmethod
    async def connect(cls, server_addr: str):
        """Start the shared webhook server and store the service address."""
        await ServiceHandler.connect(server_addr)

    @classmethod
    async def create(cls, setting: str, reconnect_keep: int = 30, session_id: str = None) -> "DynamicAgentClient":
        """Create a new session, or resume an existing one by passing its session_id."""
        instance = cls()
        instance.session_id, instance.websocket, instance.messages = await ServiceHandler.create_session(
            setting, instance, reconnect_keep=reconnect_keep, session_id=session_id
        )
        instance._listen_task = asyncio.ensure_future(instance._listen())
        return instance

    async def _listen(self):
        """Listen for messages from server. Sets _connected=False on disconnect."""
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

                    if data.get("finished"):
                        self._response_done.set()
        except websockets.exceptions.ConnectionClosed:
            pass
        except asyncio.CancelledError:
            pass

        self._connected = False

    async def trigger(
        self,
        text: str,
        on_stream: Callable[[str], None] = None,
        on_invoke: Callable[[str], None] = None,
        bucket_name: str = None,
    ):
        await self._ensure_connected()

        self._on_stream = on_stream
        self._on_invoke = on_invoke
        self._accumulated_text = ""
        self._invoke_text = ""
        self._response_done.clear()

        # Fire HTTP trigger, response streams via WebSocket
        await ServiceHandler.trigger(self.session_id, text, bucket_name=bucket_name)
        # Wait for streaming response to complete
        await self._response_done.wait()
        result = self._accumulated_text
        self._accumulated_text = ""
        return result

    async def add_operator(self, operator):
        if not isinstance(operator, AgentOperator):
            raise TypeError("operator must be an AgentOperator instance")
        return await ServiceHandler.add_operator(self.session_id, self, operator)

    @classmethod
    async def create_bucket(cls, name: str, description: str = ""):
        """Create a new bucket for storing knowledge."""
        return await ServiceHandler.create_bucket(name, description)

    @classmethod
    async def check_bucket(cls, name: str):
        """Check if a bucket exists."""
        return await ServiceHandler.check_bucket(name)

    @classmethod
    async def delete_bucket(cls, name: str):
        """Delete a bucket and all its contents."""
        return await ServiceHandler.delete_bucket(name)

    @classmethod
    async def inbound(cls, instruction_query: str, knowledge_text: str, bucket_name: str):
        """Inbound knowledge into a bucket."""
        return await ServiceHandler.inbound(instruction_query, knowledge_text, bucket_name)

    @classmethod
    async def retrieve(cls, query: str, bucket_name: str, top_k: int = 10):
        """Retrieve knowledge from a bucket."""
        return await ServiceHandler.retrieve(query, bucket_name, top_k)

    async def _ensure_connected(self):
        """Ensure websocket is connected, reconnect if needed."""
        if self._connected:
            return

        if not self._needs_reconnect:
            raise Exception("Connection closed and reconnect disabled")

        print("Connection lost. Reconnecting...")
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

        self.websocket = await ServiceHandler.reconnect_session(self.session_id)
        self._connected = True
        self._listen_task = asyncio.ensure_future(self._listen())
        print("Reconnected successfully!")

    async def _reconnect(self) -> bool:
        """Attempt to reconnect to existing session. Returns True if successful."""
        if self.session_id is None:
            return False
        try:
            print(f"Attempting to reconnect to session {self.session_id}...")
            self.websocket = await ServiceHandler.reconnect_session(self.session_id)
            print("Reconnection successful!")
            return True
        except Exception as e:
            print(f"Reconnection failed: {e}")
            return False

    async def close(self):
        self._needs_reconnect = False
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
            ServiceHandler.unregister_client(self.session_id, client_instance=self)
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