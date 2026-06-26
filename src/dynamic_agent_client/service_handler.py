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
    async def create_session(cls, setting: str, client, reconnect_keep: int = 30, session_id: str = None) -> tuple:
        """
        POST /create_session to the service, register client, return (session_id, websocket, messages).
        """
        resp = await cls._http.post(
            f"{cls._server_addr}/create_session",
            json={
                "setting": setting,
                "webhook_port": cls._port,
                "reconnect_keep": reconnect_keep,
                "session_id": session_id,
            },
        )
        resp.raise_for_status()
        data = resp.json()

        session_id = data["session_id"]
        socket_url = data["socket_url"]
        messages = data["messages"]

        # Always register/update client - last client wins
        # This handles React strict mode double mount: the second (active) client
        # replaces the first (stale) client that may be garbage collected
        cls._clients[session_id] = client

        ws = await websockets.connect(socket_url)
        return session_id, ws, messages

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
    async def trigger(cls, session_id: str, text: str, bucket_name: str = None):
        """Trigger agent with text input via HTTP POST."""
        resp = await cls._http.post(
            f"{cls._server_addr}/trigger",
            json={"session_id": session_id, "text": text, "bucket_name": bucket_name},
        )
        resp.raise_for_status()
        return resp.json()

    @classmethod
    async def delete_session(cls, session_id: str) -> bool:
        """Delete a session's persisted chat messages via HTTP DELETE."""
        resp = await cls._http.delete(
            f"{cls._server_addr}/session/{session_id}",
        )
        resp.raise_for_status()
        data = resp.json()
        cls._clients.pop(session_id, None)
        return data.get("status") == "ok"

    @classmethod
    async def create_bucket(cls, name: str, description: str = ""):
        """Create a new bucket via HTTP POST."""
        resp = await cls._http.post(
            f"{cls._server_addr}/knowledge/bucket",
            json={
                "name": name,
                "description": description,
            },
        )
        resp.raise_for_status()
        return resp.json()

    @classmethod
    async def check_bucket(cls, name: str):
        """Check if a bucket exists via HTTP GET."""
        resp = await cls._http.get(
            f"{cls._server_addr}/knowledge/bucket/{name}",
        )
        resp.raise_for_status()
        return resp.json()

    @classmethod
    async def delete_bucket(cls, name: str):
        """Delete a bucket via HTTP DELETE."""
        resp = await cls._http.delete(
            f"{cls._server_addr}/knowledge/bucket/{name}",
        )
        resp.raise_for_status()
        return resp.json()

    @classmethod
    async def inbound(cls, instruction_query: str, knowledge_text: str, bucket_name: str):
        """Inbound knowledge into a bucket via HTTP POST."""
        # TO-DO: For large texts this can exceed the timeout. Design an async approach
        # (e.g. return task_id immediately, push result via WebSocket channel).
        resp = await cls._http.post(
            f"{cls._server_addr}/knowledge/inbound",
            json={
                "instruction_query": instruction_query,
                "knowledge_text": knowledge_text,
                "bucket_name": bucket_name,
            },
            timeout=300.0,
        )
        resp.raise_for_status()
        return resp.json()

    @classmethod
    async def retrieve(cls, query: str, bucket_name: str, top_k: int = 10):
        """Retrieve knowledge from a bucket via HTTP POST."""
        resp = await cls._http.post(
            f"{cls._server_addr}/knowledge/retrieve",
            json={
                "query": query,
                "bucket_name": bucket_name,
                "top_k": top_k,
            },
        )
        resp.raise_for_status()
        return resp.json()

    @classmethod
    async def reconnect_session(cls, session_id: str):
        """Reconnect to existing session by session_id, returns websocket."""
        socket_url = f"{cls._server_addr.replace('http', 'ws')}/agent_session?session_id={session_id}"
        print(f"Connecting to: {socket_url}")
        ws = await asyncio.wait_for(websockets.connect(socket_url), timeout=5.0)
        print(f"WebSocket connected!")
        return ws

    @classmethod
    def unregister_client(cls, session_id: str, client_instance=None):
        """
        Unregister a client from the session.

        If client_instance is provided, only unregister if the current registered
        client matches it (prevents stale client from unregistering active client).
        """
        if client_instance is not None:
            current = cls._clients.get(session_id)
            if current is not client_instance:
                # Don't unregister - a different client instance has taken over
                return

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

            # Defensive: check if client exists
            if client is None:
                error_msg = f"Client not found for session {session_id}"
                print(f"[webhook] ERROR: {error_msg}")
                return f"Error: {error_msg}"

            # Defensive: check if tool_map is initialized
            if not hasattr(client, 'tool_map') or client.tool_map is None:
                error_msg = f"Client tool_map not initialized for session {session_id}"
                print(f"[webhook] ERROR: {error_msg}")
                return f"Error: {error_msg}"

            tool_name = data.get("name", "")
            arguments = json.loads(_sanitize_json(data.get("arguments", "{}")))

            for key, value in arguments.items():
                if isinstance(value, str):
                    try:
                        arguments[key] = json.loads(value)
                    except (json.JSONDecodeError, ValueError):
                        pass

            callable_func = client.tool_map.get(tool_name)

            # Defensive: check if tool exists
            if callable_func is None:
                error_msg = f"Tool '{tool_name}' not found in session {session_id}"
                print(f"[webhook] ERROR: {error_msg}")
                return f"Error: {error_msg}"

            # Hook: before tool execution
            if client._on_tool_call:
                try:
                    client._on_tool_call(tool_name, arguments)
                except Exception as e:
                    print(f"[webhook] WARNING: on_tool_call hook failed: {e}")

            # Execute tool
            try:
                result = callable_func(**arguments)
            except Exception as e:
                result = f"Error: Tool execution failed: {e}"
                print(f"[webhook] ERROR: {result}")

            # Hook: after tool execution (fires for success AND error)
            if client._on_tool_result:
                try:
                    client._on_tool_result(tool_name, arguments, result)
                except Exception as e:
                    print(f"[webhook] WARNING: on_tool_result hook failed: {e}")

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
