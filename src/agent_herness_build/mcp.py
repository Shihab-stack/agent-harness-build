"""Load MCP server configuration and connect tools exposed by those servers."""

import json
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agent_herness_build.paths import CONFIG_DIR

LOCAL_CONFIG = CONFIG_DIR / "mcp_servers.json"
EXAMPLE_CONFIG = CONFIG_DIR / "mcp_servers.example.json"

MCPRoute = tuple[ClientSession, str]


def load_server_config() -> dict[str, Any]:
    """Load local MCP settings, falling back to the committed example file."""
    config_path = LOCAL_CONFIG if LOCAL_CONFIG.is_file() else EXAMPLE_CONFIG
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not load MCP configuration from {config_path}: {exc}") from exc
    if not isinstance(config, dict):
        raise ValueError(f"{config_path} must contain a JSON object")
    servers = config.get("mcpServers")
    if not isinstance(servers, dict):
        raise ValueError(f"{config_path} must define an 'mcpServers' object")
    return servers


async def connect_mcp(
    stack: AsyncExitStack,
) -> tuple[list[dict[str, Any]], dict[str, MCPRoute]]:
    """Connect configured MCP processes and return schemas and routing data."""
    tool_schemas: list[dict[str, Any]] = []
    routes: dict[str, MCPRoute] = {}
    for server_name, spec in load_server_config().items():
        if not isinstance(spec, dict) or not isinstance(spec.get("command"), str):
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

        params = StdioServerParameters(command=spec["command"], args=args, env=env)
        read_stream, write_stream = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()

        server_tools = (await session.list_tools()).tools
        for tool in server_tools:
            model_name = f"mcp_{server_name}_{tool.name}"
            if model_name in routes:
                raise ValueError(f"Duplicate MCP tool name: {model_name}")
            routes[model_name] = (session, tool.name)
            tool_schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": model_name,
                        "description": tool.description or f"{tool.name} from {server_name}",
                        "parameters": tool.input_schema,
                    },
                }
            )
        print(f"  [mcp] connected '{server_name}': {[tool.name for tool in server_tools]}")
    return tool_schemas, routes


async def call_mcp_tool(name: str, args: dict[str, Any], routes: dict[str, MCPRoute]) -> str:
    """Call a registered MCP tool and return its textual result."""
    if name not in routes:
        return f"error: unknown tool {name}"
    session, server_tool_name = routes[name]
    result = await session.call_tool(server_tool_name, args)
    text = "\n".join(item.text for item in result.content if hasattr(item, "text"))
    if result.is_error:
        return f"tool error: {text}"
    return text or "(tool returned no text)"
