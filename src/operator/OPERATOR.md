# Agent Operator Use Guide

## 1. Create a custom operator by inheriting from AgentOperator:

```python
from agent_operator_base import AgentOperator, agent_tool, description, flow

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

## 3. Define the agent description using the @description decorator:

Marks a method that returns a string describing the agent's role. Used to build the system prompt.

- Must be a class method (has `self`)
- Must return `str`
- Only one `@description` method per operator

```python
@description
def describe(self) -> str:
    return "You are a helpful assistant that can search and analyze data."
```

## 4. Define the agent flow using the @flow decorator:

Marks a method that returns step-by-step instructions for how the agent should behave.

- Must be a class method (has `self`)
- Must return `str`
- Only one `@flow` method per operator

```python
@flow
def workflow(self) -> str:
    return """
    1. Understand the user's request
    2. Use the search tool to gather information
    3. Analyze and process the results
    4. Return a clear, formatted summary
    """
```

## 5. Register your operator with the agent:

```python
operator = MyOperator()
agent.add_operator(operator)
```

The agent will then have access to:
- `operator.get_description()` — system prompt description
- `operator.get_flow()` — flow instructions
- All `@agent_tool` methods as callable tools

## 6. The agent will automatically discover and use your tools.

## Notes:
- Use type hints (str, int, bool, float) for proper schema generation
- Document parameters with `:param name: description` in docstrings
- Tools can be sync or async functions
- Only methods (with `self`) can be decorated with `@agent_tool`, `@description`, or `@flow`