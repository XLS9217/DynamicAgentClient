"""
This acts as a final wrapper to user
"""
import asyncio
import json
import socket

import requests
import websockets
import uvicorn
from fastapi import FastAPI, Request as FastAPIRequest

from dynamic_agent_client.src.operator.agent_operator_base import AgentOperator
from dynamic_agent_client.src.session_client_structs import ClientInvokeMessage


def _find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class DynamicAgentClient:

    def __init__(self, server_addr: str):
        self.server_addr = server_addr.rstrip("/")
        self.session_id: str | None = None
        self.websocket = None

        self._on_stream = None
        self._accumulated_text = ""
        self._response_done = asyncio.Event() # handle for accumulated trigger
        self._listen_task = None

        self.tool_map = {}  # {prefixed_tool_name: callable}

        self._webhook_port = None
        self._webhook_server = None
        self._webhook_task = None

    async def _start_webhook_server(self):
        """Start FastAPI server for tool execution."""
        self._webhook_port = _find_free_port()
        app = FastAPI()
        client = self

        @app.post("/webhook")
        async def webhook(request: FastAPIRequest):
            data = await request.json()
            tool_name = data.get("name", "")
            arguments = json.loads(data.get("arguments", "{}"))

            # Parse string arguments that look like JSON
            for key, value in arguments.items():
                if isinstance(value, str):
                    try:
                        arguments[key] = json.loads(value)
                    except (json.JSONDecodeError, ValueError):
                        pass  # Keep as string if not valid JSON

            callable_func = client.tool_map.get(tool_name)
            if not callable_func:
                return {"error": f"Tool {tool_name} not found"}

            result = callable_func(**arguments)
            return str(result)

        config = uvicorn.Config(app, host="0.0.0.0", port=self._webhook_port, log_level="error", lifespan="off")
        server = uvicorn.Server(config)
        self._webhook_server = server
        self._webhook_task = asyncio.create_task(server.serve())

    @classmethod
    async def create(cls, setting: str, server_addr: str) -> "DynamicAgentClient":
        instance = cls(server_addr)

        # Start webhook server
        await instance._start_webhook_server()
        await asyncio.sleep(0.5)

        # Create session - service will detect our IP
        resp = requests.post(
            f"{instance.server_addr}/create_session",
            json={"setting": setting, "webhook_port": instance._webhook_port},
        )
        resp.raise_for_status()
        data = resp.json()
        instance.session_id = data["session_id"]
        socket_url = data["socket_url"]

        # Connect websocket
        print(f"Connecting to {socket_url}")
        instance.websocket = await websockets.connect(socket_url)

        instance._listen_task = asyncio.ensure_future(instance._listen())
        return instance

    async def _listen(self):
        """Continuously receive and handle messages from the server."""
        try:
            async for message in self.websocket:
                data = json.loads(message)
                if data.get("type") == "agent_chunk":
                    self._accumulated_text += data["text"]
                    if self._on_stream:
                        self._on_stream(data["text"])

                    if data.get("finished"):
                        print("Response finished")
                        self._response_done.set()
        except websockets.exceptions.ConnectionClosed:
            pass
        except asyncio.CancelledError:
            pass

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
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

        if self.websocket:
            await self.websocket.close()
            self.websocket = None

        if hasattr(self, '_webhook_server') and self._webhook_server:
            self._webhook_server.should_exit = True
            if self._webhook_task:
                try:
                    await self._webhook_task
                except asyncio.CancelledError:
                    pass
                self._webhook_task = None
            self._webhook_server = None

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

    async def add_operator(self, operator):
        """
        1. Serialize the operator, build tool_map entries with prefixed names
        2. POST the serialized JSON to the service's /agent_operator endpoint
        """
        if not isinstance(operator, AgentOperator):
            raise TypeError("operator must be an AgentOperator instance")

        serialized = operator.get_serialized_operator()

        # Build flat tool_map: prefixed_name -> callable
        for tool_name, tool_info in operator._tools.items():
            prefixed_name = f"{serialized.name}_{tool_name}"
            self.tool_map[prefixed_name] = tool_info["callable"]

        resp = requests.post(
            f"{self.server_addr}/agent_operator",
            json={
                "session_id": self.session_id,
                "operator": serialized.model_dump(),
            },
        )
        resp.raise_for_status()
        return resp.json()
