"""Example 3: add time and fetch MCP tools to a workspace-enabled agent."""

import asyncio
import inspect
import json
import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import AsyncOpenAI

client = AsyncOpenAI(
    base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
    api_key="ollama",
)
MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")

WORKSPACE = Path(__file__).resolve().parents[1] / "workspace"
MAX_TOOL_ROUNDS = 8

MCP_SERVERS = {
    "time": StdioServerParameters(command="uvx", args=["mcp-server-time"]),
    "fetch": StdioServerParameters(
        command="uvx",
        args=["mcp-server-fetch"],
        env={
            "npm_config_audit": "false",
            "npm_config_fund": "false",
            "npm_config_loglevel": "silent",
        },
    ),
}


def list_files() -> str:
    """List files in the assistant's workspace folder."""
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    return "\n".join(path.name for path in WORKSPACE.iterdir()) or "(empty)"


def workspace_path(filename: str) -> Path:
    """Resolve a filename and reject paths outside the assistant workspace."""
    root = WORKSPACE.resolve()
    path = (root / filename).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("file must be inside the assistant's workspace folder") from exc
    return path


def read_file(filename: str) -> str:
    """Read a file from the assistant's workspace folder."""
    try:
        path = workspace_path(filename)
    except ValueError as exc:
        return f"error: {exc}"
    return path.read_text(encoding="utf-8") if path.is_file() else f"error: no {filename}"


def write_file(filename: str, content: str) -> str:
    """Write (or overwrite) a file in the assistant's workspace folder."""
    try:
        path = workspace_path(filename)
    except ValueError as exc:
        return f"error: {exc}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"wrote {filename}"


LOCAL_TOOLS = {
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
}

LOCAL_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List the files in the user's workspace folder.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read one file from the user's workspace folder.",
            "parameters": {
                "type": "object",
                "properties": {"filename": {"type": "string"}},
                "required": ["filename"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Write (or overwrite) a file inside the assistant's workspace folder."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["filename", "content"],
                "additionalProperties": False,
            },
        },
    },
]


async def connect_mcp(
    stack: AsyncExitStack,
) -> tuple[list[dict[str, Any]], dict[str, tuple[ClientSession, str]]]:
    """Start configured MCP servers and return tool schemas and routing data."""
    tool_schemas = list(LOCAL_TOOL_SCHEMAS)
    mcp_tools: dict[str, tuple[ClientSession, str]] = {}

    for server_name, params in MCP_SERVERS.items():
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()

        tools = (await session.list_tools()).tools
        for tool in tools:
            model_tool_name = f"mcp_{server_name}_{tool.name}"
            mcp_tools[model_tool_name] = (session, tool.name)
            tool_schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": model_tool_name,
                        "description": tool.description or f"{tool.name} from {server_name}",
                        "parameters": tool.input_schema,
                    },
                }
            )
        print(f"  [mcp] connected '{server_name}': {[tool.name for tool in tools]}")

    return tool_schemas, mcp_tools


async def call_tool(
    name: str,
    args: dict[str, Any],
    mcp_tools: dict[str, tuple[ClientSession, str]],
) -> str:
    """Run a local tool or route a call to its MCP server."""
    local_tool = LOCAL_TOOLS.get(name)
    if local_tool is not None:
        try:
            inspect.signature(local_tool).bind(**args)
        except TypeError as exc:
            return f"tool error: invalid arguments for {name}: {exc}"
        return local_tool(**args)

    route = mcp_tools.get(name)
    if route is None:
        return f"error: unknown tool {name}"
    session, server_tool_name = route
    result = await session.call_tool(
        server_tool_name,
        {key: value for key, value in args.items() if value is not None},
    )
    text = "\n".join(item.text for item in result.content if hasattr(item, "text"))
    if result.is_error:
        return f"tool error: {text}"
    return text or "(tool returned no text)"


async def run_agent(
    user_message: str,
    tool_schemas: list[dict[str, Any]],
    mcp_tools: dict[str, tuple[ClientSession, str]],
) -> str:
    """Run one request through the model and its available tools."""
    messages = [
        {"role": "system", "content": "You are a helpful personal assistant."},
        {"role": "user", "content": user_message},
    ]
    for _ in range(MAX_TOOL_ROUNDS):
        response = await client.chat.completions.create(
            model=MODEL, messages=messages, tools=tool_schemas
        )
        message = response.choices[0].message
        if not message.tool_calls:
            return message.content or ""

        messages.append(message)
        for call in message.tool_calls:
            args = json.loads(call.function.arguments or "{}")
            print(f"  [tool] {call.function.name}({args})")
            result = await call_tool(call.function.name, args, mcp_tools)
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": result}
            )

    raise RuntimeError(f"Agent exceeded the limit of {MAX_TOOL_ROUNDS} tool rounds.")


async def main() -> None:
    """Connect the MCP servers and run the interactive assistant prompt loop."""
    async with AsyncExitStack() as stack:
        tool_schemas, mcp_tools = await connect_mcp(stack)
        print(
            f"\nv3 assistant ({MODEL}) with {len(tool_schemas)} tools "
            "- type /exit or press ctrl+c to quit"
        )
        try:
            while True:
                question = await asyncio.to_thread(input, "\nyou: ")
                if question.strip().lower() in {"/exit", "/quit"}:
                    break
                print(
                    "\nassistant:",
                    await run_agent(question, tool_schemas, mcp_tools),
                )
        except (EOFError, KeyboardInterrupt):
            print("\nbye!")


if __name__ == "__main__":
    asyncio.run(main())
