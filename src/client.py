# WebSocket + HTTP client for communicating with dynamic_agent_service.
#
# DynamicAgentClient: main class consumers use to interact with the agent service.
# Responsibilities:
#   - Open/close WebSocket connection for streaming agent responses
#   - HTTP methods for session creation, operator registration, health check
#   - Send operator tool schemas to the service on session start
#   - Route incoming tool-call requests from the agent back to the
#     correct AgentOperatorBase instance and return results
#   - Handle reconnection, timeouts, and error propagation
