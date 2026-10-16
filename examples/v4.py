"""Example 4: add durable memory to the file and MCP tool examples."""

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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT_ROOT / "workspace"
MEMORY_FILE = WORKSPACE / "memory.md"
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

SYSTEM_PROMPT = """You are a helpful personal assistant.

Remembered facts about the user:
{memory}

Use save_memory for new, useful, lasting facts the user has shared. Use only
the provided tools for file, time, and web-fetch tasks. Be clear when a tool
reports an error."""


def workspace_path(filename: str) -> Path:
    """Resolve a workspace filename and reject paths outside that folder."""
    root = WORKSPACE.resolve()
    path = (root / filename).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("file must be inside the assistant's workspace folder") from exc
    return path


def list_files() -> str:
    """List files in the assistant workspace, creating the folder if needed."""
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    return "\n".join(path.name for path in WORKSPACE.iterdir()) or "(empty)"


def read_file(filename: str) -> str:
    """Read a workspace file, refusing paths outside the assistant workspace."""
    try:
        path = workspace_path(filename)
    except ValueError as exc:
        return f"error: {exc}"
    if not path.is_file():
        return f"error: no file named {filename}"
    return path.read_text(encoding="utf-8")


def write_file(filename: str, content: str) -> str:
    """Create or overwrite a workspace file without allowing path traversal."""
    try:
        path = workspace_path(filename)
    except ValueError as exc:
        return f"error: {exc}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"wrote {filename}"


def load_memory() -> str:
    """Return saved long-term memory, or a clear message when none exists."""
    if MEMORY_FILE.is_file():
        return MEMORY_FILE.read_text(encoding="utf-8")
    return "(nothing saved yet)"


def save_memory(fact: str) -> str:
    """Append one lasting user fact to the local long-term memory file."""
    with MEMORY_FILE.open("a", encoding="utf-8") as memory_file:
        memory_file.write(f"- {fact}\n")
    return f"saved: {fact}"


LOCAL_TOOLS = {
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
    "save_memory": save_memory,
}

LOCAL_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List the files in the assistant's workspace folder.",
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
            "description": "Read one file in the assistant's workspace folder.",
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
            "description": "Create or overwrite one file in the assistant's workspace.",
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
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Save one useful, lasting fact about the user.",
            "parameters": {
                "type": "object",
                "properties": {"fact": {"type": "string"}},
                "required": ["fact"],
                "additionalProperties": False,
            },
        },
    },
]


async def connect_mcp(
    stack: AsyncExitStack,
) -> tuple[list[dict[str, Any]], dict[str, tuple[ClientSession, str]]]:
    """Start configured MCP servers and register their schemas and routes."""
    tool_schemas = list(LOCAL_TOOL_SCHEMAS)
    mcp_tools: dict[str, tuple[ClientSession, str]] = {}

    for server_name, params in MCP_SERVERS.items():
        read_stream, write_stream = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
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
    """Dispatch a tool call locally or through the matching MCP session."""
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
    messages: list[dict[str, Any]],
    tool_schemas: list[dict[str, Any]],
    mcp_tools: dict[str, tuple[ClientSession, str]],
) -> str:
    """Run the model/tool loop and retain the turn in shared chat history."""
    for _ in range(MAX_TOOL_ROUNDS):
        response = await client.chat.completions.create(
            model=MODEL, messages=messages, tools=tool_schemas
        )
        message = response.choices[0].message
        if not message.tool_calls:
            answer = message.content or ""
            messages.append({"role": "assistant", "content": answer})
            return answer

        messages.append(message)
        for call in message.tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError as exc:
                result = f"tool error: invalid JSON arguments: {exc}"
            else:
                print(f"  [tool] {call.function.name}({args})")
                result = await call_tool(call.function.name, args, mcp_tools)
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": result}
            )

    raise RuntimeError(f"Agent exceeded the limit of {MAX_TOOL_ROUNDS} tool rounds.")


async def main() -> None:
    """Connect tools and run interactive chat with persistent local memory."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT.format(memory=load_memory())}
    ]
    async with AsyncExitStack() as stack:
        tool_schemas, mcp_tools = await connect_mcp(stack)
        print(
            f"\nv4 assistant ({MODEL}) with {len(tool_schemas)} tools "
            "- type /exit or press ctrl+c to quit"
        )
        try:
            while True:
                question = await asyncio.to_thread(input, "\nyou: ")
                if question.strip().lower() in {"/exit", "/quit"}:
                    break
                messages[0] = {
                    "role": "system",
                    "content": SYSTEM_PROMPT.format(memory=load_memory()),
                }
                messages.append({"role": "user", "content": question})
                answer = await run_agent(messages, tool_schemas, mcp_tools)
                print("\nassistant:", answer)
        except (EOFError, KeyboardInterrupt):
            print("\nbye!")


if __name__ == "__main__":
    asyncio.run(main())
