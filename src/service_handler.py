"""
Only
"""

class ServiceHandler:
    """

    handles
    1. webhook server
    2. map of session_id : client , later use this to do function call use the tool map in client
    3. initial connect to return the websocket

    Delete the following after impletement
    I want to use like

    client = await DynamicAgentClient.connect(server_addr=f"http://localhost:{port}")
    client = await DynamicAgentClient.create(setting="You are a helpful math assistant.")
    then do other stuff like what we are doing now

    """

    _app = None

    @classmethod
    async def connect(cls, server_addr: str):
        """
        Do the initial change the client.py is doing now
        return the websocket to client
        """
        pass

    @classmethod
    async def _find_free_port(cls):
        pass

    @classmethod
    async def _start_webhook_server(cls):
        pass