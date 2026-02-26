
import asyncio
import inspect
import json
import re
from abc import ABC
from typing import Callable, get_type_hints
from logging import getLogger
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


class AgentOperator(ABC):
    """
    Base class for operators that provide tools to the agent.
    Subclasses define @agent_tool methods.
    """

    def __init__(self):
        self._tools: dict[str, dict] = {}
        self._description_func = None
        self._flow_func = None
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
                    "func": attr,
                    "schema": func._agent_tool_schema,
                }
                logger.info(f"Collected tool: {name}")

            elif hasattr(func, '_is_operator_description'):
                self._description_func = attr
                logger.info(f"Collected description: {name}")

            elif hasattr(func, '_is_operator_flow'):
                self._flow_func = attr
                logger.info(f"Collected flow: {name}")

        logger.info(f"Total tools collected: {len(self._tools)}")

    def get_description(self) -> str | None:
        """Call the @description method and return its string, or None if not defined."""
        if self._description_func:
            return self._description_func()
        return None

    def get_flow(self) -> str | None:
        """Call the @flow method and return its string, or None if not defined."""
        if self._flow_func:
            return self._flow_func()
        return None

    def get_tools(self) -> list:
        """Get all tools in OpenAI format"""
        return [{"type": "function", "function": t["schema"]} for t in self._tools.values()]

    def get_tools_with_ref(self) -> list:
        """Get all tools with operator reference for execution"""
        return [
            {"type": "function", "function": t["schema"], "_operator": self, "_func_name": name}
            for name, t in self._tools.items()
        ]

    def _sanitize_json_load(self, arguments: str) -> dict | str:
        """Parse JSON with fallback sanitization for control characters. Returns dict or error string."""
        try:
            return json.loads(arguments)
        except json.JSONDecodeError as json_err:
            # Escape raw newlines/tabs inside strings, remove other control chars
            cleaned = arguments.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
            cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', cleaned)
            if cleaned != arguments:
                logger.warning(f"Sanitized JSON: escaped newlines/tabs or removed control chars")
                try:
                    return json.loads(cleaned)
                except json.JSONDecodeError as retry_err:
                    logger.error(f"JSON parse error after sanitize: {retry_err}")
                    return f"Error: Invalid JSON - {str(retry_err)}"
            logger.error(f"JSON parse error: {json_err}")
            logger.error(f"Raw arguments: {repr(arguments)}")
            return f"Error: Invalid JSON - {str(json_err)}"

    async def execute_tool(self, name: str, arguments: str):
        """Execute a tool by name"""
        if name not in self._tools:
            logger.warning(f"Tool '{name}' not found")
            return f"Error: Tool '{name}' not found"

        func = self._tools[name]["func"]
        try:
            if not arguments:
                args = {}
            else:
                args = self._sanitize_json_load(arguments)
                if isinstance(args, str):
                    return args

            logger.info(f"Executing tool: {name} with args: {args}")

            if asyncio.iscoroutinefunction(func):
                result = await func(**args)
            else:
                result = func(**args)

            logger.info(f"Tool '{name}' completed")
            return result
        except Exception as e:
            logger.error(f"Error executing tool '{name}': {e}")
            logger.error(f"Tool parameters: {arguments}")
            return f"Error executing tool '{name}': {str(e)}"
