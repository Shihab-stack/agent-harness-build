"""Model/tool orchestration for the interactive assistant."""

import inspect
import json
from typing import Any, Callable

from openai import AsyncOpenAI

from agent_herness_build.mcp import MCPRoute, call_mcp_tool
from agent_herness_build.models import ModelConfig
from agent_herness_build.tools.files import FILE_TOOLS
from agent_herness_build.tools.memory import save_memory

MAX_TOOL_ROUNDS = 8
LOCAL_TOOLS = {**FILE_TOOLS, "save_memory": save_memory}
SYSTEM_PROMPT = """You are a helpful personal assistant. Be concise.

Use list_project_files and read_project_file for read-only inspection of
allowlisted project files. Never use project inspection to access credentials
or local configuration. The regular file tools operate on the user's workspace;
write_file can create files only under workspace/generated/ and asks before
overwriting. Use save_memory for useful lasting facts the user shares. Use only
the sandbox tool for Python code; never route code execution through another
Python MCP server. Use only provided tools for time and web fetch tasks. Be
clear about tool errors.

Remembered facts:
{memory}"""


async def call_tool(
    name: str,
    args: dict[str, Any],
    mcp_routes: dict[str, MCPRoute],
) -> str:
    """Validate and dispatch a local tool call or route it to an MCP server."""
    local_tool = LOCAL_TOOLS.get(name)
    if local_tool is not None:
        try:
            inspect.signature(local_tool).bind(**args)
        except TypeError as exc:
            return f"tool error: invalid arguments for {name}: {exc}"
        return local_tool(**args)
    return await call_mcp_tool(name, args, mcp_routes)


async def run_agent(
    prompt: str,
    messages: list[dict[str, Any]],
    client: AsyncOpenAI,
    model: ModelConfig,
    tool_schemas: list[dict[str, Any]],
    mcp_routes: dict[str, MCPRoute],
    memory: str,
    on_token: Callable[[str], None] | None = None,
) -> str:
    """Stream a turn, run any requested tools, and retain completed history."""
    previous_messages = list(messages)
    if messages:
        messages[0] = {
            "role": "system",
            "content": SYSTEM_PROMPT.format(memory=memory),
        }
    else:
        messages.append(
            {"role": "system", "content": SYSTEM_PROMPT.format(memory=memory)}
        )
    messages.append({"role": "user", "content": prompt})

    completed = False
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            response = await client.chat.completions.create(
                model=model.model,
                messages=messages,
                tools=tool_schemas or None,
                stream=True,
            )
            tool_calls: dict[int, dict[str, Any]] = {}
            answer_parts: list[str] = []
            async for chunk in response:
                delta = chunk.choices[0].delta
                if delta.content:
                    answer_parts.append(delta.content)
                    if on_token is not None:
                        on_token(delta.content)
                for tool_delta in delta.tool_calls or []:
                    tool_call = tool_calls.setdefault(
                        tool_delta.index,
                        {
                            "id": "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        },
                    )
                    if tool_delta.id:
                        tool_call["id"] = tool_delta.id
                    if tool_delta.function:
                        if tool_delta.function.name:
                            tool_call["function"]["name"] += tool_delta.function.name
                        if tool_delta.function.arguments:
                            tool_call["function"]["arguments"] += (
                                tool_delta.function.arguments
                            )

            answer = "".join(answer_parts)
            if not tool_calls:
                messages.append({"role": "assistant", "content": answer})
                completed = True
                return answer

            ordered_tool_calls = [tool_calls[index] for index in sorted(tool_calls)]
            messages.append(
                {
                    "role": "assistant",
                    "content": answer or None,
                    "tool_calls": ordered_tool_calls,
                }
            )
            for tool_call in ordered_tool_calls:
                try:
                    arguments = json.loads(tool_call["function"]["arguments"] or "{}")
                except json.JSONDecodeError as exc:
                    result = f"tool error: invalid JSON arguments: {exc}"
                else:
                    if not isinstance(arguments, dict):
                        result = "tool error: arguments must be a JSON object"
                    else:
                        print(
                            f"  [tool] {tool_call['function']['name']}({arguments})"
                        )
                        result = await call_tool(
                            tool_call["function"]["name"], arguments, mcp_routes
                        )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": result,
                    }
                )

        raise RuntimeError(
            f"Agent exceeded the limit of {MAX_TOOL_ROUNDS} tool rounds."
        )
    finally:
        if not completed:
            messages[:] = previous_messages
