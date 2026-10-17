"""Load MCP configuration and connect tools exposed by those servers."""

import asyncio
import json
import math
import re
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agent_herness_build.paths import CONFIG_DIR

LOCAL_CONFIG = CONFIG_DIR / "mcp_servers.json"
EXAMPLE_CONFIG = CONFIG_DIR / "mcp_servers.example.json"
DEFAULT_STARTUP_TIMEOUT = 20.0
TOOL_NAME_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
SENSITIVE_CONFIG_KEY = re.compile(
    r"(token|secret|password|credential|api[-_]?key|authorization|auth)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MCPRoute:
    """Route an exposed model tool to its MCP session and safety metadata."""

    session: ClientSession
    server_tool_name: str
    description: str
    requires_confirmation: bool


def load_server_config() -> dict[str, Any]:
    """Load local MCP settings, falling back to the committed example file."""
    config_path = LOCAL_CONFIG if LOCAL_CONFIG.is_file() else EXAMPLE_CONFIG
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Could not load MCP configuration from {config_path}: {exc}"
        ) from exc
    if not isinstance(config, dict):
        raise ValueError(f"{config_path} must contain a JSON object")
    servers = config.get("mcpServers")
    if not isinstance(servers, dict):
        raise ValueError(f"{config_path} must define an 'mcpServers' object")
    return servers


def _validate_server_spec(
    server_name: str, spec: Any
) -> tuple[str, list[str], dict[str, str] | None]:
    if (
        not isinstance(spec, dict)
        or not isinstance(spec.get("command"), str)
        or not spec["command"]
    ):
        raise ValueError(f"MCP server '{server_name}' must define a command")
    args = spec.get("args", [])
    env = spec.get("env")
    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        raise ValueError(f"MCP server '{server_name}' args must be a list of strings")
    if env is not None and (
        not isinstance(env, dict)
        or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in env.items()
        )
    ):
        raise ValueError(f"MCP server '{server_name}' env must contain string values")
    return spec["command"], args, env


def _safe_startup_error(error: Exception, spec: Any) -> str:
    message = str(error)
    if not isinstance(spec, dict):
        return message

    env = spec.get("env")
    if isinstance(env, dict):
        for key, value in env.items():
            if (
                isinstance(key, str)
                and SENSITIVE_CONFIG_KEY.search(key)
                and isinstance(value, str)
                and value
            ):
                message = message.replace(value, "[redacted]")

    args = spec.get("args")
    if isinstance(args, list):
        redact_next = False
        for argument in args:
            if not isinstance(argument, str):
                continue
            if redact_next:
                message = message.replace(argument, "[redacted]")
                redact_next = False
            elif SENSITIVE_CONFIG_KEY.search(argument):
                if "=" in argument:
                    flag, _ = argument.split("=", maxsplit=1)
                    message = message.replace(argument, f"{flag}=[redacted]")
                else:
                    redact_next = True
    return message


def _tool_entries(
    server_name: str, session: ClientSession, server_tools: list[Any]
) -> tuple[list[dict[str, Any]], dict[str, MCPRoute]]:
    schemas: list[dict[str, Any]] = []
    routes: dict[str, MCPRoute] = {}
    for tool in server_tools:
        if (
            not isinstance(getattr(tool, "name", None), str)
            or not TOOL_NAME_PATTERN.fullmatch(tool.name)
        ):
            raise ValueError(f"MCP server '{server_name}' exposed a tool with an invalid name")
        input_schema = getattr(tool, "input_schema", None)
        if not isinstance(input_schema, dict) or input_schema.get("type") != "object":
            raise ValueError(
                f"MCP server '{server_name}' tool '{tool.name}' has an invalid input schema"
            )
        model_name = f"mcp_{server_name}_{tool.name}"
        if not TOOL_NAME_PATTERN.fullmatch(model_name):
            raise ValueError(
                f"MCP server '{server_name}' exposed a tool name that is too long "
                "or invalid after routing"
            )
        if model_name in routes:
            raise ValueError(f"Duplicate MCP tool name: {model_name}")
        description = (
            tool.description or f"{tool.name} from {server_name}"
        )
        annotations = getattr(tool, "annotations", None)
        read_only = getattr(annotations, "read_only_hint", None) is True
        destructive = getattr(annotations, "destructive_hint", None) is True
        routes[model_name] = MCPRoute(
            session=session,
            server_tool_name=tool.name,
            description=description,
            requires_confirmation=not read_only or destructive,
        )
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": model_name,
                    "description": description,
                    "parameters": input_schema,
                },
            }
        )
    return schemas, routes


async def _connect_server(
    stack: AsyncExitStack,
    server_name: str,
    spec: Any,
) -> tuple[list[dict[str, Any]], dict[str, MCPRoute]]:
    command, args, env = _validate_server_spec(server_name, spec)
    params = StdioServerParameters(command=command, args=args, env=env)
    read_stream, write_stream = await stack.enter_async_context(stdio_client(params))
    session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
    await session.initialize()
    server_tools = (await session.list_tools()).tools
    return _tool_entries(server_name, session, server_tools)


async def _close_failed_server(server_stack: AsyncExitStack, server_name: str) -> None:
    try:
        await server_stack.aclose()
    except Exception as exc:
        print(
            f"  [mcp] cleanup failed for '{server_name}': "
            f"{type(exc).__name__}"
        )


async def connect_mcp(
    stack: AsyncExitStack,
    selected_servers: set[str] | None = None,
    startup_timeout: float = DEFAULT_STARTUP_TIMEOUT,
) -> tuple[list[dict[str, Any]], dict[str, MCPRoute]]:
    """Connect selected MCP processes independently; failed optional servers are skipped."""
    if not math.isfinite(startup_timeout) or startup_timeout <= 0:
        raise ValueError("MCP startup timeout must be a finite positive number")

    configured = load_server_config()
    if selected_servers is not None:
        unknown = selected_servers - configured.keys()
        if unknown:
            raise ValueError(
                "Unknown MCP server(s): " + ", ".join(sorted(unknown))
            )

    tool_schemas: list[dict[str, Any]] = []
    routes: dict[str, MCPRoute] = {}
    for server_name, spec in configured.items():
        if selected_servers is not None and server_name not in selected_servers:
            print(f"  [mcp] disabled '{server_name}' (not selected)")
            continue

        server_stack = AsyncExitStack()
        try:
            async with asyncio.timeout(startup_timeout):
                server_schemas, server_routes = await _connect_server(
                    server_stack, server_name, spec
                )
            duplicate_names = routes.keys() & server_routes.keys()
            if duplicate_names:
                raise ValueError(
                    "Duplicate MCP tool name(s): " + ", ".join(sorted(duplicate_names))
                )
        except TimeoutError:
            await _close_failed_server(server_stack, server_name)
            print(
                f"  [mcp] failed '{server_name}': startup timed out "
                f"after {startup_timeout:g}s"
            )
            continue
        except asyncio.CancelledError:
            await _close_failed_server(server_stack, server_name)
            raise
        except Exception as exc:
            error_message = _safe_startup_error(exc, spec)
            print(
                f"  [mcp] failed '{server_name}': "
                f"{type(exc).__name__}: {error_message}"
            )
            await _close_failed_server(server_stack, server_name)
            continue

        stack.push_async_callback(server_stack.aclose)
        routes.update(server_routes)
        tool_schemas.extend(server_schemas)
        print(
            f"  [mcp] connected '{server_name}': {len(server_schemas)} tool(s)"
        )
    return tool_schemas, routes


async def call_mcp_tool(
    name: str,
    args: dict[str, Any],
    routes: dict[str, MCPRoute],
) -> str:
    """Call a registered MCP tool and return its textual result."""
    route = routes.get(name)
    if route is None:
        return f"error: unknown tool {name}"
    try:
        result = await route.session.call_tool(route.server_tool_name, args)
    except Exception as exc:
        return f"tool error calling {name}: {type(exc).__name__}: {exc}"
    text = "\n".join(item.text for item in result.content if hasattr(item, "text"))
    if result.is_error:
        return f"tool error: {text}"
    return text or "(tool returned no text)"
