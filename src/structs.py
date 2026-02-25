# Shared Pydantic structs used by both dynamic_agent_client and dynamic_agent_service.
#
# Includes:
#   - SessionMessage: a single user/assistant message in a session
#   - ToolCallRequest: agent -> operator, requesting a tool invocation
#   - ToolCallResult: operator -> agent, returning the tool output
#   - ToolSchema: describes a tool's name, description, and input parameters
#   - AgentResponseChunk: a streaming chunk of the agent's response
