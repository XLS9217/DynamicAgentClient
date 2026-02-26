# Agent Operator Use Guide

## 1. Create a custom operator by inheriting from AgentOperator:

```python
from agent_operator_base import AgentOperator, agent_tool

class MyOperator(AgentOperator):
    def __init__(self):
        super().__init__()
```

## 2. Define tools using the @agent_tool decorator:

```python
@agent_tool(description="Search for information")
def search(self, query: str, limit: int = 10):
    '''
    :param query: The search query string
    :param limit: Maximum number of results to return
    '''
    # Your implementation here
    return f"Found results for: {query}"
```

### Schema Generation Rules:
The final OpenAI-compatible function schema is automatically generated based on these rules:
- **Function Name**: Used as the tool name in the schema.
- **Description**: Taken from the `@agent_tool(description=...)` argument. If omitted, it falls back to the method's docstring.
- **Parameters**: 
    - All method parameters except `self` are included.
    - **Types**: Determined by Python type hints:
        - `str` → `"string"` (default if no hint)
        - `int`, `float` → `"number"`
        - `bool` → `"boolean"`
    - **Descriptions**: Extracted from docstrings using the `:param name: description` format.
    - **Required Fields**: Parameters without a default value are automatically marked as `required`.
- **Structure**: The tool is wrapped in the standard OpenAI format: `{"type": "function", "function": {...}}`.

## 3. Register your operator with the agent:

```python
operator = MyOperator()
agent.add_operator(operator)
```

## 4. The agent will automatically discover and use your tools.

## Notes:
- Use type hints (str, int, bool, float) for proper schema generation
- Document parameters with :param name: description in docstrings
- Tools can be sync or async functions
- Only methods (with self) can be decorated with @agent_tool
