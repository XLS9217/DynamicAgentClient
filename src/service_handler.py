"""
Singleton that owns the shared webhook server and the connection to the service.
All clients go through ServiceHandler — one webhook port for all sessions.
"""
import asyncio
import json
import re
import socket

import httpx
import uvicorn
import websockets
from fastapi import FastAPI, Request as FastAPIRequest


def _make_httpx_client() -> httpx.AsyncClient:
    """Create an httpx client that bypasses proxy for http:// targets."""
    return httpx.AsyncClient(mounts={"http://": None})


def _sanitize_json(raw: str) -> str:
    """Fix common LLM JSON quirks like leading zeros (e.g. 00.5 -> 0.5)."""
    return re.sub(r'(?<![0-9])0+(\d+\.)', r'\1', raw)


class ServiceHandler:
    """
    Class-only singleton.
    1. Runs one webhook server shared across all sessions
    2. Maps session_id -> client for routing tool execution
    3. Handles connect (create_session + websocket) on behalf of client
    4. Handles add_operator on behalf of client
    """

    _app: FastAPI = None
    _server = None
    _server_task = None
    _port: int = None
    _server_addr: str = None
    _clients: dict = {}  # session_id -> DynamicAgentClient
    _http: httpx.AsyncClient = None

    @classmethod
    async def connect(cls, server_addr: str):
        """
        First-time setup: start webhook server and store the service address.
        Subsequent calls with same address are a no-op.
        """
        cls._server_addr = server_addr.rstrip("/")
        if cls._http is None:
            cls._http = _make_httpx_client()
        if cls._server is None:
            await cls._start_webhook_server()

    @classmethod
    async def create_session(cls, setting: str, client, messages: list = None) -> tuple:
        """
        POST /create_session to the service, register client, return (session_id, websocket).
        """
        resp = await cls._http.post(
            f"{cls._server_addr}/create_session",
            json={"setting": setting, "webhook_port": cls._port, "messages": messages or []},
        )
        resp.raise_for_status()
        data = resp.json()

        session_id = data["session_id"]
        socket_url = data["socket_url"]

        cls._clients[session_id] = client

        ws = await websockets.connect(socket_url)
        return session_id, ws

    @classmethod
    async def add_operator(cls, session_id: str, client, operator):
        """
        1. Register tool_map entries on the client
        2. POST serialized operator to the service
        """
        serialized = operator.get_serialized_operator()

        for tool_name, tool_info in operator._tools.items():
            prefixed_name = f"{serialized.name}_{tool_name}"
            client.tool_map[prefixed_name] = tool_info["callable"]

        resp = await cls._http.post(
            f"{cls._server_addr}/agent_operator",
            json={
                "session_id": session_id,
                "operator": serialized.model_dump(),
            },
        )
        resp.raise_for_status()
        return resp.json()

    @classmethod
    def unregister_client(cls, session_id: str):
        cls._clients.pop(session_id, None)

    @classmethod
    async def _start_webhook_server(cls):
        cls._port = cls._find_free_port()
        cls._app = FastAPI()

        @cls._app.post("/webhook")
        async def webhook(request: FastAPIRequest):
            data = await request.json()
            session_id = data.get("session_id")
            client = cls._clients.get(session_id)

            tool_name = data.get("name", "")
            arguments = json.loads(_sanitize_json(data.get("arguments", "{}")))

            for key, value in arguments.items():
                if isinstance(value, str):
                    try:
                        arguments[key] = json.loads(value)
                    except (json.JSONDecodeError, ValueError):
                        pass

            callable_func = client.tool_map.get(tool_name)
            result = callable_func(**arguments)
            return str(result)

        config = uvicorn.Config(
            cls._app, host="0.0.0.0", port=cls._port,
            log_level="error", lifespan="off",
        )
        cls._server = uvicorn.Server(config)
        cls._server_task = asyncio.create_task(cls._server.serve())
        await asyncio.sleep(0.5)

    @classmethod
    def _find_free_port(cls):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            return s.getsockname()[1]

    @classmethod
    async def stop(cls):
        if cls._http:
            await cls._http.aclose()
            cls._http = None
        if cls._server:
            cls._server.should_exit = True
            if cls._server_task:
                try:
                    await cls._server_task
                except asyncio.CancelledError:
                    pass
                cls._server_task = None
            cls._server = None
            cls._port = None
        cls._clients.clear()