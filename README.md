# dynamic_agent_client

Python SDK for communicating with the DynamicAgent service.

## Install

### Using pip

You can install directly from GitHub using `pip`:

```bash
pip install "dynamic-agent-client @ git+https://github.com/XLS9217/DynamicAgent.git#subdirectory=dynamic_agent_client"
```

Note: If you have issues with `#subdirectory` fragment, ensure you are using a recent version of `pip`.

### Using uv

If you are using `uv`, you can add it as a dependency by specifying the Git URL with the subdirectory:

```bash
uv add "dynamic-agent-client @ git+https://github.com/XLS9217/DynamicAgent.git" --subdirectory dynamic_agent_client
```

Note: If you are using an older version of `uv`, you might need to use the fragment syntax:
```bash
uv add "dynamic-agent-client @ git+https://github.com/XLS9217/DynamicAgent.git#subdirectory=dynamic_agent_client"
```

## Quick Start

```python
import asyncio
from dynamic_agent_client import DynamicAgentClient

async def main():
    await DynamicAgentClient.connect(server_addr="http://localhost:7777")

    client = await DynamicAgentClient.create(setting="You are a helpful assistant.")

    response = await client.trigger("Hello!")
    print(response)

    await client.close()

asyncio.run(main())
```

## API

### `DynamicAgentClient`

#### `connect(server_addr: str)`

Class method. Call once before creating any clients.

```python
await DynamicAgentClient.connect(server_addr="http://localhost:7777")
```

#### `create(setting, messages=None, compact_limit=40, compact_target=20)`

Create a session.

| Param | Type | Default | Description |
|---|---|---|---|
| `setting` | `str` | required | System prompt / persona for the agent |
| `messages` | `list` | `[]` | OpenAI-style message history to preload |
| `compact_limit` | `int` | `40` | When message count reaches this, compact triggers |
| `compact_target` | `int` | `20` | After compacting: 1 summary + (target - 1) recent messages |

```python
client = await DynamicAgentClient.create(
    setting="You are a hardware advisor.",
    messages=[
        {"role": "user", "content": "What's a good SSD?"},
        {"role": "assistant", "content": "Samsung 990 EVO is solid."},
    ],
    compact_limit=40,
    compact_target=20,
)
```

#### `trigger(text, on_stream=None, on_invoke=None, on_compact=None)`

Send a message and wait for the full response.

| Param | Type | Description |
|---|---|---|
| `text` | `str` | The user message |
| `on_stream` | `Callable[[str], None]` | Called with each text chunk as it streams |
| `on_invoke` | `Callable[[str], None]` | Called with accumulated text after each LLM call completes |
| `on_compact` | `Callable[[bool], None]` | Called with `True` when compaction starts, `False` when it ends |

```python
response = await client.trigger(
    "Explain quantum computing",
    on_stream=lambda chunk: print(chunk, end="", flush=True),
    on_invoke=lambda text: print(text),
    on_compact=lambda c: print("(compacting...)" if c else "(done)"),
)
```

`on_invoke` is useful with tool-calling agents — it fires after each LLM round, so you see the agent's intermediate reasoning between tool calls.

#### `add_operator(operator)`

Register an operator (tool provider) on the session.

```python
op = MathOperator()
await client.add_operator(op)
```

#### `close()`

Close the websocket and clean up. Also works as an async context manager:

```python
async with await DynamicAgentClient.create(setting="...") as client:
    await client.trigger("Hello")
```

---

### `AgentOperator`

Base class for defining tools the agent can call. Subclass it and use decorators.

#### Decorators

- `@description` — method returning a `str` description of the operator
- `@flow` — method returning a `str` step-by-step instruction (can have multiple)
- `@agent_tool(description="...")` — marks a method as a callable tool

#### Example

```python
import math
from dynamic_agent_client import AgentOperator, agent_tool, description, flow

class MathOperator(AgentOperator):

    @description
    def math_description(self) -> str:
        return "A math operator for vector operations."

    @flow
    def dot_product_flow(self) -> str:
        return "1. Receive two vectors\n2. Compute dot product\n3. Return result"

    @agent_tool(description="Compute dot product of two vectors")
    def dot_product(self, vector_a: list[float], vector_b: list[float]) -> float:
        """
        :param vector_a: The first vector
        :param vector_b: The second vector
        """
        return sum(a * b for a, b in zip(vector_a, vector_b))

    @agent_tool(description="Compute magnitude of a vector")
    def magnitude(self, vector: list[float]) -> float:
        """
        :param vector: The vector
        """
        return math.sqrt(sum(x * x for x in vector))
```

Tool parameter types are inferred from type hints. Docstring `:param name: desc` lines become parameter descriptions in the schema.

## Examples

Run with `uv run -m`:

```bash
# Basic message history + compaction
uv run -m dynamic_agent_client.examples.message_compact

# Tool-calling with operators
uv run -m dynamic_agent_client.examples.one_operator
```