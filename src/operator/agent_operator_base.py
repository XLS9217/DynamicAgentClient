
import inspect
import re
from abc import ABC
from typing import Callable, get_type_hints
from logging import getLogger

from pydantic import BaseModel

logger = getLogger(__name__)

def _parse_docstring_params(docstring: str | None) -> dict[str, str]:
    """Parse :param name: description lines from a docstring."""
    if not docstring:
        return {}

    param_descriptions = {}
    pattern = r':param\s+(\w+):\s*(.+?)(?=:param|:return|:rtype|$)'
    matches = re.findall(pattern, docstring, re.DOTALL)

    for name, desc in matches:
        cleaned_desc = ' '.join(desc.split())
        if cleaned_desc:
            param_descriptions[name] = cleaned_desc

    return param_descriptions


def _build_schema(func: Callable, description: str) -> dict:
    """Build OpenAI function schema for a method (skips self)"""
    sig = inspect.signature(func)
    try:
        type_hints = get_type_hints(func)
    except Exception:
        type_hints = {}

    param_descriptions = _parse_docstring_params(func.__doc__)

    properties = {}
    required = []

    for param_name, param in sig.parameters.items():
        if param_name == 'self':
            continue

        param_type = type_hints.get(param_name, str)

        json_type = "string"
        if param_type in (int, float):
            json_type = "number"
        elif param_type is bool:
            json_type = "boolean"

        prop_schema = {"type": json_type}
        if param_name in param_descriptions:
            prop_schema["description"] = param_descriptions[param_name]

        properties[param_name] = prop_schema

        if param.default == inspect.Parameter.empty:
            required.append(param_name)

    return {
        "name": func.__name__,
        "description": description or func.__doc__ or "",
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


def agent_tool(description: str = ""):
    """
    Decorator to mark a method as an agent tool.
    Only works on class methods (must have self as first param).
    """
    def decorator(func: Callable) -> Callable:
        sig = inspect.signature(func)
        params = list(sig.parameters.keys())

        if not params or params[0] != 'self':
            raise ValueError("@agent_tool can only decorate class methods")

        func._agent_tool_schema = _build_schema(func, description)
        return func

    return decorator


def description(func: Callable) -> Callable:
    """
    Decorator to mark a method as the operator's description provider.
    The method must take only self and return a str.
    Used to supply the agent's system prompt description.
    """
    sig = inspect.signature(func)
    params = list(sig.parameters.keys())
    if not params or params[0] != 'self':
        raise ValueError("@description can only decorate class methods")
    func._is_operator_description = True
    return func


def flow(func: Callable) -> Callable:
    """
    Decorator to mark a method as the operator's flow provider.
    The method must take only self and return a str.
    Used to supply the agent's step-by-step flow instructions.
    """
    sig = inspect.signature(func)
    params = list(sig.parameters.keys())
    if not params or params[0] != 'self':
        raise ValueError("@flow can only decorate class methods")
    func._is_operator_flow = True
    return func

class SerializedOperatorStructure(BaseModel):
    """
    Work with service's operator handler
    """
    name: str # name of class
    tools: list[dict] #openai tools schema
    description: str | None = None # description of the operator
    flows: list[dict[str,str]] | None = None # each individual flow, yes, there could be multiple flow, flow_name: flow_text

class AgentOperator(ABC):
    """
    Base class for operators that provide tools to the agent.
    Subclasses define @agent_tool methods.
    """

    def __init__(self):
        self._tools: dict[str, dict] = {}
        self._description_func = None
        self._flow_funcs: list[tuple[str, Callable]] = []
        self._collect_tools()

    def _collect_tools(self):
        """Find all @agent_tool, @description, and @flow methods on this instance"""
        for name in dir(self):
            if name.startswith('_'):
                continue

            try:
                attr = getattr(self, name)
            except Exception as e:
                print(f"Warning: Failed to get attribute '{name}': {e}")
                continue

            if not callable(attr):
                continue

            func = getattr(attr, '__func__', attr)

            if hasattr(func, '_agent_tool_schema'):
                self._tools[name] = {
                    "schema": func._agent_tool_schema,
                    "callable": attr,
                }
                logger.info(f"Collected tool: {name}")

            elif hasattr(func, '_is_operator_description'):
                self._description_func = attr
                logger.info(f"Collected description: {name}")

            elif hasattr(func, '_is_operator_flow'):
                self._flow_funcs.append((name, attr))
                logger.info(f"Collected flow: {name}")

        logger.info(f"Total tools collected: {len(self._tools)}")

    def get_serialized_operator(self) -> SerializedOperatorStructure:
        """Serialize this operator into a SerializedOperatorStructure."""
        class_name = self.__class__.__name__
        tools = []
        for t in self._tools.values():
            schema = dict(t["schema"])
            schema["name"] = f"{class_name}_{schema['name']}"
            tools.append({"type": "function", "function": schema})

        desc = self._description_func() if self._description_func else None

        flows = [{name: func()} for name, func in self._flow_funcs] if self._flow_funcs else None

        return SerializedOperatorStructure(
            name=class_name,
            tools=tools,
            description=desc,
            flows=flows,
        )

    def execute(self, tool_name: str, arguments: dict):
        """Execute a tool by name with given arguments."""
        if tool_name not in self._tools:
            raise ValueError(f"Tool {tool_name} not found in operator")

        callable_func = self._tools[tool_name]["callable"]
        return callable_func(**arguments)
